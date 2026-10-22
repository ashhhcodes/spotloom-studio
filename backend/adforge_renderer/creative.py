"""Deterministic, fact-grounded creative generation and renderer adapter."""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
import hashlib
import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .facts import BusinessFacts, FactField, ReviewState
from .models import BusinessInput

DEFAULT_BRAND_COLORS = ("#D98B45", "#F5EFE7")
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class SceneRole(StrEnum):
    HOOK = "hook"
    VALUE_PROPOSITION = "value_proposition"
    SUPPORTING_POINT = "supporting_point"
    CTA = "cta"


class GenerationStatus(StrEnum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"


class CreativeScene(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    scene_id: str = Field(pattern=r"^scene-[a-z0-9_-]{1,60}$")
    order: int = Field(ge=1, le=6)
    role: SceneRole
    on_screen_text: str = Field(min_length=1, max_length=180)
    supporting_description: str | None = Field(default=None, max_length=240)
    claim_fact_ids: tuple[str, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def no_duplicate_references(self) -> Self:
        if len(self.claim_fact_ids) != len(set(self.claim_fact_ids)):
            raise ValueError("claim_fact_ids must be unique within a scene")
        return self


class Creative(BaseModel):
    """Renderer-compatible creative; timing is owned by the renderer."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    creative_id: str = Field(pattern=r"^creative-[a-z0-9_-]{1,50}$")
    title: str = Field(min_length=1, max_length=100)
    hook: str = Field(min_length=1, max_length=70)
    scenes: tuple[CreativeScene, ...] = Field(min_length=3, max_length=6)
    brand_colors: tuple[str, ...] = Field(min_length=1, max_length=2)
    brand_color_fact_ids: tuple[str, ...] = Field(default=(), max_length=2)
    cta_text: str = Field(min_length=1, max_length=50)
    cta_fact_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")

    @field_validator("brand_colors")
    @classmethod
    def normalize_colors(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.upper() for value in values)
        if any(not _HEX_COLOR.fullmatch(value) for value in normalized):
            raise ValueError("brand colors must use #RRGGBB hex notation")
        if len(set(normalized)) != len(normalized):
            raise ValueError("brand colors must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_scene_sequence(self) -> Self:
        roles = [scene.role for scene in self.scenes]
        if [scene.order for scene in self.scenes] != list(range(1, len(self.scenes) + 1)):
            raise ValueError("scene order must be consecutive starting at 1")
        if roles[0] != SceneRole.HOOK or roles[1] != SceneRole.VALUE_PROPOSITION:
            raise ValueError("creative must start with hook then value_proposition")
        if roles[-1] != SceneRole.CTA or any(role != SceneRole.SUPPORTING_POINT
                                              for role in roles[2:-1]):
            raise ValueError("creative must end with CTA and place supporting points between")
        if len({scene.scene_id for scene in self.scenes}) != len(self.scenes):
            raise ValueError("scene_id values must be unique")
        if self.scenes[0].on_screen_text != self.hook:
            raise ValueError("hook must match the first scene's on-screen text")
        if len(self.brand_color_fact_ids) not in (0, len(self.brand_colors)):
            raise ValueError("provide a fact reference for every supplied brand color")
        return self


class CreativeGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: GenerationStatus
    creative: Creative | None = None
    review_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def status_matches_result(self) -> Self:
        if self.status == GenerationStatus.READY and (self.creative is None or self.review_reasons):
            raise ValueError("ready generation needs a creative and no review reasons")
        if self.status == GenerationStatus.NEEDS_REVIEW and (self.creative is not None or not self.review_reasons):
            raise ValueError("needs_review generation needs reasons and no creative")
        return self


class UnsupportedFactReference(ValueError):
    """A creative references absent, rejected, unreviewed or field-incompatible facts."""


def _require_fact(facts: BusinessFacts, fact_id: str, expected: FactField) -> str:
    fact = facts.get(fact_id)
    if fact is None:
        raise UnsupportedFactReference(f"creative references nonexistent fact_id {fact_id!r}")
    if fact.review_state != ReviewState.APPROVED:
        raise UnsupportedFactReference(f"fact_id {fact_id!r} is not approved")
    if fact.field != expected:
        raise UnsupportedFactReference(
            f"fact_id {fact_id!r} has field {fact.field.value!r}; expected {expected.value!r}"
        )
    return fact.value


def validate_creative(creative: Creative, facts: BusinessFacts) -> None:
    """Validate references and exact-copy claim grounding (not semantic truth)."""
    business_name_id = creative.scenes[0].claim_fact_ids
    if len(business_name_id) != 1 or _require_fact(
            facts, business_name_id[0], FactField.BUSINESS_NAME) != creative.hook:
        raise UnsupportedFactReference("hook must exactly match one approved business_name fact")
    for scene in creative.scenes[1:-1]:
        valid_fields = ({FactField.PRODUCT_OR_SERVICE, FactField.SELLING_POINT}
                        if scene.role == SceneRole.VALUE_PROPOSITION
                        else {FactField.SELLING_POINT})
        matched = False
        for fact_id in scene.claim_fact_ids:
            fact = facts.get(fact_id)
            if fact is None:
                raise UnsupportedFactReference(f"creative references nonexistent fact_id {fact_id!r}")
            if fact.review_state != ReviewState.APPROVED:
                raise UnsupportedFactReference(f"fact_id {fact_id!r} is not approved")
            if fact.field not in valid_fields or fact.value != scene.on_screen_text:
                raise UnsupportedFactReference(
                    f"scene {scene.scene_id!r} text must exactly match an approved supporting fact"
                )
            matched = True
        if not matched:
            raise UnsupportedFactReference(f"scene {scene.scene_id!r} has no approved claim support")
        if scene.supporting_description is not None:
            description_supported = any(
                facts.get(fact_id) is not None
                and facts.get(fact_id).review_state == ReviewState.APPROVED
                and facts.get(fact_id).value == scene.supporting_description
                for fact_id in scene.claim_fact_ids
            )
            if not description_supported:
                raise UnsupportedFactReference(
                    f"scene {scene.scene_id!r} description must exactly match a cited approved fact"
                )
    cta_scene = creative.scenes[-1]
    cta_text = _require_fact(facts, creative.cta_fact_id, FactField.CTA)
    if cta_scene.on_screen_text != creative.cta_text or creative.cta_text != cta_text:
        raise UnsupportedFactReference("CTA text must exactly match its approved CTA fact")
    if cta_scene.claim_fact_ids != (creative.cta_fact_id,):
        raise UnsupportedFactReference("CTA scene must cite exactly its CTA fact")
    if creative.brand_color_fact_ids:
        for color, fact_id in zip(creative.brand_colors, creative.brand_color_fact_ids, strict=True):
            if _require_fact(facts, fact_id, FactField.BRAND_COLOR).upper() != color:
                raise UnsupportedFactReference("creative brand colors must match approved color facts")
    supporting_texts = [scene.on_screen_text.casefold() for scene in creative.scenes
                        if scene.role == SceneRole.SUPPORTING_POINT]
    repeated = [text for text, count in Counter(supporting_texts).items() if count > 1]
    if repeated:
        raise UnsupportedFactReference("creative repeats an exact supporting point")


def generate_creative(facts: BusinessFacts) -> CreativeGeneration:
    """Generate a stable literal-copy sequence; never paraphrase factual claims."""
    approved = {field: facts.values(field, approved_only=True) for field in FactField}
    reasons: list[str] = []
    for required in (FactField.BUSINESS_NAME, FactField.PRODUCT_OR_SERVICE, FactField.CTA):
        values = approved[required]
        distinct = {fact.value for fact in values}
        if not distinct:
            reasons.append(f"Add and approve {required.value} before generating a creative.")
        elif len(distinct) > 1:
            reasons.append(f"Resolve conflicting approved {required.value} facts before generating.")
    if reasons:
        return CreativeGeneration(status=GenerationStatus.NEEDS_REVIEW,
                                   review_reasons=tuple(reasons))

    business = approved[FactField.BUSINESS_NAME][0]
    product = approved[FactField.PRODUCT_OR_SERVICE][0]
    cta = approved[FactField.CTA][0]
    unique_points: list = []
    seen_points: set[str] = set()
    warnings: list[str] = []
    for point in approved[FactField.SELLING_POINT]:
        normalized = " ".join(point.value.split()).casefold()
        if normalized in seen_points:
            warnings.append(f"Duplicate selling point {point.fact_id!r} omitted from creative.")
            continue
        seen_points.add(normalized)
        unique_points.append(point)

    color_facts = approved[FactField.BRAND_COLOR][:2]
    if color_facts:
        colors = tuple(fact.value.upper() for fact in color_facts)
        color_ids = tuple(fact.fact_id for fact in color_facts)
    else:
        colors = DEFAULT_BRAND_COLORS
        color_ids = ()
        warnings.append("No approved brand colors; renderer defaults are used as styling only.")

    scenes = [CreativeScene(scene_id="scene-hook", order=1, role=SceneRole.HOOK,
                            on_screen_text=business.value,
                            claim_fact_ids=(business.fact_id,)),
              CreativeScene(scene_id="scene-value", order=2,
                            role=SceneRole.VALUE_PROPOSITION,
                            on_screen_text=product.value,
                            claim_fact_ids=(product.fact_id,))]
    for index, point in enumerate(unique_points, start=1):
        scenes.append(CreativeScene(
            scene_id=f"scene-point-{point.fact_id}", order=len(scenes) + 1,
            role=SceneRole.SUPPORTING_POINT, on_screen_text=point.value,
            claim_fact_ids=(point.fact_id,),
        ))
    scenes.append(CreativeScene(scene_id="scene-cta", order=len(scenes) + 1,
                                role=SceneRole.CTA, on_screen_text=cta.value,
                                claim_fact_ids=(cta.fact_id,)))
    slug = re.sub(r"[^a-z0-9_-]+", "-", facts.business_id.lower()).strip("-") or "business"
    suffix = hashlib.sha256(facts.business_id.encode("utf-8")).hexdigest()[:8]
    creative = Creative(
        creative_id=f"creative-{slug[:30]}-{suffix}",
        title=f"{business.value} | Ad", hook=business.value, scenes=tuple(scenes),
        brand_colors=colors, brand_color_fact_ids=color_ids,
        cta_text=cta.value, cta_fact_id=cta.fact_id,
    )
    validate_creative(creative, facts)
    return CreativeGeneration(status=GenerationStatus.READY, creative=creative,
                               warnings=tuple(warnings))


def to_renderer_input(creative: Creative, facts: BusinessFacts) -> BusinessInput:
    """Adapt the approved creative into the existing renderer input model."""
    validate_creative(creative, facts)
    name = _require_fact(facts, creative.scenes[0].claim_fact_ids[0], FactField.BUSINESS_NAME)
    product_scene = next(scene for scene in creative.scenes
                         if scene.role == SceneRole.VALUE_PROPOSITION)
    product = product_scene.on_screen_text
    points = [scene.on_screen_text for scene in creative.scenes
              if scene.role == SceneRole.SUPPORTING_POINT]
    return BusinessInput(
        business_name=name,
        product_or_service=product,
        selling_points=points,
        brand_colors=list(creative.brand_colors),
        cta=creative.cta_text,
    )
