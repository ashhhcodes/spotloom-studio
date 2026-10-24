"""Minimal local HTTP application for Spotloom Studio."""

from __future__ import annotations

import argparse
import ipaddress
import logging
from email.message import Message
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from adforge_renderer.integration_schemas import (
    BusinessClaims,
    CreativeBrief,
    PreproductionValidationRequest,
    StoryboardInput,
    validate_contract_input,
)
from adforge_renderer.preproduction_validation import (
    PreproductionValidationResponse,
    evaluate_preproduction,
)
from adforge_renderer.production_package import (
    CONTRACT_VERSION,
    MAX_PACKAGE_BYTES,
    PROFILE_ID,
    validate_production_package_json,
)


logger = logging.getLogger(__name__)


app = FastAPI(
    title="Spotloom Studio API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request, _error: RequestValidationError,
) -> JSONResponse:
    """Return a stable 422 without reflecting submitted values or internal details."""
    return JSONResponse(status_code=422, content={
        "requestSchemaValid": False,
        "evaluationStatus": "not-evaluated",
        "detail": "Invalid request body.",
        "issues": [],
        "plannedRuntimeSeconds": None,
    })


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    """Report that this HTTP application is responding."""
    return {"status": "ok"}


@app.post(
    "/validate/preproduction",
    response_model=PreproductionValidationResponse,
)
def validate_preproduction(
    payload: PreproductionValidationRequest,
) -> PreproductionValidationResponse | JSONResponse:
    """Validate caller-supplied structures and derive runtime without side effects."""
    try:
        result = validate_contract_input(
            facts=payload.facts,
            brief=payload.brief,
            storyboard=payload.storyboard,
        )
        if not result.valid:
            return JSONResponse(
                status_code=422,
                content={
                    "requestSchemaValid": False,
                    "evaluationStatus": "not-evaluated",
                    "detail": "Request does not match the supported pre-production contract.",
                    "issues": [
                        {"path": issue.path, "code": issue.code, "message": issue.message}
                        for issue in result.issues
                    ],
                    "plannedRuntimeSeconds": None,
                },
            )
        return evaluate_preproduction(
            correlation_id=payload.correlationId,
            facts=BusinessClaims.model_validate(payload.facts),
            brief=CreativeBrief.model_validate(payload.brief),
            storyboard=StoryboardInput.model_validate(payload.storyboard),
        )
    except Exception as error:
        # Log only a fixed event and exception class; exception text may contain input.
        logger.error("Pre-production validation failed (%s).", type(error).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "evaluationStatus": "failed",
                "detail": "Pre-production validation could not be completed.",
            },
        )


_PACKAGE_SCHEMA_CODES = {
    "package_schema_invalid",
    "invalid_correlation_id",
    "unsupported_contract_version",
    "unsupported_profile",
}
_PACKAGE_UNSUPPORTED_CODES = {"unsupported_contract_version", "unsupported_profile"}


def _package_error(
    status_code: int,
    code: str,
    message: str,
    *,
    outcome: str = "request-error",
    correlation_id: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "outcome": outcome,
            "correlationId": correlation_id,
            "structurallyValid": None,
            "issues": [{"path": "", "code": code, "message": message}],
        },
    )


def _package_content_type_is_supported(request: Request) -> bool:
    values = [value for name, value in request.scope.get("headers", []) if name.lower() == b"content-type"]
    if len(values) != 1:
        return False
    try:
        header_value = values[0].decode("ascii")
    except UnicodeDecodeError:
        return False
    try:
        parsed = Message()
        parsed["content-type"] = header_value
        media_type = parsed.get_content_type().lower()
        parameters = parsed.get_params()
    except (TypeError, ValueError):
        return False
    if media_type != "application/json":
        return False
    if not parameters or parameters[0][0].lower() != "application/json":
        return False
    charsets = [value for name, value in parameters[1:] if name.lower() == "charset"]
    if len(charsets) > 1 or any(name.lower() != "charset" for name, _ in parameters[1:]):
        return False
    return not charsets or (charsets[0] or "").lower() in {"utf-8", "utf8"}


def _package_content_length(request: Request) -> tuple[int | None, str | None]:
    values = [value for name, value in request.scope.get("headers", []) if name.lower() == b"content-length"]
    if not values:
        return None, None
    if len(values) != 1 or not values[0] or any(byte < 48 or byte > 57 for byte in values[0]):
        return None, "invalid_content_length"
    normalized = values[0].lstrip(b"0") or b"0"
    maximum = str(MAX_PACKAGE_BYTES).encode("ascii")
    if len(normalized) > len(maximum) or (len(normalized) == len(maximum) and normalized > maximum):
        return None, "payload_too_large"
    return int(normalized), None


@app.post("/validate/production-package", include_in_schema=False)
async def validate_production_package(request: Request) -> JSONResponse:
    """Stream a bounded package body and run structural validation only."""
    correlation_id: str | None = None
    try:
        if not _package_content_type_is_supported(request):
            return _package_error(415, "unsupported_media_type", "Content-Type must be application/json with UTF-8 encoding.")

        declared_length, length_error = _package_content_length(request)
        if length_error == "invalid_content_length":
            return _package_error(400, length_error, "Content-Length is malformed or conflicting.")
        if length_error == "payload_too_large":
            return _package_error(413, length_error, "The request body exceeds the 65536-byte limit.")

        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_PACKAGE_BYTES:
                return _package_error(413, "payload_too_large", "The request body exceeds the 65536-byte limit.")
            body.extend(chunk)
        if declared_length is not None and len(body) != declared_length:
            return _package_error(400, "content_length_mismatch", "Content-Length does not match the received body.")

        result = validate_production_package_json(bytes(body))
        correlation_id = result.correlation_id
        if result.issues:
            issue_codes = {issue.code for issue in result.issues}
            if "invalid_json" in issue_codes or "invalid_unicode" in issue_codes:
                return _package_error(400, result.issues[0].code, result.issues[0].message)
            if "payload_too_large" in issue_codes:
                return _package_error(413, "payload_too_large", "The request body exceeds the 65536-byte limit.")
            if issue_codes & _PACKAGE_SCHEMA_CODES:
                outcome = "unsupported" if issue_codes & _PACKAGE_UNSUPPORTED_CODES else "schema-invalid"
                return JSONResponse(
                    status_code=422,
                    content={
                        "outcome": outcome,
                        "correlationId": correlation_id,
                        "structurallyValid": None,
                        "issues": [
                            {"path": issue.path, "code": issue.code, "message": issue.message}
                            for issue in result.issues
                        ],
                    },
                )

        return JSONResponse(
            status_code=200,
            content={
                "outcome": "evaluated",
                "correlationId": correlation_id,
                "contractVersion": (
                    result.package.contractVersion
                    if result.package
                    else (result.contract_version or CONTRACT_VERSION)
                ),
                "rendererProfileId": result.package.rendererProfileId if result.package else PROFILE_ID,
                "structurallyValid": result.valid,
                "issues": [
                    {"path": issue.path, "code": issue.code, "message": issue.message}
                    for issue in result.issues
                ],
            },
        )
    except ClientDisconnect:
        return _package_error(400, "client_disconnected", "The request body was not received completely.", correlation_id=correlation_id)
    except Exception as error:
        error_id = str(uuid4())
        logger.error("Production package preflight failed (%s; errorId=%s).", type(error).__name__, error_id)
        return JSONResponse(
            status_code=500,
            content={
                "outcome": "internal-error",
                "correlationId": correlation_id,
                "structurallyValid": None,
                "errorId": error_id,
                "detail": "Production package validation could not be completed.",
            },
        )
def _loopback_host(value: str) -> str:
    if value.lower() == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("host must be localhost or a loopback IP address") from exc
    if not address.is_loopback:
        raise argparse.ArgumentTypeError("host must be localhost or a loopback IP address")
    return value


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return port


def main(argv: list[str] | None = None) -> None:
    """Start the API only when explicitly invoked as a command."""
    parser = argparse.ArgumentParser(description="Run the local Spotloom Studio API.")
    parser.add_argument("--host", type=_loopback_host, default="127.0.0.1")
    parser.add_argument("--port", type=_port, default=8000)
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
