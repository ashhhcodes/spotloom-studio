from __future__ import annotations

import shutil

import pytest
from pydantic import ValidationError

from adforge_renderer.creative import (
    Creative,
    CreativeGeneration,
    GenerationStatus,
    SceneRole,
    UnsupportedFactReference,
    generate_creative,
    to_renderer_input,
    validate_creative,
)
from adforge_renderer.facts import (
    BusinessFact,
    BusinessFacts,
    FactField,
    FactProvenance,
    FactSource,
    ReviewState,
)
from adforge_renderer.models import BusinessInput


MANUAL = FactProvenance(source=FactSource.MANUAL)


def make_fact(fact_id: str, field: FactField, value: str, *,
              state: ReviewState = ReviewState.APPROVED,
              provenance: FactProvenance = MANUAL) -> BusinessFact:
    return BusinessFact(fact_id=fact_id, field=field, value=value,
                        provenance=provenance, review_state=state)


def make_facts(points: tuple[str, ...] = ("Roasted in small batches", "A good cup, made simple"),
               *, colors: tuple[str, ...] = ("#D98B45", "#F5EFE7"),
               include_product: bool = True, include_name: bool = True,
               include_cta: bool = True, state: ReviewState = ReviewState.APPROVED) -> BusinessFacts:
    facts: list[BusinessFact] = []
    if include_name:
        facts.append(make_fact("name", FactField.BUSINESS_NAME, "Northstar Coffee", state=state))
    if include_product:
        facts.append(make_fact("product", FactField.PRODUCT_OR_SERVICE,
                               "Small-batch coffee, thoughtfully roasted", state=state))
    facts.extend(make_fact(f"point-{index}", FactField.SELLING_POINT, point, state=state)
                 for index, point in enumerate(points, 1))
    facts.extend(make_fact(f"color-{index}", FactField.BRAND_COLOR, color, state=state)
                 for index, color in enumerate(colors, 1))
    if include_cta:
        facts.append(make_fact("cta", FactField.CTA, "Find your next cup", state=state))
    return BusinessFacts(business_id="Northstar Coffee", facts=tuple(facts))


def test_required_optional_missing_and_explicit_facts_are_distinct():
    facts = make_facts(points=(), colors=())
    assert facts.get("point-1") is None
    assert facts.values(FactField.PRICE) == ()
    explicit_price = BusinessFact(fact_id="price", field=FactField.PRICE, value="$0",
                                  provenance=MANUAL, review_state=ReviewState.UNREVIEWED)
    with_price = BusinessFacts(business_id=facts.business_id, facts=(*facts.facts, explicit_price))
    assert with_price.get("price").value == "$0"
    assert with_price.values(FactField.PRICE, approved_only=True) == ()
    explicit_negative = make_fact("no-offer", FactField.OFFER,
                                  "No promotion is currently provided")
    without_inference = BusinessFacts(business_id="explicit-negative",
                                      facts=(explicit_negative,))
    assert without_inference.get("no-offer").value == "No promotion is currently provided"
    assert without_inference.values(FactField.OFFER, approved_only=True)[0] == explicit_negative


def test_provenance_validation_for_website_and_model_suggestions():
    with pytest.raises(ValidationError, match="requires a source_url"):
        FactProvenance(source=FactSource.WEBSITE)
    website_source = FactProvenance(source=FactSource.WEBSITE, source_url="https://example.com/about")
    website_fact = make_fact("site-name", FactField.BUSINESS_NAME, "Example", provenance=website_source)
    assert str(website_fact.provenance.source_url).startswith("https://example.com")
    suggestion = make_fact("model-copy", FactField.OFFER, "A special deal",
                           provenance=FactProvenance(source=FactSource.MODEL_SUGGESTION),
                           state=ReviewState.UNREVIEWED)
    sheet = BusinessFacts(business_id="suggestion", facts=(suggestion,))
    assert sheet.values(FactField.OFFER, approved_only=True) == ()
    reviewed = sheet.approve("model-copy")
    assert reviewed.get("model-copy").provenance.source == FactSource.MODEL_SUGGESTION
    assert reviewed.get("model-copy").review_state == ReviewState.APPROVED


def test_approval_rejection_and_correction_require_explicit_approval():
    facts = make_facts(points=())
    unreviewed = BusinessFacts(business_id="Review", facts=(
        make_fact("name", FactField.BUSINESS_NAME, "Nortstar Coffee",
                  state=ReviewState.UNREVIEWED),
    ))
    approved = unreviewed.approve("name")
    assert approved.get("name").review_state == ReviewState.APPROVED
    rejected = approved.reject("name")
    assert rejected.get("name").review_state == ReviewState.REJECTED
    with pytest.raises(ValueError, match="rejected fact"):
        rejected.approve("name")
    corrected = rejected.correct("name", "Northstar Coffee")
    assert corrected.get("name").review_state == ReviewState.REJECTED
    assert corrected.get("name-v2").review_state == ReviewState.UNREVIEWED
    assert corrected.get("name-v2").supersedes_fact_id == "name"
    assert corrected.values(FactField.BUSINESS_NAME, approved_only=True) == ()
    reviewed = corrected.approve("name-v2")
    assert reviewed.values(FactField.BUSINESS_NAME, approved_only=True)[0].value == "Northstar Coffee"
    assert facts.get("price") is None


def test_duplicate_fact_ids_and_unbounded_renderer_fact_counts_are_rejected():
    repeated = make_fact("same", FactField.SELLING_POINT, "Point")
    with pytest.raises(ValidationError, match="unique"):
        BusinessFacts(business_id="bad", facts=(repeated, repeated))
    points = tuple(make_fact(f"point-{i}", FactField.SELLING_POINT, f"Point {i}")
                   for i in range(4))
    with pytest.raises(ValidationError, match="at most three"):
        BusinessFacts(business_id="bad", facts=points)


@pytest.mark.parametrize("points,expected_supporting", [
    ((), 0),
    (("One point",), 1),
    (("Point one", "Point two"), 2),
    (("Point one", "Point two", "Point three"), 3),
])
def test_generation_handles_zero_one_and_multiple_points(points, expected_supporting):
    facts = make_facts(points=points, colors=())
    result = generate_creative(facts)
    assert result.status == GenerationStatus.READY
    creative = result.creative
    assert sum(scene.role == SceneRole.SUPPORTING_POINT for scene in creative.scenes) == expected_supporting
    assert creative.hook == "Northstar Coffee"
    assert creative.cta_text == "Find your next cup"
    assert creative.brand_colors == ("#D98B45", "#F5EFE7")
    if points:
        generated_points = [scene.on_screen_text for scene in creative.scenes
                            if scene.role == SceneRole.SUPPORTING_POINT]
        assert generated_points == list(points)
    renderer_input = to_renderer_input(creative, facts)
    assert isinstance(renderer_input, BusinessInput)
    assert renderer_input.business_name == "Northstar Coffee"
    assert renderer_input.cta == "Find your next cup"
    assert renderer_input.selling_points == list(points)
    validate_creative(creative, facts)


def test_identical_normalized_inputs_generate_identical_creatives():
    facts = make_facts()
    assert generate_creative(facts) == generate_creative(facts)


def test_duplicate_selling_point_is_not_repeated_and_warning_is_returned():
    facts = make_facts(points=("Roasted in small batches", " roasted   in small batches "))
    result = generate_creative(facts)
    point_scenes = [scene for scene in result.creative.scenes
                    if scene.role == SceneRole.SUPPORTING_POINT]
    assert [scene.claim_fact_ids for scene in point_scenes] == [("point-1",)]
    assert any("Duplicate selling point" in warning for warning in result.warnings)


@pytest.mark.parametrize("missing", ["name", "product", "cta"])
def test_insufficient_approved_core_facts_requires_review(missing):
    facts = make_facts(include_name=missing != "name",
                       include_product=missing != "product",
                       include_cta=missing != "cta")
    result = generate_creative(facts)
    assert result.status == GenerationStatus.NEEDS_REVIEW
    assert result.creative is None
    assert result.review_reasons


def test_unreviewed_facts_do_not_generate_factual_copy():
    result = generate_creative(make_facts(state=ReviewState.UNREVIEWED))
    assert result.status == GenerationStatus.NEEDS_REVIEW
    assert result.creative is None


def test_nonexistent_rejected_and_unreviewed_fact_references_are_rejected():
    facts = make_facts()
    creative = generate_creative(facts).creative
    missing_reference = creative.model_copy(update={
        "scenes": (creative.scenes[0].model_copy(update={"claim_fact_ids": ("ghost",)}),
                   *creative.scenes[1:]),
    })
    with pytest.raises(UnsupportedFactReference, match="nonexistent"):
        validate_creative(missing_reference, facts)
    with pytest.raises(UnsupportedFactReference, match="not approved"):
        validate_creative(creative, facts.reject("point-1"))
    with pytest.raises(UnsupportedFactReference, match="not approved"):
        validate_creative(creative, make_facts(state=ReviewState.UNREVIEWED))


def test_scene_text_must_exactly_match_cited_approved_fact():
    facts = make_facts()
    creative = generate_creative(facts).creative
    supporting = next(i for i, scene in enumerate(creative.scenes)
                      if scene.role == SceneRole.SUPPORTING_POINT)
    changed = creative.scenes[supporting].model_copy(
        update={"on_screen_text": "The best coffee in town"})
    altered = creative.model_copy(update={
        "scenes": tuple(changed if i == supporting else scene
                         for i, scene in enumerate(creative.scenes))
    })
    with pytest.raises(UnsupportedFactReference, match="exactly match"):
        validate_creative(altered, facts)


def test_supporting_description_also_requires_exact_fact_support():
    facts = make_facts()
    creative = generate_creative(facts).creative
    index = next(i for i, scene in enumerate(creative.scenes)
                 if scene.role == SceneRole.SUPPORTING_POINT)
    changed = creative.scenes[index].model_copy(
        update={"supporting_description": "Guaranteed to be the best"})
    altered = creative.model_copy(update={
        "scenes": tuple(changed if i == index else scene
                         for i, scene in enumerate(creative.scenes))
    })
    with pytest.raises(UnsupportedFactReference, match="description must exactly match"):
        validate_creative(altered, facts)


def test_repeated_supporting_point_in_creative_is_rejected():
    facts = make_facts(points=("One point", "Another point"))
    creative = generate_creative(facts).creative
    indices = [i for i, scene in enumerate(creative.scenes)
               if scene.role == SceneRole.SUPPORTING_POINT]
    second = creative.scenes[indices[1]].model_copy(update={
        "on_screen_text": creative.scenes[indices[0]].on_screen_text,
        "claim_fact_ids": creative.scenes[indices[0]].claim_fact_ids,
    })
    repeated = creative.model_copy(update={
        "scenes": tuple(second if i == indices[1] else scene
                         for i, scene in enumerate(creative.scenes))
    })
    with pytest.raises(UnsupportedFactReference, match="repeats an exact"):
        validate_creative(repeated, facts)


def test_creative_schema_rejects_bad_scene_order_and_count():
    result = generate_creative(make_facts(points=()))
    data = result.creative.model_dump(mode="json")
    data["scenes"][1]["order"] = 4
    with pytest.raises(ValidationError, match="consecutive"):
        Creative.model_validate(data)
    with pytest.raises(ValidationError):
        CreativeGeneration(status=GenerationStatus.READY, creative=None)


def test_fact_creative_adapter_renders_with_existing_renderer(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for the creative-render integration test")
    from adforge_renderer.renderer import render_ad

    facts = make_facts(points=("One", "Two", "Three"))
    creative = generate_creative(facts).creative
    renderer_input = to_renderer_input(creative, facts)
    metadata = render_ad(renderer_input, tmp_path / "creative.mp4")
    assert metadata["container"] == "mp4"
    assert metadata["codec"] == "h264"
    assert metadata["width"] == 1080
    assert metadata["height"] == 1920


def test_zero_point_creative_renders_with_existing_renderer(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for the creative-render integration test")
    from adforge_renderer.renderer import render_ad

    facts = make_facts(points=())
    creative = generate_creative(facts).creative
    metadata = render_ad(to_renderer_input(creative, facts), tmp_path / "no-points.mp4")
    assert metadata["codec"] == "h264"
    assert metadata["width"] == 1080
    assert metadata["height"] == 1920
