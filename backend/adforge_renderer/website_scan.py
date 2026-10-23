"""Bounded public-page fetching, robots policy, and literal HTML fact extraction."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
import hashlib
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field
from urllib.robotparser import RobotFileParser

from .facts import (BusinessFact, FactField, FactProvenance, FactSource,
                    ReviewState)

USER_AGENT = "AdForgeAI/0.1 (local business website fact extractor)"
MAX_BODY_BYTES = 1_000_000
MAX_PAGE_TEXT = 20_000
MAX_REDIRECTS = 4
TOTAL_TIMEOUT_SECONDS = 20
SUPPORTED_TYPES = {"text/html", "application/xhtml+xml"}
ROBOTS_TYPES = {"text/plain", "text/html", "application/octet-stream"}
_WS = re.compile(r"\s+")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)")
_PRICE = re.compile(r"(?<!\w)(?:[$€£₹]\s?\d[\d,.]*|\d[\d,.]*\s?(?:USD|EUR|GBP|INR))(?!\w)", re.I)
_CTA = re.compile(r"\b(?:contact us|book now|shop now|buy now|call now|learn more|visit us|get started|schedule now)\b", re.I)
_COLOR = re.compile(r"#[0-9a-fA-F]{6}\b")


class ScanStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    UNSUPPORTED_CONTENT = "unsupported_content"
    FAILED = "failed"


class ScanError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str = Field(max_length=48)
    message: str = Field(max_length=180)


class ScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    original_url: str = Field(max_length=2048)
    final_url: str | None = Field(default=None, max_length=2048)
    status: ScanStatus
    facts: tuple[BusinessFact, ...] = Field(default=(), max_length=32)
    warnings: tuple[str, ...] = Field(default=(), max_length=12)
    error: ScanError | None = None


class FetchPolicyError(Exception):
    def __init__(self, code: str, message: str, status: ScanStatus = ScanStatus.BLOCKED_BY_POLICY):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_reserved
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def normalize_and_validate_url(url: str, resolver=socket.getaddrinfo) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise FetchPolicyError("invalid_url", "Enter a valid public HTTP or HTTPS URL.")
    try:
        p = urlsplit(url)
        if p.scheme.lower() not in {"http", "https"} or not p.netloc or p.username is not None or p.password is not None:
            raise ValueError
        host = p.hostname
        port = p.port
        if not host or any(ord(c) <= 32 for c in host) or "\\" in host:
            raise ValueError
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
        if not host or len(host) > 253:
            raise ValueError
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            if "%" in host or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                    for label in host.split(".")):
                raise ValueError
        if port is not None and not (1 <= port <= 65535):
            raise ValueError
        try:
            ipaddress.ip_address(host.strip("[]"))
            addresses = [host.strip("[]")]
        except ValueError:
            answers = resolver(host, port or (443 if p.scheme.lower() == "https" else 80), type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(row[4][0] for row in answers))
        if not addresses or any(not _public_ip(addr) for addr in addresses):
            raise FetchPolicyError("unsafe_destination", "This destination is not available for website scanning.")
        netloc = f"[{host}]" if ":" in host else host
        if port is not None:
            netloc += f":{port}"
        path = p.path or "/"
        return urlunsplit((p.scheme.lower(), netloc, path, p.query, ""))
    except FetchPolicyError:
        raise
    except (ValueError, UnicodeError, OSError, socket.gaierror):
        raise FetchPolicyError("invalid_or_unresolvable_url", "Enter a valid public HTTP or HTTPS URL.") from None
    except Exception:
        raise FetchPolicyError("dns_failure", "The website address could not be resolved safely.") from None


@dataclass(frozen=True)
class FetchedPage:
    url: str
    content_type: str
    body: bytes


class SafeFetcher:
    """Requests each destination only after fresh DNS validation; redirects are manual."""
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, resolver=socket.getaddrinfo,
                 max_bytes: int = MAX_BODY_BYTES, max_redirects: int = MAX_REDIRECTS):
        self.transport, self.resolver = transport, resolver
        self.max_bytes, self.max_redirects = max_bytes, max_redirects

    async def _request(self, url: str, allowed_types=SUPPORTED_TYPES) -> tuple[int, httpx.Headers, bytes, str]:
        current = url
        seen: set[str] = set()
        for _ in range(self.max_redirects + 1):
            current = normalize_and_validate_url(current, self.resolver)
            if current in seen:
                raise FetchPolicyError("redirect_loop", "The website returned a redirect loop.")
            seen.add(current)
            try:
                async with httpx.AsyncClient(transport=self.transport, follow_redirects=False,
                                             timeout=httpx.Timeout(8, connect=3), trust_env=False,
                                             headers={"User-Agent": USER_AGENT,
                                                      "Accept": "text/html,application/xhtml+xml,text/plain"}) as client:
                    async with client.stream("GET", current) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise FetchPolicyError("invalid_redirect", "The website returned an invalid redirect.")
                            current = urljoin(current, location)
                            continue
                        if response.status_code >= 400:
                            raise FetchPolicyError("http_error", "The website could not be read.", ScanStatus.FAILED)
                        raw_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                        if raw_type not in allowed_types:
                            raise FetchPolicyError("unsupported_content", "The website did not return supported HTML.", ScanStatus.UNSUPPORTED_CONTENT)
                        declared = response.headers.get("content-length")
                        if declared and int(declared) > self.max_bytes:
                            raise FetchPolicyError("body_too_large", "The website page is larger than the scan limit.", ScanStatus.FAILED)
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise FetchPolicyError("body_too_large", "The website page is larger than the scan limit.", ScanStatus.FAILED)
                            chunks.append(chunk)
                        return response.status_code, response.headers, b"".join(chunks), current
            except FetchPolicyError:
                raise
            except httpx.TimeoutException:
                raise FetchPolicyError("timeout", "The website took too long to respond.", ScanStatus.FAILED) from None
            except (httpx.HTTPError, ValueError):
                raise FetchPolicyError("fetch_failed", "The website could not be read.", ScanStatus.FAILED) from None
        raise FetchPolicyError("redirect_limit", "The website redirected too many times.")

    async def fetch(self, url: str) -> FetchedPage:
        start = normalize_and_validate_url(url, self.resolver)
        p = urlsplit(start)
        robots_url = urlunsplit((p.scheme, p.netloc, "/robots.txt", "", ""))
        try:
            _, _, robots_body, robots_final = await self._request(robots_url, ROBOTS_TYPES)
            rp, rf = urlsplit(robots_url), urlsplit(robots_final)
            if (rp.scheme, rp.netloc) != (rf.scheme, rf.netloc):
                raise ValueError("cross-origin robots redirect")
            robots_text = robots_body.decode("utf-8", errors="strict")
            directives = [line.strip() for line in robots_text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
            known = re.compile(r"^(?:user-agent|allow|disallow|crawl-delay|sitemap)\s*:", re.I)
            if not directives or not any(line.lower().startswith("user-agent:") for line in directives) or any(not known.match(line) for line in directives):
                raise ValueError("malformed robots policy")
            parser = RobotFileParser()
            parser.set_url(robots_final)
            parser.parse(robots_text.splitlines())
            if not parser.can_fetch(USER_AGENT, start):
                raise FetchPolicyError("robots_disallowed", "The website's robots policy disallows scanning this page.")
        except FetchPolicyError as exc:
            if exc.code == "http_error":
                raise FetchPolicyError("robots_unavailable", "The website's access policy could not be confirmed.") from None
            raise
        except (UnicodeError, ValueError):
            raise FetchPolicyError("robots_unavailable", "The website's access policy could not be confirmed.") from None
        _, headers, body, final_url = await self._request(start)
        return FetchedPage(final_url, headers.get("content-type", "").split(";", 1)[0].lower(), body)


def _clean(value: str | None, limit: int = 240) -> str | None:
    if not value:
        return None
    value = _WS.sub(" ", value).strip()
    return value[:limit].rstrip() or None


def extract_facts(html: bytes | str, page_url: str) -> tuple[BusinessFact, ...]:
    """Extract literal visible/declared strings; no semantic inference or remote assets."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script,style,template,noscript,iframe,svg,canvas,nav,form,[hidden],[aria-hidden='true']"):
        node.decompose()
    text = _clean(soup.get_text(" ", strip=True), MAX_PAGE_TEXT) or ""
    facts: list[BusinessFact] = []

    def add(field: FactField, value: str | None, method: str, evidence: str | None):
        value = _clean(value)
        if not value or any(f.field == field and f.value.casefold() == value.casefold() for f in facts):
            return
        if field == FactField.SELLING_POINT and sum(f.field == field for f in facts) >= 3:
            return
        if len(facts) >= 32:
            return
        digest = hashlib.sha256(f"{page_url}\0{field.value}\0{value}".encode()).hexdigest()[:28]
        facts.append(BusinessFact(fact_id=f"web-{digest}", field=field, value=value,
                                  provenance=FactProvenance(source=FactSource.WEBSITE,
                                      source_url=page_url, extraction_method=method,
                                      evidence=_clean(evidence, 240)),
                                  review_state=ReviewState.UNREVIEWED))

    def meta(*selectors):
        for selector in selectors:
            tag = soup.select_one(selector)
            if tag and tag.get("content"):
                return tag["content"]
        return None

    name = meta('meta[property="og:site_name"]', 'meta[name="application-name"]')
    method = "meta:og:site_name" if soup.select_one('meta[property="og:site_name"]') else "meta:application-name"
    if not name:
        name = soup.title.get_text(" ", strip=True) if soup.title else None
        method = "title"
    if not name:
        h1 = soup.find("h1")
        name, method = (h1.get_text(" ", strip=True), "heading:h1") if h1 else (None, "")
    add(FactField.BUSINESS_NAME, name, method or "", name)

    description = meta('meta[name="description"]', 'meta[property="og:description"]')
    method = "meta:description" if soup.select_one('meta[name="description"]') else "meta:og:description"
    if not description:
        p = next((p for p in soup.find_all("p") if _clean(p.get_text(" ", strip=True), 240)), None)
        description, method = (p.get_text(" ", strip=True), "visible:p") if p else (None, "")
    add(FactField.PRODUCT_OR_SERVICE, description, method or "", description)

    for li in soup.find_all("li"):
        value = _clean(li.get_text(" ", strip=True))
        if value and len(value) >= 12:
            add(FactField.SELLING_POINT, value, "visible:li", value)
    for match in _CTA.finditer(text):
        add(FactField.CTA, match.group(0), "visible:text", match.group(0))

    for value in dict.fromkeys(_EMAIL.findall(text)):
        add(FactField.CONTACT_INFORMATION, value, "visible:email", value)
    for value in dict.fromkeys(_PHONE.findall(text)):
        if sum(ch.isdigit() for ch in value) >= 8:
            add(FactField.CONTACT_INFORMATION, value, "visible:phone", value)
    address = soup.select_one('[itemprop="streetAddress"]')
    if address:
        value = address.get_text(" ", strip=True)
        add(FactField.ADDRESS, value, "microdata:streetAddress", value)
    price = meta('meta[property="product:price:amount"]')
    if not price:
        price = next(iter(_PRICE.findall(text)), None)
    add(FactField.PRICE, price, "meta:product:price:amount" if soup.select_one('meta[property="product:price:amount"]') else "visible:price", price)
    offer = meta('meta[property="og:description"]')
    if offer and re.search(r"\b(?:offer|sale|discount|% off|free shipping)\b", offer, re.I):
        add(FactField.OFFER, offer, "meta:og:description", offer)
    colors = []
    theme = meta('meta[name="theme-color"]')
    if theme and _COLOR.fullmatch(theme.strip()):
        colors.append(theme.strip())
    for tag in soup.find_all(style=True):
        for color in _COLOR.findall(tag["style"]):
            colors.append(color)
    for color in dict.fromkeys(c.upper() for c in colors):
        add(FactField.BRAND_COLOR, color, "meta:theme-color" if theme == color else "inline-style:hex", color)
        if len([f for f in facts if f.field == FactField.BRAND_COLOR]) >= 2:
            break
    add(FactField.WEBSITE, page_url, "scan:page_url", page_url)
    return tuple(facts)


async def scan_website(url: str, *, fetcher: SafeFetcher | None = None) -> ScanResult:
    fetcher = fetcher or SafeFetcher()
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
            page = await fetcher.fetch(url)
        facts = extract_facts(page.body, page.url)
        useful = tuple(f for f in facts if f.field != FactField.WEBSITE)
        status = ScanStatus.SUCCESS if useful else ScanStatus.PARTIAL
        warnings = () if useful else ("No supported business facts were found on this page.",)
        return ScanResult(original_url=url, final_url=page.url, status=status, facts=facts, warnings=warnings)
    except FetchPolicyError as exc:
        return ScanResult(original_url=url, status=exc.status,
                          error=ScanError(code=exc.code, message=exc.message))
    except TimeoutError:
        return ScanResult(original_url=url, status=ScanStatus.FAILED,
                          error=ScanError(code="total_timeout", message="The website scan took too long to complete."))
    except Exception:
        return ScanResult(original_url=url, status=ScanStatus.FAILED,
                          error=ScanError(code="scan_failed", message="The website scan could not be completed."))
