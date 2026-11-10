"""Strict request and response contracts for project-scoped creative planning."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


CampaignObjective = Literal["awareness", "engagement", "traffic", "conversions"]
CampaignPlatform = Literal["instagram", "tiktok", "youtube", "other"]
VideoFormat = Literal["9:16", "1:1", "16:9"]
StoryboardStatus = Literal["draft", "ready_for_review"]
CampaignText = Annotated[StrictStr, Field(max_length=500)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CampaignBrief(_StrictModel):
    """Draft campaign details; blank fields are valid and remain incomplete."""

    campaign_name: Annotated[StrictStr, Field(max_length=120)] = ""
    brand_name: Annotated[StrictStr, Field(max_length=120)] = ""
    website_url: Annotated[StrictStr, Field(max_length=2048)] = ""
    product_or_service: Annotated[StrictStr, Field(max_length=1000)] = ""
    target_audience: CampaignText = ""
    objective: CampaignObjective | None = None
    platform: CampaignPlatform | None = None
    key_selling_points: list[CampaignText] = Field(default_factory=list, max_length=32)
    call_to_action: CampaignText = ""

    @field_validator("website_url")
    @classmethod
    def validate_website_url(cls, value: str) -> str:
        if not value:
            return value
        if value != value.strip() or any(ord(char) < 0x20 or char.isspace() for char in value):
            raise ValueError("website_url must be a valid HTTP or HTTPS URL.")
        try:
            parsed = urlsplit(value)
            _ = parsed.port
        except ValueError:
            raise ValueError("website_url must be a valid HTTP or HTTPS URL.") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("website_url must be a valid HTTP or HTTPS URL.")
        return value


class CreativeDirection(_StrictModel):
    """User-authored direction; choosing it does not generate media."""

    visual_style: CampaignText = ""
    advertising_tone: CampaignText = ""
    primary_message: CampaignText = ""
    supporting_message: CampaignText = ""
    audience_emphasis: CampaignText = ""
    brand_personality: CampaignText = ""
    desired_video_format: VideoFormat | None = None
    preferred_duration_seconds: Literal[15, 30, 60] | None = None


class StoryboardScene(_StrictModel):
    id: Annotated[StrictStr, Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")]
    title: Annotated[StrictStr, Field(min_length=1, max_length=120)]
    description: Annotated[StrictStr, Field(max_length=500)] = ""
    visual_direction: Annotated[StrictStr, Field(max_length=1000)] = ""
    on_screen_text: CampaignText = ""
    narration: Annotated[StrictStr, Field(max_length=1000)] = ""
    duration_seconds: StrictInt = Field(default=5, ge=1, le=60)
    status: StoryboardStatus = "draft"

    @field_validator("title")
    @classmethod
    def require_nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Scene title must contain non-whitespace characters.")
        return value


class ProjectCreativeWorkspaceUpdate(_StrictModel):
    revision: StrictInt = Field(ge=0)
    brief: CampaignBrief
    creative_direction: CreativeDirection
    storyboard: list[StoryboardScene] = Field(max_length=32)

    @field_validator("storyboard")
    @classmethod
    def require_unique_scene_ids(cls, scenes: list[StoryboardScene]) -> list[StoryboardScene]:
        scene_ids = [scene.id for scene in scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("Storyboard scene IDs must be unique.")
        return scenes


class ProjectCreativeWorkspaceResponse(_StrictModel):
    project_id: UUID
    revision: StrictInt
    brief: CampaignBrief
    creative_direction: CreativeDirection
    storyboard: list[StoryboardScene]
    created_at: datetime | None
    updated_at: datetime | None


def empty_workspace_response(project_id: UUID) -> ProjectCreativeWorkspaceResponse:
    """Return an honest unsaved workspace without creating database state."""
    return ProjectCreativeWorkspaceResponse(
        project_id=project_id,
        revision=0,
        brief=CampaignBrief(),
        creative_direction=CreativeDirection(),
        storyboard=[],
        created_at=None,
        updated_at=None,
    )
