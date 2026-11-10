"""Validated user-provided business details for a local ad render."""

from __future__ import annotations

import re
from typing import Literal, Sequence
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
STORYBOARD_FADE_SECONDS = 0.35
MAX_STORYBOARD_RENDER_SECONDS = 30


class BusinessInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    business_name: str = Field(min_length=1, max_length=70)
    product_or_service: str = Field(min_length=1, max_length=110)
    selling_points: list[str] = Field(default_factory=list, max_length=3)
    brand_colors: list[str] = Field(min_length=1, max_length=2)
    cta: str = Field(min_length=1, max_length=50)

    @field_validator("selling_points")
    @classmethod
    def validate_selling_points(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 90 for value in cleaned):
            raise ValueError("selling points must contain 1–90 non-blank characters")
        return cleaned

    @field_validator("brand_colors")
    @classmethod
    def validate_brand_colors(cls, values: list[str]) -> list[str]:
        normalized = [value.upper() for value in values]
        if any(not _HEX_COLOR.fullmatch(value) for value in normalized):
            raise ValueError("brand colors must use #RRGGBB hex notation")
        if len(set(normalized)) != len(normalized):
            raise ValueError("brand colors must be unique")
        return normalized


class StoryboardRenderScene(BaseModel):
    """Bounded text fields used to draw one illustrative storyboard scene."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    scene_id: StrictStr = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
    title: StrictStr = Field(min_length=1, max_length=80)
    on_screen_text: StrictStr = Field(min_length=1, max_length=180)
    duration_seconds: StrictInt = Field(ge=1, le=60)
    transition: Literal["cut", "fade"]
    role: Literal["hook", "benefit", "proof", "cta"] | None = None

    @field_validator("title", "on_screen_text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scene text must not be blank")
        return value

    @field_validator("role", mode="before")
    @classmethod
    def reject_explicit_null_role(cls, value):
        if value is None:
            raise ValueError("scene role must be hook, benefit, proof, or cta")
        return value


def storyboard_render_duration(scenes: Sequence[StoryboardRenderScene]) -> float:
    """Return the timeline length after supported crossfade overlaps."""
    duration = float(sum(scene.duration_seconds for scene in scenes))
    return duration - sum(
        STORYBOARD_FADE_SECONDS for scene in scenes[1:] if scene.transition == "fade"
    )
