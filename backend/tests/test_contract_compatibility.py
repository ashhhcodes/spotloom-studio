from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adforge_renderer.facts import BusinessFact
from adforge_renderer.integration_schemas import (
    BusinessClaim,
    BusinessClaims,
    CreativeBrief,
    StoryboardInput,
    calculate_storyboard_runtime,
    validate_contract_input,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "contract-compatibility.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
VALID = FIXTURES["validNorthstar"]
MUTATIONS = FIXTURES["mutations"]


def test_shared_valid_fixture_is_accepted_and_runtime_is_derived():
    result = validate_contract_input(
        facts={"facts": VALID["facts"]},
        brief=VALID["brief"],
        storyboard=VALID["storyboard"],
    )

    assert result.valid
    assert result.issues == ()
    assert result.plannedRuntimeSeconds == 15
    assert calculate_storyboard_runtime(VALID["storyboard"]["scenes"]) == 15


def test_shared_duration_boundary_scenes_are_accepted():
    storyboard = {"scenes": FIXTURES["boundaryDurationScenes"]}

    assert StoryboardInput.model_validate(storyboard)
    assert calculate_storyboard_runtime(storyboard["scenes"]) == 61
    assert validate_contract_input(facts={"facts": []}, brief=VALID["brief"], storyboard=storyboard).plannedRuntimeSeconds == 61


@pytest.mark.parametrize("status", ["unreviewed", "approved", "rejected"])
def test_review_status_values_match_frontend_union(status):
    candidate = copy.deepcopy(VALID["facts"][0])
    candidate["status"] = status

    parsed = BusinessClaim.model_validate(candidate)

    assert parsed.status == status


def test_invalid_review_status_is_not_treated_as_approval():
    candidate = copy.deepcopy(VALID["facts"][0])
    candidate["status"] = MUTATIONS["invalidReviewStatus"]

    with pytest.raises(ValidationError):
        BusinessClaim.model_validate(candidate)


def test_shared_invalid_duration_fixture_rejects_runtime_as_a_whole():
    payload = copy.deepcopy(VALID)
    payload["storyboard"]["scenes"][0]["durationSeconds"] = MUTATIONS["invalidDuration"]

    result = validate_contract_input(
        facts={"facts": payload["facts"]}, brief=payload["brief"], storyboard=payload["storyboard"],
    )

    assert not result.valid
    assert result.plannedRuntimeSeconds is None
    assert calculate_storyboard_runtime(payload["storyboard"]["scenes"]) is None


def test_shared_unknown_enum_missing_field_and_extra_field_are_rejected():
    unknown_enum = copy.deepcopy(VALID)
    unknown_enum["brief"]["objective"] = MUTATIONS["unknownObjective"]
    assert not validate_contract_input(
        facts={"facts": unknown_enum["facts"]}, brief=unknown_enum["brief"], storyboard=unknown_enum["storyboard"],
    ).valid

    missing_required = copy.deepcopy(VALID)
    del missing_required["brief"][MUTATIONS["removedBriefField"]]
    assert not validate_contract_input(
        facts={"facts": missing_required["facts"]}, brief=missing_required["brief"], storyboard=missing_required["storyboard"],
    ).valid

    extra_field = copy.deepcopy(VALID)
    extra_field["brief"][MUTATIONS["extraFieldName"]] = MUTATIONS["extraFieldValue"]
    assert not validate_contract_input(
        facts={"facts": extra_field["facts"]}, brief=extra_field["brief"], storyboard=extra_field["storyboard"],
    ).valid


def test_empty_storyboard_is_schema_valid_but_has_no_runtime():
    payload = copy.deepcopy(VALID)
    payload["storyboard"]["scenes"] = []

    result = validate_contract_input(
        facts={"facts": payload["facts"]}, brief=payload["brief"], storyboard=payload["storyboard"],
    )

    assert result.valid
    assert result.plannedRuntimeSeconds is None


def test_python_schema_does_not_accept_client_runtime_as_authoritative():
    payload = copy.deepcopy(VALID)
    payload["storyboard"]["plannedRuntimeSeconds"] = MUTATIONS["callerRuntime"]

    result = validate_contract_input(
        facts={"facts": payload["facts"]}, brief=payload["brief"], storyboard=payload["storyboard"],
    )

    assert not result.valid
    assert result.plannedRuntimeSeconds is None


def test_duplicate_fact_and_scene_ids_are_rejected():
    duplicate_fact = copy.deepcopy(VALID)
    duplicate_fact["facts"][1]["id"] = MUTATIONS["duplicateFactId"]
    with pytest.raises(ValidationError):
        BusinessClaims.model_validate({"facts": duplicate_fact["facts"]})

    duplicate_scene = copy.deepcopy(VALID)
    duplicate_scene["storyboard"]["scenes"][1]["id"] = MUTATIONS["duplicateSceneId"]
    with pytest.raises(ValidationError):
        StoryboardInput.model_validate(duplicate_scene["storyboard"])


def test_frontend_shaped_claim_requires_mapping_to_backend_business_fact():
    with pytest.raises(ValidationError):
        BusinessFact.model_validate(VALID["facts"][0])

    backend_shape = {
        "fact_id": "product",
        "field": "product_or_service",
        "value": "Small-batch roasted coffee",
        "provenance": {"source": "manual", "note": "User supplied"},
        "review_state": "unreviewed",
    }
    assert BusinessFact.model_validate(backend_shape).review_state.value == "unreviewed"


def test_frontend_readiness_has_stronger_scene_content_requirement_than_schema():
    candidate = copy.deepcopy(VALID["storyboard"]["scenes"][0])
    candidate["narrativePurpose"] = MUTATIONS["emptyNarrativePurpose"]

    # The integration schema describes field shape and bounds; frontend readiness
    # separately blocks scenes without narrative purpose.
    assert StoryboardInput.model_validate({"scenes": [candidate]})
