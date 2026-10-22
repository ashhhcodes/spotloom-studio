"""Small provenance-aware business fact model with explicit human review states."""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


class FactField(StrEnum):
    BUSINESS_NAME = "business_name"
    PRODUCT_OR_SERVICE = "product_or_service"
    SELLING_POINT = "selling_point"
    BRAND_COLOR = "brand_color"
    CTA = "cta"
    ADDRESS = "address"
    CONTACT_INFORMATION = "contact_information"
    OFFER = "offer"
    PRICE = "price"
    WEBSITE = "website"


class FactSource(StrEnum):
    MANUAL = "manual"
    WEBSITE = "website"
    MODEL_SUGGESTION = "model_suggestion"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FACT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class FactProvenance(BaseModel):
    """Where a value came from, with optional bounded extraction evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: FactSource
    source_url: AnyHttpUrl | None = None
    note: str | None = Field(default=None, max_length=240)
    extraction_method: str | None = Field(default=None, max_length=80)
    evidence: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def require_website_source_url(self) -> Self:
        if self.source == FactSource.WEBSITE and self.source_url is None:
            raise ValueError("website provenance requires a source_url")
        if self.source != FactSource.WEBSITE and self.source_url is not None:
            raise ValueError("source_url is only valid for website provenance")
        return self


class BusinessFact(BaseModel):
    """A supplied claim and its review status. Rejected is not a negative claim."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    fact_id: str = Field(pattern=_FACT_ID.pattern)
    field: FactField
    value: str = Field(min_length=1, max_length=240)
    provenance: FactProvenance
    review_state: ReviewState = ReviewState.UNREVIEWED
    supersedes_fact_id: str | None = Field(default=None, pattern=_FACT_ID.pattern)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("fact value cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_field_value(self) -> Self:
        if self.field == FactField.BRAND_COLOR and not _HEX_COLOR.fullmatch(self.value):
            raise ValueError("brand_color facts must use #RRGGBB hex notation")
        return self


class BusinessFacts(BaseModel):
    """A versionless in-memory/manual fact sheet; absent facts stay absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    business_id: str = Field(min_length=1, max_length=64)
    facts: tuple[BusinessFact, ...] = Field(max_length=32)

    @model_validator(mode="after")
    def validate_ids_and_supersedes(self) -> Self:
        ids = [fact.fact_id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact_id values must be unique")
        if sum(f.field == FactField.SELLING_POINT for f in self.facts) > 3:
            raise ValueError("at most three selling_point facts are supported by the renderer")
        if sum(f.field == FactField.BRAND_COLOR for f in self.facts) > 2:
            raise ValueError("at most two brand_color facts are supported")
        by_id = {fact.fact_id: fact for fact in self.facts}
        for fact in self.facts:
            if fact.supersedes_fact_id:
                previous = by_id.get(fact.supersedes_fact_id)
                if previous is None:
                    raise ValueError("supersedes_fact_id must reference an existing fact")
                if previous.field != fact.field:
                    raise ValueError("a correction must preserve the original fact field")
        return self

    def get(self, fact_id: str) -> BusinessFact | None:
        return next((fact for fact in self.facts if fact.fact_id == fact_id), None)

    def values(self, field: FactField, *, approved_only: bool = False) -> tuple[BusinessFact, ...]:
        return tuple(fact for fact in self.facts
                     if fact.field == field
                     and (not approved_only or fact.review_state == ReviewState.APPROVED))

    def _replace_fact(self, replacement: BusinessFact) -> BusinessFacts:
        if self.get(replacement.fact_id) is None:
            raise ValueError(f"unknown fact_id: {replacement.fact_id}")
        return BusinessFacts.model_validate({
            "business_id": self.business_id,
            "facts": tuple(replacement if f.fact_id == replacement.fact_id else f
                           for f in self.facts),
        })

    def approve(self, fact_id: str) -> BusinessFacts:
        fact = self.get(fact_id)
        if fact is None:
            raise ValueError(f"unknown fact_id: {fact_id}")
        if fact.review_state == ReviewState.REJECTED:
            raise ValueError("a rejected fact must be corrected as a new unreviewed fact")
        return self._replace_fact(fact.model_copy(update={"review_state": ReviewState.APPROVED}))

    def reject(self, fact_id: str) -> BusinessFacts:
        fact = self.get(fact_id)
        if fact is None:
            raise ValueError(f"unknown fact_id: {fact_id}")
        return self._replace_fact(fact.model_copy(update={"review_state": ReviewState.REJECTED}))

    def correct(self, fact_id: str, new_value: str, *,
                provenance: FactProvenance | None = None) -> BusinessFacts:
        """Reject the old value and add a linked, unreviewed manual correction."""
        old = self.get(fact_id)
        if old is None:
            raise ValueError(f"unknown fact_id: {fact_id}")
        if any(fact.supersedes_fact_id == fact_id for fact in self.facts):
            raise ValueError("correct the latest fact revision, not a superseded fact")
        revision = 2
        new_id = f"{fact_id}-v{revision}"
        known_ids = {fact.fact_id for fact in self.facts}
        while new_id in known_ids:
            revision += 1
            new_id = f"{fact_id}-v{revision}"
        rejected = old.model_copy(update={"review_state": ReviewState.REJECTED})
        correction = BusinessFact(
            fact_id=new_id,
            field=old.field,
            value=new_value,
            provenance=provenance or FactProvenance(source=FactSource.MANUAL,
                                                   note=f"Correction of {fact_id}"),
            review_state=ReviewState.UNREVIEWED,
            supersedes_fact_id=fact_id,
        )
        facts = tuple(rejected if fact.fact_id == fact_id else fact for fact in self.facts)
        return BusinessFacts(business_id=self.business_id, facts=(*facts, correction))
