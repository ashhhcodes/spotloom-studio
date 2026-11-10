"""Minimal local HTTP application for Spotloom Studio."""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import ipaddress
import logging
import tempfile
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from email.message import Message
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response
from starlette.requests import ClientDisconnect
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy.orm import Session

from adforge_renderer.integration_schemas import (
    BusinessClaims,
    CreativeBrief,
    PreproductionValidationRequest,
    StoryboardInput,
    validate_contract_input,
)
from adforge_renderer.identity import VerifiedClerkPrincipal, require_verified_principal
from adforge_renderer.database import (
    DatabaseConfigurationError,
    DatabaseOperationError,
    LazyDatabaseRuntime,
    get_session_dependency,
)
from adforge_renderer.database.models import normalize_project_name
from adforge_renderer.project_service import (
    IdentityMappingError,
    create_owned_project,
    find_internal_user_id,
    get_or_create_internal_user_id,
    get_owned_project,
    list_owned_projects,
)
from adforge_renderer.preproduction_validation import (
    PreproductionValidationResponse,
    evaluate_preproduction,
)
from adforge_renderer.creative import DEFAULT_BRAND_COLORS
from adforge_renderer.models import (
    MAX_STORYBOARD_RENDER_SECONDS,
    BusinessInput,
    StoryboardRenderScene,
    storyboard_render_duration,
)
from adforge_renderer.renderer import render_ad
from adforge_renderer.validation import RendererError
from adforge_renderer.production_package import (
    CONTRACT_VERSION,
    MAX_PACKAGE_BYTES,
    PROFILE_ID,
    validate_production_package_json,
)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Dispose only resources that were lazily initialized by API requests."""
    try:
        yield
    finally:
        try:
            application.state.database_runtime.dispose()
        except DatabaseOperationError:
            logger.error("Database engine disposal failed.")


app = FastAPI(
    title="Spotloom Studio API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_lifespan,
)
app.state.database_runtime = LazyDatabaseRuntime()


def get_project_session(
    request: Request,
    _principal: Annotated[
        VerifiedClerkPrincipal, Depends(require_verified_principal)
    ],
) -> Iterator[Session]:
    """Open a transaction only for an authenticated project API request."""
    try:
        factory = request.app.state.database_runtime.session_factory()
        yield from get_session_dependency(factory)()
    except DatabaseConfigurationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project persistence is not configured.",
        ) from None
    except DatabaseOperationError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project persistence is unavailable.",
        ) from None


class DemoRenderRequest(BaseModel):
    """Bounded, caller-supplied text used only by the local illustrative renderer."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, str_strip_whitespace=True)

    business_name: StrictStr = Field(min_length=1, max_length=70)
    product_or_service: StrictStr = Field(min_length=1, max_length=110)
    selling_points: list[Annotated[StrictStr, Field(min_length=1, max_length=90)]] = Field(default_factory=list, max_length=3)
    cta: StrictStr = Field(min_length=1, max_length=50)
    primary_color: StrictStr = Field(default=DEFAULT_BRAND_COLORS[0], pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: StrictStr = Field(default=DEFAULT_BRAND_COLORS[1], pattern=r"^#[0-9A-Fa-f]{6}$")
    scenes: tuple[StoryboardRenderScene, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def scene_ids_are_unique(self):
        ids = [scene.scene_id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene IDs must be unique")
        if self.scenes[0].transition != "cut":
            raise ValueError("the first scene must start without an incoming transition")
        if storyboard_render_duration(self.scenes) > MAX_STORYBOARD_RENDER_SECONDS:
            raise ValueError("storyboard render duration exceeds the local demo limit")
        return self


class ProjectCreateRequest(BaseModel):
    """Strict project-create body; ownership and identity are never client input."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    name: StrictStr

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        try:
            return normalize_project_name(value)
        except ValueError:
            raise ValueError(
                "Project name must be nonblank and no longer than 120 characters."
            ) from None


class ProjectResponse(BaseModel):
    """Safe project representation without identity or ownership authority."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, _error: RequestValidationError,
) -> JSONResponse:
    """Return a stable 422 without reflecting submitted values or internal details."""
    if request.url.path == "/projects" or request.url.path.startswith("/projects/"):
        return JSONResponse(
            status_code=422,
            content={
                "error": "invalid_project_request",
                "detail": "Provide a nonblank project name within the current limit and no unsupported fields.",
            },
        )
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


@app.get("/auth/identity", include_in_schema=False)
def verify_clerk_identity(
    principal: Annotated[VerifiedClerkPrincipal, Depends(require_verified_principal)],
) -> dict[str, object]:
    """Demonstrate verified external identity; this does not authorize a project."""
    return {
        "authenticated": True,
        "principal": {"issuer": principal.issuer, "subject": principal.subject},
    }


def _mapping_user_id(
    session: Session,
    principal: VerifiedClerkPrincipal,
    *,
    create_if_missing: bool,
):
    try:
        if create_if_missing:
            return get_or_create_internal_user_id(session, principal)
        return find_internal_user_id(session, principal)
    except IdentityMappingError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verified identity could not be resolved.",
        ) from None


def _project_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Project not found.",
    )


@app.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreateRequest,
    principal: Annotated[VerifiedClerkPrincipal, Depends(require_verified_principal)],
    session: Annotated[Session, Depends(get_project_session)],
) -> ProjectResponse:
    """Create a project owned by the internal user mapped from verified Clerk."""
    user_id = _mapping_user_id(session, principal, create_if_missing=True)
    project = create_owned_project(session, user_id, payload.name)
    return ProjectResponse.model_validate(project)


@app.get("/projects", response_model=list[ProjectResponse])
def get_projects(
    principal: Annotated[VerifiedClerkPrincipal, Depends(require_verified_principal)],
    session: Annotated[Session, Depends(get_project_session)],
) -> list[ProjectResponse]:
    """List only projects owned by the internal user for this verified principal."""
    user_id = _mapping_user_id(session, principal, create_if_missing=True)
    projects = list_owned_projects(session, user_id)
    return [ProjectResponse.model_validate(project) for project in projects]


@app.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    principal: Annotated[VerifiedClerkPrincipal, Depends(require_verified_principal)],
    session: Annotated[Session, Depends(get_project_session)],
) -> ProjectResponse:
    """Return an owned project; unknown and non-owned IDs are indistinguishable."""
    user_id = _mapping_user_id(session, principal, create_if_missing=False)
    if user_id is None:
        raise _project_not_found()
    project = get_owned_project(session, project_id, user_id)
    if project is None:
        raise _project_not_found()
    return ProjectResponse.model_validate(project)


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


@app.post("/render/demo", include_in_schema=False)
async def render_demo_video(request: Request) -> Response:
    """Render an illustrative MP4 from bounded text and stream it without persistence."""
    if not _package_content_type_is_supported(request):
        return JSONResponse(status_code=415, content={
            "error": "unsupported_media_type",
            "detail": "Content-Type must be application/json with UTF-8 encoding.",
        })

    declared_length, length_error = _package_content_length(request)
    if length_error == "invalid_content_length":
        return JSONResponse(status_code=400, content={
            "error": length_error,
            "detail": "Content-Length is malformed or conflicting.",
        })
    if length_error == "payload_too_large":
        return JSONResponse(status_code=413, content={
            "error": length_error,
            "detail": "The render request exceeds the 65536-byte limit.",
        })

    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_PACKAGE_BYTES:
                return JSONResponse(status_code=413, content={
                    "error": "payload_too_large",
                    "detail": "The render request exceeds the 65536-byte limit.",
                })
            body.extend(chunk)
    except ClientDisconnect:
        return JSONResponse(status_code=400, content={
            "error": "client_disconnected",
            "detail": "The render request body was not received completely.",
        })
    if declared_length is not None and len(body) != declared_length:
        return JSONResponse(status_code=400, content={
            "error": "content_length_mismatch",
            "detail": "Content-Length does not match the received body.",
        })

    try:
        render_request = DemoRenderRequest.model_validate_json(bytes(body))
        renderer_input = BusinessInput(
            business_name=render_request.business_name,
            product_or_service=render_request.product_or_service,
            selling_points=render_request.selling_points,
            brand_colors=list(dict.fromkeys((render_request.primary_color, render_request.accent_color))),
            cta=render_request.cta,
        )
    except ValidationError:
        return JSONResponse(status_code=422, content={
            "error": "invalid_render_input",
            "detail": "Use 1–6 unique scenes, supported roles, #RRGGBB brand colors, durations of 1–60 seconds, supported transitions, a cut on the first scene, and a rendered timeline no longer than 30 seconds.",
        })

    temporary = tempfile.TemporaryDirectory(prefix="spotloom-demo-render-")
    output_path = Path(temporary.name) / "preview.mp4"
    try:
        await run_in_threadpool(
            render_ad, renderer_input, output_path, storyboard_scenes=render_request.scenes,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RendererError("Renderer did not produce a video file.")
    except Exception as error:
        temporary.cleanup()
        error_id = str(uuid4())
        logger.error("Demo render failed (%s; errorId=%s).", type(error).__name__, error_id)
        return JSONResponse(status_code=500, content={
            "error": "demo_render_failed",
            "errorId": error_id,
            "detail": "The local demo video could not be generated. Check that FFmpeg and FFprobe are available.",
        })

    return FileResponse(
        output_path,
        media_type="video/mp4",
        filename="spotloom-illustrative-draft.mp4",
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(temporary.cleanup),
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
