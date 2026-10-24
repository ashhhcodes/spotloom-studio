from __future__ import annotations

import asyncio
import builtins
import copy
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from adforge_renderer import api
from adforge_renderer.production_package import MAX_PACKAGE_BYTES


FIXTURES = Path(__file__).parent / "fixtures"
VALID = json.loads((FIXTURES / "production-package-valid.json").read_text(encoding="utf-8"))
VALID_V2 = json.loads((FIXTURES / "production-package-v2-valid.json").read_text(encoding="utf-8"))
CORRELATION_ID = VALID["correlationId"]


def _headers(*values: tuple[bytes, bytes]) -> list[tuple[bytes, bytes]]:
    return [(b"content-type", b"application/json"), *values]


def _invoke_stream(
    chunks: list[bytes],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    disconnect_after_first: bool = False,
) -> tuple[int, dict[str, object]]:
    events = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    if not chunks:
        events = [{"type": "http.request", "body": b"", "more_body": False}]
    if disconnect_after_first:
        events = events[:1] + [{"type": "http.disconnect"}]
        if events[0]["type"] == "http.request":
            events[0]["more_body"] = True

    async def receive() -> dict[str, object]:
        return events.pop(0) if events else {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/validate/production-package",
        "raw_path": b"/validate/production-package",
        "query_string": b"",
        "headers": headers if headers is not None else [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "root_path": "",
    }
    response = asyncio.run(api.validate_production_package(Request(scope, receive)))
    return response.status_code, json.loads(response.body)


def _compact_payload(payload: object = VALID) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def test_valid_package_and_structural_findings_return_correlated_evaluations() -> None:
    invalid = copy.deepcopy(VALID)
    invalid["scenes"][0]["durationFrames"] = 179

    with TestClient(api.app) as client:
        valid_response = client.post(
            "/validate/production-package",
            content=_compact_payload(),
            headers={"content-type": "application/json; charset=UTF-8"},
        )
        findings_response = client.post(
            "/validate/production-package",
            content=_compact_payload(invalid),
            headers={"content-type": "application/json"},
        )

    assert valid_response.status_code == 200
    assert valid_response.json()["structurallyValid"] is True
    assert valid_response.json()["correlationId"] == CORRELATION_ID
    assert findings_response.status_code == 200
    assert findings_response.json()["structurallyValid"] is False
    assert findings_response.json()["correlationId"] == CORRELATION_ID
    assert "scene_duration_total_mismatch" in {
        issue["code"] for issue in findings_response.json()["issues"]
    }


def test_v2_preflight_dispatches_and_reports_contract_version_without_resolving_assets() -> None:
    invalid = copy.deepcopy(VALID_V2)
    invalid["scenes"][0]["durationFrames"] = 179

    with TestClient(api.app) as client:
        valid_response = client.post(
            "/validate/production-package",
            content=_compact_payload(VALID_V2),
            headers={"content-type": "application/json"},
        )
        findings_response = client.post(
            "/validate/production-package",
            content=_compact_payload(invalid),
            headers={"content-type": "application/json"},
        )

    assert valid_response.status_code == 200
    assert valid_response.json()["contractVersion"] == "spotloom.production-package.v2"
    assert valid_response.json()["structurallyValid"] is True
    assert findings_response.status_code == 200
    assert findings_response.json()["contractVersion"] == "spotloom.production-package.v2"
    assert findings_response.json()["structurallyValid"] is False
    assert "scene_duration_total_mismatch" in {
        issue["code"] for issue in findings_response.json()["issues"]
    }


@pytest.mark.parametrize(
    "correlation_id, expected_echo",
    [
        (None, None),
        ("not-a-uuid-secret", None),
        ("A714886A-BD4C-4DDE-9F88-8E29C5D764B1", None),
        (CORRELATION_ID, CORRELATION_ID),
    ],
    ids=["missing", "malformed", "noncanonical", "valid"],
)
def test_schema_errors_echo_only_independently_valid_correlation(correlation_id, expected_echo) -> None:
    payload = copy.deepcopy(VALID)
    if correlation_id is None:
        del payload["correlationId"]
    else:
        payload["correlationId"] = correlation_id
    del payload["scenes"]

    with TestClient(api.app) as client:
        response = client.post(
            "/validate/production-package",
            content=_compact_payload(payload),
            headers={"content-type": "application/json"},
        )

    body = response.json()
    assert response.status_code == 422
    assert body["outcome"] == "schema-invalid"
    assert body["correlationId"] == expected_echo
    assert correlation_id != "not-a-uuid-secret" or correlation_id not in response.text


@pytest.mark.parametrize(
    "content_type",
    [None, "text/plain", "application/json; charset=latin-1", "application/json; profile=x"],
    ids=["missing", "wrong-media-type", "wrong-charset", "unsupported-parameter"],
)
def test_unsupported_content_types_return_sanitized_415(content_type) -> None:
    header_values = [] if content_type is None else [(b"content-type", content_type.encode("ascii"))]
    status, body = _invoke_stream([_compact_payload()], headers=header_values)
    assert status == 415
    assert body["issues"][0]["code"] == "unsupported_media_type"
    assert body["correlationId"] is None
    assert _compact_payload().decode("utf-8") not in json.dumps(body)


@pytest.mark.parametrize(
    "content_type",
    [
        b"application/json; charset",
        b'application/json; charset="utf-8',
        b"application/json; charset=utf-8;",
        b"application/json garbage",
        b"application/json; =utf-8",
    ],
    ids=["missing-parameter-value", "unterminated-quoted-value", "empty-parameter", "trailing-token", "missing-parameter-name"],
)
def test_malformed_mime_content_types_return_sanitized_415(content_type: bytes) -> None:
    status, body = _invoke_stream(
        [_compact_payload()], headers=[(b"content-type", content_type)]
    )

    assert status == 415
    assert body["issues"][0]["code"] == "unsupported_media_type"
    assert body["correlationId"] is None
    assert content_type.decode("ascii") not in json.dumps(body)


def test_identical_duplicate_content_lengths_are_rejected() -> None:
    body_bytes = _compact_payload()
    repeated_length = str(len(body_bytes)).encode("ascii")
    status, body = _invoke_stream(
        [body_bytes],
        headers=_headers(
            (b"content-length", repeated_length),
            (b"content-length", repeated_length),
        ),
    )

    assert status == 400
    assert body["issues"][0]["code"] == "invalid_content_length"
    assert body["correlationId"] is None
    assert body_bytes.decode("utf-8") not in json.dumps(body)


def test_utf8_json_content_type_is_accepted() -> None:
    status, body = _invoke_stream(
        [_compact_payload()],
        headers=[(b"content-type", b"application/json; charset=utf-8")],
    )
    assert status == 200
    assert body["correlationId"] == CORRELATION_ID


@pytest.mark.parametrize("length", [b"-1", b"abc", b" 10"])
def test_malformed_content_length_returns_400_without_reading(length) -> None:
    status, body = _invoke_stream(
        [_compact_payload()],
        headers=_headers((b"content-length", length)),
    )
    assert status == 400
    assert body["issues"][0]["code"] == "invalid_content_length"
    assert body["correlationId"] is None


def test_conflicting_content_lengths_are_rejected() -> None:
    status, body = _invoke_stream(
        [_compact_payload()],
        headers=_headers((b"content-length", b"10"), (b"content-length", b"11")),
    )
    assert status == 400
    assert body["issues"][0]["code"] == "invalid_content_length"
    assert body["correlationId"] is None


def test_oversized_declared_content_length_is_rejected_before_reading() -> None:
    status, body = _invoke_stream(
        [],
        headers=_headers((b"content-length", str(MAX_PACKAGE_BYTES + 1).encode("ascii"))),
    )
    assert status == 413
    assert body["issues"][0]["code"] == "payload_too_large"
    assert body["correlationId"] is None


@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_actual_stream_limit_below_at_and_above_boundary(delta) -> None:
    body = _compact_payload()
    target = MAX_PACKAGE_BYTES + delta
    if len(body) > target:
        pytest.skip("fixture unexpectedly exceeds target body size")
    body += b" " * (target - len(body))
    status, result = _invoke_stream([body[:100], body[100:]])
    if delta == 1:
        assert status == 413
        assert result["issues"][0]["code"] == "payload_too_large"
        assert result["correlationId"] is None
    else:
        assert status == 200
        assert result["correlationId"] == CORRELATION_ID


def test_actual_oversized_stream_without_length_is_rejected() -> None:
    body = _compact_payload() + b" " * (MAX_PACKAGE_BYTES + 1)
    status, result = _invoke_stream([body])
    assert status == 413
    assert result["issues"][0]["code"] == "payload_too_large"
    assert result["correlationId"] is None


def test_content_length_must_match_streamed_body() -> None:
    body = _compact_payload()
    status, result = _invoke_stream(
        [body], headers=_headers((b"content-length", str(len(body) + 1).encode("ascii")))
    )
    assert status == 400
    assert result["issues"][0]["code"] == "content_length_mismatch"
    assert result["correlationId"] is None


@pytest.mark.parametrize(
    "raw, expected_code",
    [
        (b"{", "invalid_json"),
        (b"\xff", "invalid_json"),
        (b'{"x":{"k":1,"k":2}}', "invalid_json"),
        (_compact_payload().replace(b'"duration":15', b'"duration":NaN'), "invalid_json"),
        (b"[" * 20_000 + b"]" * 20_000, "invalid_json"),
    ],
    ids=["malformed", "invalid-utf8", "nested-duplicate-key", "nonfinite", "parser-recursion"],
)
def test_json_parse_errors_return_sanitized_400(raw, expected_code) -> None:
    status, body = _invoke_stream([raw])
    assert status == 400
    assert body["issues"][0]["code"] == expected_code
    assert body["correlationId"] is None
    assert len(body["issues"][0]["message"]) <= 120
    assert "traceback" not in json.dumps(body).lower()


@pytest.mark.parametrize(
    "field,value,expected_outcome,expected_code",
    [
        ("scenes", None, "schema-invalid", "package_schema_invalid"),
        ("contractVersion", None, "unsupported", "unsupported_contract_version"),
        ("contractVersion", "spotloom.production-package.v3", "unsupported", "unsupported_contract_version"),
        ("rendererProfileId", "unknown-profile", "unsupported", "unsupported_profile"),
    ],
)
def test_schema_and_unsupported_profile_responses(field, value, expected_outcome, expected_code) -> None:
    payload = copy.deepcopy(VALID)
    if field == "scenes":
        del payload[field]
    elif value is None:
        del payload[field]
    else:
        payload[field] = value
    status, body = _invoke_stream([_compact_payload(payload)])
    assert status == 422
    assert body["outcome"] == expected_outcome
    assert body["correlationId"] == CORRELATION_ID
    assert "contractVersion" not in body
    assert expected_code in {issue["code"] for issue in body["issues"]}


def test_findings_are_deterministic_and_ordered() -> None:
    payload = copy.deepcopy(VALID)
    payload["scenes"][0]["durationFrames"] = 179
    raw = _compact_payload(payload)
    first = _invoke_stream([raw])
    second = _invoke_stream([raw])
    assert first == second
    issues = first[1]["issues"]
    assert issues == sorted(issues, key=lambda issue: (issue["path"], issue["code"], issue["message"]))


def test_unexpected_error_is_sanitized_and_has_safe_error_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_raw: bytes):
        raise RuntimeError("secret server detail")

    monkeypatch.setattr(api, "validate_production_package_json", fail)
    status, body = _invoke_stream([_compact_payload()])
    assert status == 500
    assert body["outcome"] == "internal-error"
    assert UUID(body["errorId"])
    assert body["correlationId"] is None
    assert "secret server detail" not in json.dumps(body)


def test_client_disconnect_abandons_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    def must_not_validate(_raw: bytes):
        raise AssertionError("incomplete body must not be evaluated")

    monkeypatch.setattr(api, "validate_production_package_json", must_not_validate)
    status, body = _invoke_stream([b"{\"partial\":"], disconnect_after_first=True)
    assert status == 400
    assert body["issues"][0]["code"] == "client_disconnected"
    assert body["structurallyValid"] is None
    assert body["correlationId"] is None


def test_route_has_no_filesystem_network_subprocess_database_or_renderer_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("structural preflight attempted a forbidden side effect")

    from adforge_renderer import renderer

    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(renderer, "render_ad", forbidden)

    status, body = _invoke_stream([_compact_payload()])
    assert status == 200
    assert body["structurallyValid"] is True


def test_preproduction_endpoint_contract_remains_unchanged() -> None:
    compatibility = json.loads((FIXTURES / "contract-compatibility.json").read_text(encoding="utf-8"))
    sample = compatibility["validNorthstar"]
    request_body = {
        "correlationId": CORRELATION_ID,
        "facts": {"facts": sample["facts"]},
        "brief": sample["brief"],
        "storyboard": sample["storyboard"],
    }

    with TestClient(api.app) as client:
        response = client.post("/validate/preproduction", json=request_body)
    body = response.json()
    assert response.status_code == 200
    assert body["correlationId"] == CORRELATION_ID
    assert body["evaluationStatus"] == "evaluated-with-limitations"
    assert body["factualVerification"] == "not-performed"
    assert set(body) == {
        "correlationId", "requestSchemaValid", "evaluationStatus", "readinessStatus",
        "briefConfirmationSignal", "factualVerification", "findings", "summary",
        "factSummary", "storyboardSummary",
    }
