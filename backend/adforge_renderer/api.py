"""Minimal local HTTP application for Spotloom Studio."""

from __future__ import annotations

import argparse
import ipaddress
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
            BusinessClaims.model_validate(payload.facts),
            CreativeBrief.model_validate(payload.brief),
            StoryboardInput.model_validate(payload.storyboard),
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
