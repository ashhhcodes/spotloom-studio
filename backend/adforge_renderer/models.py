"""Validated user-provided business details for a local ad render."""

from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


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
