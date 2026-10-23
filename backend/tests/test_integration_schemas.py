from __future__ import annotations

import builtins
from pathlib import Path
import socket
import subprocess

import pytest
from pydantic import ValidationError

from adforge_renderer.integration_schemas import (
    BusinessClaim,
    BusinessClaims,
    CreativeBrief,
    StoryboardInput,
    StoryboardScene,
    calculate_storyboard_runtime,
    validate_contract_input,
)


def source(**overrides):
    value = {
        "kind": "illustrative-placeholder",
        "reference": "Demo source — no website scanned",
        "pageOrSection": "Placeholder — no page inspected",
        "excerpt": None,
    }
    return {**value, **overrides}


def claim(**overrides):
    value = {
        "id": "product",
        "category": "Product",
        "claim": "Small-batch roasted coffee",
        "originalClaim": "Small-batch roasted coffee",
        "revisions": [],
        "status": "unreviewed",
        "source": source(),
    }
    return {**value, **overrides}


def brief(**overrides):
    value = {
        "objective": "awareness",
        "targetAudience": "People looking for a considered everyday cup",
        "productOrOffer": "Small-batch roasted coffee",
        "keyMessage": "A good cup, made simple.",
        "valueProposition": "",
        "platform": "instagram",
        "aspectRatio": "9:16",
        "duration": 15,
        "tone": "Warm, considered, and clear",
        "callToAction": "Learn more",
        "reliedUponFactIds": ["product"],
        "requirementsConfirmed": False,
    }
    return {**value, **overrides}


def scene(**overrides):
    value = {
        "id": "scene-one",
        "title": "Open",
        "narrativePurpose": "Set the tone",
        "visualDirection": "A quiet tabletop, as an illustrative suggestion.",
        "onScreenText": "A moment to pause",
        "narration": "Take a moment.",
        "durationSeconds": 4,
        "transitionNote": "Fade in",
    }
    return {**value, **overrides}


@pytest.mark.parametrize("status", ["unreviewed", "approved", "rejected"])
def test_claim_accepts_each_review_state_without_claiming_truth(status):
    parsed = BusinessClaim.model_validate(claim(status=status))

    assert parsed.status == status
    assert parsed.source.kind == "illustrative-placeholder"


def test_claim_requires_provenance_and_well_formed_source_metadata():
    missing_source = claim()
    del missing_source["source"]
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(missing_source)

    missing_source_detail = claim(source={"kind": "website", "reference": "https://example.test"})
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(missing_source_detail)

    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(source=source(kind="website", reference="https://user:secret@example.test")))

    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(source=source(kind="website", reference="javascript:alert(1)")))


def test_claim_rejects_invalid_status_and_extra_fields():
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(status="verified"))
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(isVerified=True))


def test_claim_rejects_blank_text_and_non_string_coercion():
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(claim="  "))
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(claim=123))
    with pytest.raises(ValidationError):
        BusinessClaims.model_validate({"facts": [claim(), claim(id="product")]})
    assert BusinessClaim.model_validate(claim(claim=" padded wording ")).claim == " padded wording "
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(revisions=["r" * 241]))
    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(claim(source=source(excerpt="e" * 241)))


def test_brief_requires_frontend_fields_and_allows_empty_optional_value_proposition():
    parsed = CreativeBrief.model_validate(brief())

    assert parsed.valueProposition == ""
    assert parsed.requirementsConfirmed is False

    missing = brief()
    del missing["targetAudience"]
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(missing)
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(targetAudience="  "))
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(targetAudience="x" * 501))


def test_brief_rejects_extra_fields_invalid_enums_and_coercion():
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(objective="sales"))
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(duration="15"))
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(requirementsConfirmed=1))
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(serverPath="C:/private"))


@pytest.mark.parametrize("duration", [1, 60])
def test_scene_accepts_inclusive_duration_boundaries(duration):
    assert StoryboardScene.model_validate(scene(durationSeconds=duration)).durationSeconds == duration


@pytest.mark.parametrize("duration", [None, 0, -1, 61, 1.5, "15", True])
def test_scene_rejects_missing_fractional_out_of_range_and_coerced_durations(duration):
    value = scene()
    if duration is None:
        del value["durationSeconds"]
    else:
        value["durationSeconds"] = duration
    with pytest.raises(ValidationError):
        StoryboardScene.model_validate(value)


def test_storyboard_allows_empty_collection_but_runtime_is_unavailable():
    parsed = StoryboardInput.model_validate({"scenes": []})

    assert parsed.scenes == []
    assert calculate_storyboard_runtime(parsed.scenes) is None
    result = validate_contract_input(facts={"facts": []}, brief=brief(), storyboard={"scenes": []})
    assert result.valid
    assert result.plannedRuntimeSeconds is None


def test_runtime_uses_all_valid_scenes_and_is_unavailable_for_any_invalid_scene():
    assert calculate_storyboard_runtime([scene(durationSeconds=1), scene(id="two", durationSeconds=60)]) == 61
    assert calculate_storyboard_runtime([scene(durationSeconds=10), scene(id="bad", durationSeconds=0)]) is None
    assert calculate_storyboard_runtime([scene(durationSeconds=10), {"id": "missing-duration"}]) is None


def test_collections_and_scene_text_are_bounded_and_extra_fields_rejected():
    with pytest.raises(ValidationError):
        BusinessClaims.model_validate({"facts": [claim(id=f"fact-{index}") for index in range(33)]})
    with pytest.raises(ValidationError):
        StoryboardInput.model_validate({"scenes": [scene(id=f"scene-{index}") for index in range(33)]})
    with pytest.raises(ValidationError):
        StoryboardScene.model_validate(scene(narration="n" * 1001))
    with pytest.raises(ValidationError):
        StoryboardScene.model_validate(scene(untrustedExtra="ignored?"))
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(reliedUponFactIds=["product", "product"]))
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(reliedUponFactIds=["f" * 65]))
    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(brief(reliedUponFactIds=["not a fact id"]))


def test_combined_validation_returns_sanitized_paths_and_unavailable_runtime():
    result = validate_contract_input(
        facts={"facts": [claim(status="verified")]},
        brief=brief(targetAudience=""),
        storyboard={"scenes": [scene(durationSeconds=0)]},
    )

    assert not result.valid
    assert result.plannedRuntimeSeconds is None
    assert {issue.path.split(".")[0] for issue in result.issues} == {"facts", "brief", "storyboard"}
    assert all("verified" not in issue.message for issue in result.issues)


def test_combined_validation_does_not_reflect_unknown_field_names():
    secret_key = "private-token-value"
    result = validate_contract_input(
        facts={"facts": [], secret_key: "not returned"},
        brief=brief(),
        storyboard={"scenes": []},
    )

    assert not result.valid
    assert secret_key not in repr(result)
    assert any(issue.path == "facts.extra_field" for issue in result.issues)


def test_validation_has_no_network_subprocess_or_filesystem_write(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("pure contract validation must not perform I/O")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)

    result = validate_contract_input(
        facts={"facts": [claim(source=source(kind="website", reference="https://example.test/about"))]},
        brief=brief(),
        storyboard={"scenes": [scene(durationSeconds=1)]},
    )

    assert result.valid
    assert result.plannedRuntimeSeconds == 1
