from __future__ import annotations

import copy
import json
from pathlib import Path
import socket
import subprocess

import pytest

from adforge_renderer.production_package import (
    CONTRACT_VERSION_V2,
    MAX_PACKAGE_BYTES,
    ProductionPackage,
    ProductionPackageV2,
    ProductionPackageV2Validation,
    validate_production_package,
    validate_production_package_json,
)


FIXTURES = Path(__file__).parent / "fixtures"
VALID = json.loads((FIXTURES / "production-package-valid.json").read_text(encoding="utf-8"))
INVALID = json.loads((FIXTURES / "production-package-invalid.json").read_text(encoding="utf-8"))
VALID_V2 = json.loads((FIXTURES / "production-package-v2-valid.json").read_text(encoding="utf-8"))
INVALID_V2 = json.loads((FIXTURES / "production-package-v2-invalid.json").read_text(encoding="utf-8"))


def codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def test_valid_fixture_matches_versioned_profile_and_exact_fifteen_seconds():
    result = validate_production_package(VALID)

    assert result.valid
    assert result.issues == ()
    assert isinstance(result.package, ProductionPackage)
    assert result.contract_version == "spotloom.production-package.v1"
    assert sum(scene.durationFrames for scene in result.package.scenes) == 360
    assert result.package.rendererProfileId == "spotloom.storyboard.vertical-1080x1920-h264-aac-15s.v1"


def test_v2_fixture_dispatches_to_strict_versioned_schema_without_digest():
    result = validate_production_package(VALID_V2)
    json_result = validate_production_package_json(json.dumps(VALID_V2))

    assert result.valid and json_result.valid
    assert isinstance(result, ProductionPackageV2Validation)
    assert isinstance(result.package, ProductionPackageV2)
    assert result.contract_version == CONTRACT_VERSION_V2
    assert result.package.projectId == "sample-northstar"
    assert result.package.assets[0].assetVersionId == "ver_demo_audio_0001"
    assert "sha256" not in result.package.assets[0].model_dump()


def test_invalid_v2_fixture_rejects_malformed_asset_version():
    result = validate_production_package(INVALID_V2)

    assert not result.valid
    assert "package_schema_invalid" in codes(result)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda payload: payload.pop("projectId"), "package_schema_invalid"),
        (lambda payload: payload.update(projectId="../other-project"), "package_schema_invalid"),
        (lambda payload: payload["assets"][0].pop("assetVersionId"), "package_schema_invalid"),
        (lambda payload: payload["assets"][0].update(assetVersionId="ver_short"), "package_schema_invalid"),
        (lambda payload: payload["assets"][0].update(assetVersionId=42), "package_schema_invalid"),
        (lambda payload: payload["assets"].append(copy.deepcopy(payload["assets"][0])), "duplicate_asset_id"),
        (lambda payload: payload["audioSegments"][0].update(assetId="ast_missing_0001"), "asset_reference_missing"),
        (lambda payload: payload["assets"][0].update(declaredDurationFrames=True), "package_schema_invalid"),
        (lambda payload: payload["assets"][0].update(unexpected="value"), "package_schema_invalid"),
        (lambda payload: payload["assets"][0].update(sha256="a" * 64), "package_schema_invalid"),
    ],
    ids=["missing-project", "invalid-project", "missing-version", "malformed-version", "wrong-version-type", "duplicate-asset", "undeclared-reference", "strict-bool", "unknown-field", "untrusted-digest"],
)
def test_v2_schema_and_reference_constraints(mutation, expected):
    payload = copy.deepcopy(VALID_V2)
    mutation(payload)

    result = validate_production_package(payload)

    assert not result.valid
    assert expected in codes(result)
    assert result.package is None


def test_v2_unknown_contract_version_does_not_default_to_v1():
    payload = copy.deepcopy(VALID_V2)
    payload["contractVersion"] = "spotloom.production-package.v3"

    result = validate_production_package_json(json.dumps(payload))

    assert not result.valid
    assert "unsupported_contract_version" in codes(result)
    assert result.package is None
    assert result.contract_version is None


@pytest.mark.parametrize(
    "replacement",
    [None, "", "spotloom.production-package.v2.0"],
    ids=["missing", "empty", "malformed"],
)
def test_missing_or_malformed_contract_version_fails_deterministically(replacement):
    payload = copy.deepcopy(VALID_V2)
    if replacement is None:
        del payload["contractVersion"]
    else:
        payload["contractVersion"] = replacement

    first = validate_production_package_json(json.dumps(payload))
    second = validate_production_package_json(json.dumps(payload))

    assert not first.valid
    assert first == second
    assert "unsupported_contract_version" in codes(first)
    assert first.package is None
    assert first.contract_version is None


def test_empty_decoded_object_does_not_claim_a_contract_version():
    result = validate_production_package({})

    assert not result.valid
    assert "unsupported_contract_version" in codes(result)
    assert result.contract_version is None


def test_explicit_v2_validator_does_not_claim_v2_for_another_version():
    from adforge_renderer.production_package import validate_production_package_v2

    result = validate_production_package_v2({"contractVersion": "spotloom.production-package.v3"})

    assert not result.valid
    assert "unsupported_contract_version" in codes(result)
    assert result.contract_version is None


def test_v2_json_uses_shared_nested_duplicate_key_protection():
    raw = json.dumps(VALID_V2, separators=(",", ":"))
    raw = raw.replace('"projectId":"sample-northstar"', '"projectId":"sample-northstar","projectId":"sample-northstar"')

    result = validate_production_package_json(raw)

    assert not result.valid
    assert codes(result) == {"invalid_json"}


def test_invalid_fixture_reports_duration_and_scene_total_without_raw_values():
    result = validate_production_package(INVALID)

    assert not result.valid
    assert {"profile_duration_mismatch", "scene_duration_total_mismatch"} <= codes(result)
    assert all(issue.severity == "error" for issue in result.issues)


def test_profile_requires_nine_sixteen_aspect_ratio():
    payload = copy.deepcopy(VALID)
    payload["brief"]["aspectRatio"] = "1:1"

    assert "profile_aspect_ratio_mismatch" in codes(validate_production_package(payload))


@pytest.mark.parametrize("field,value,expected", [
    ("contractVersion", "spotloom.production-package.v3", "unsupported_contract_version"),
    ("rendererProfileId", "unknown-profile", "unsupported_profile"),
    ("correlationId", "not-a-uuid", "invalid_correlation_id"),
])
def test_version_profile_and_correlation_are_strict(field, value, expected):
    payload = copy.deepcopy(VALID)
    payload[field] = value

    result = validate_production_package(payload)

    assert not result.valid
    assert expected in codes(result)


def test_extra_or_missing_fields_are_rejected_with_safe_stable_issues():
    extra = copy.deepcopy(VALID)
    extra["serverPath-secret"] = "do-not-reflect"
    missing = copy.deepcopy(VALID)
    del missing["scenes"]

    extra_result = validate_production_package(extra)
    missing_result = validate_production_package(missing)

    assert not extra_result.valid and not missing_result.valid
    assert "package_schema_invalid" in codes(extra_result)
    assert "package_schema_invalid" in codes(missing_result)
    assert all("do-not-reflect" not in issue.path + issue.message for issue in extra_result.issues)
    assert all(issue.message == "Value does not match the supported production package contract." for issue in extra_result.issues)


def test_claim_copy_requires_existing_approved_fact_and_exact_current_text():
    unapproved = copy.deepcopy(VALID)
    unapproved["facts"][0]["status"] = "unreviewed"
    mismatch = copy.deepcopy(VALID)
    mismatch["scenes"][0]["elements"][0]["content"]["text"] = "Northstar Coffee!"
    missing = copy.deepcopy(VALID)
    missing["scenes"][0]["elements"][0]["content"]["factId"] = "missing-fact"

    assert "fact_not_caller_approved" in codes(validate_production_package(unapproved))
    assert "claim_text_mismatch" in codes(validate_production_package(mismatch))
    assert "fact_reference_missing" in codes(validate_production_package(missing))


@pytest.mark.parametrize("field", ["targetAudience", "productOrOffer", "keyMessage", "tone", "callToAction"])
def test_brief_claims_require_explicit_exact_approved_fact_association(field):
    payload = copy.deepcopy(VALID)
    payload["brief"][field] = {"kind": "claim", "text": "Northstar Coffee", "factId": "brand"}
    assert validate_production_package(payload).valid
    payload["brief"][field]["text"] = " northstar coffee "
    assert "claim_text_mismatch" in codes(validate_production_package(payload))


@pytest.mark.parametrize("field", ["title", "narrativePurpose"])
def test_scene_claim_text_requires_fact_association(field):
    payload = copy.deepcopy(VALID)
    payload["scenes"][0][field] = {"kind": "claim", "text": "Northstar Coffee", "factId": "brand"}
    assert validate_production_package(payload).valid
    payload["scenes"][0][field]["factId"] = "missing"
    assert "fact_reference_missing" in codes(validate_production_package(payload))


@pytest.mark.parametrize("claim", ["northstar coffee", " Northstar Coffee", "Northstar Coffee ", "Cafe\u0301"])
def test_claim_match_is_case_and_whitespace_sensitive(claim):
    payload = copy.deepcopy(VALID)
    payload["facts"][0]["claim"] = "Café"
    payload["scenes"][0]["elements"][0]["content"] = {
        "kind": "claim", "text": claim, "factId": "brand",
    }
    assert "claim_text_mismatch" in codes(validate_production_package(payload))


def test_claim_match_is_case_sensitive_for_otherwise_identical_text():
    payload = copy.deepcopy(VALID)
    payload["facts"][0]["claim"] = "Northstar Coffee"
    payload["scenes"][0]["elements"][0]["content"]["text"] = "northstar coffee"
    result = validate_production_package(payload)
    assert codes(result) == {"claim_text_mismatch"}


@pytest.mark.parametrize("duration", [True, 180.0, "180"])
def test_frame_fields_reject_booleans_and_coercive_numbers(duration):
    payload = copy.deepcopy(VALID)
    payload["scenes"][0]["durationFrames"] = duration
    assert "package_schema_invalid" in codes(validate_production_package(payload))


def test_brief_and_scene_text_require_explicit_classification():
    payload = copy.deepcopy(VALID)
    payload["brief"]["keyMessage"] = "A good cup, made simple."
    assert "package_schema_invalid" in codes(validate_production_package(payload))
    payload = copy.deepcopy(VALID)
    payload["scenes"][0]["title"] = "Opening"
    assert "package_schema_invalid" in codes(validate_production_package(payload))


def test_ordered_scenes_and_transition_rules_are_enforced():
    payload = copy.deepcopy(VALID)
    payload["scenes"][1]["order"] = 1

    result = validate_production_package(payload)

    assert not result.valid
    assert "scene_order_invalid" in codes(result)

    payload["scenes"][1]["transitionFromPrevious"] = "crossfade"
    assert "package_schema_invalid" in codes(validate_production_package(payload))


def test_narration_is_optional_per_scene_but_when_present_is_timed_and_grounded():
    payload = copy.deepcopy(VALID)
    payload["audioSegments"] = [{
        "id": "narration-one",
        "kind": "narration",
        "assetId": "ast_demo_audio_01",
        "sceneId": "opening",
        "startFrame": 0,
        "endFrame": 180,
        "sourceStartFrame": 0,
        "transcript": {"kind": "claim", "text": "Northstar Coffee", "factId": "brand"},
    }]

    assert validate_production_package(payload).valid

    payload["audioSegments"][0]["endFrame"] = 181
    assert "narration_outside_scene" in codes(validate_production_package(payload))


def test_narration_segments_cannot_overlap_within_a_scene():
    payload = copy.deepcopy(VALID)
    payload["audioSegments"] = [
        {
            "id": "narration-one",
            "kind": "narration",
            "assetId": "ast_demo_audio_01",
            "sceneId": "opening",
            "startFrame": 0,
            "endFrame": 100,
            "sourceStartFrame": 0,
            "transcript": {"kind": "claim", "text": "Northstar Coffee", "factId": "brand"},
        },
        {
            "id": "narration-two",
            "kind": "narration",
            "assetId": "ast_demo_audio_01",
            "sceneId": "opening",
            "startFrame": 99,
            "endFrame": 180,
            "sourceStartFrame": 0,
            "transcript": {"kind": "creative", "text": "Take a moment."},
        },
    ]

    assert "narration_overlap" in codes(validate_production_package(payload))


def test_scene_associated_music_must_fit_scene_but_global_music_may_span_scenes():
    payload = copy.deepcopy(VALID)
    payload["audioSegments"][0]["sceneId"] = "opening"
    payload["audioSegments"][0]["endFrame"] = 181
    assert "audio_outside_scene" in codes(validate_production_package(payload))

    payload["audioSegments"][0]["sceneId"] = None
    assert validate_production_package(payload).valid


def test_source_trim_is_bounded_and_music_effect_gaps_and_overlaps_are_allowed():
    payload = copy.deepcopy(VALID)
    payload["audioSegments"] = [
        {"id": "music-a", "kind": "music", "assetId": "ast_demo_audio_01", "sceneId": None,
         "startFrame": 0, "endFrame": 180, "sourceStartFrame": 0, "transcript": None},
        {"id": "music-b", "kind": "sound_effect", "assetId": "ast_demo_audio_01", "sceneId": None,
         "startFrame": 60, "endFrame": 120, "sourceStartFrame": 60, "transcript": None},
    ]
    assert validate_production_package(payload).valid

    payload["audioSegments"][1]["sourceStartFrame"] = 350
    assert "audio_exceeds_declared_asset" in codes(validate_production_package(payload))


def test_duplicate_identifiers_and_visual_bounds_are_reported():
    duplicate = copy.deepcopy(VALID)
    duplicate["scenes"][1]["id"] = duplicate["scenes"][0]["id"]
    duplicate["audioSegments"].append(copy.deepcopy(duplicate["audioSegments"][0]))
    bounds = copy.deepcopy(VALID)
    bounds["scenes"][0]["elements"][0]["x"] = 9000

    duplicate_codes = codes(validate_production_package(duplicate))
    assert "duplicate_scene_id" in duplicate_codes
    assert "duplicate_segment_id" in duplicate_codes
    assert "visual_bounds_out_of_range" in codes(validate_production_package(bounds))


def test_audio_must_be_present_and_assets_must_be_declared_and_referenced():
    no_audio = copy.deepcopy(VALID)
    no_audio["audioSegments"] = []
    unknown_asset = copy.deepcopy(VALID)
    unknown_asset["audioSegments"][0]["assetId"] = "ast_unknown_asset"
    unused_asset = copy.deepcopy(VALID)
    unused_asset["assets"].append({
        "id": "ast_unused_0001",
        "kind": "audio",
        "format": "wav-pcm-s16le-48000-stereo",
        "declaredDurationFrames": 360,
    })

    assert "package_schema_invalid" in codes(validate_production_package(no_audio))
    assert "asset_reference_missing" in codes(validate_production_package(unknown_asset))
    assert "asset_unused" in codes(validate_production_package(unused_asset))


def test_asset_reference_is_opaque_and_does_not_imply_availability():
    payload = copy.deepcopy(VALID)
    payload["assets"][0]["id"] = "ast_missing_from_any_real_store"
    payload["audioSegments"][0]["assetId"] = payload["assets"][0]["id"]

    assert validate_production_package(payload).valid

    payload["assets"][0]["id"] = "C:/private/audio.wav"
    payload["audioSegments"][0]["assetId"] = "C:/private/audio.wav"
    assert "package_schema_invalid" in codes(validate_production_package(payload))


def test_json_parser_enforces_byte_limit_duplicate_keys_and_safe_invalid_json():
    valid_json = json.dumps(VALID, separators=(",", ":"))
    assert validate_production_package_json(valid_json).valid
    oversized = validate_production_package_json(b" " * (MAX_PACKAGE_BYTES + 1))
    duplicate = validate_production_package_json('{"contractVersion":"v1","contractVersion":"v2"}')
    malformed = validate_production_package_json("<html>bad payload secret</html>")

    assert codes(oversized) == {"payload_too_large"}
    assert codes(duplicate) == {"invalid_json"}
    assert codes(malformed) == {"invalid_json"}
    assert "secret" not in malformed.issues[0].message


def test_json_parser_rejects_nested_duplicate_keys_invalid_utf8_nonfinite_and_wrong_types():
    nested_duplicate = validate_production_package_json('{"outer":{"x":1,"x":2}}')
    invalid_utf8 = validate_production_package_json(b"\xff")
    nonfinite = validate_production_package_json(json.dumps(VALID, separators=(",", ":")).replace('"duration":15', '"duration":NaN'))
    wrong_type = validate_production_package_json(VALID)
    escaped_surrogate = validate_production_package_json(json.dumps(VALID).replace("Northstar Coffee", "\\ud800"))

    assert codes(nested_duplicate) == {"invalid_json"}
    assert codes(invalid_utf8) == {"invalid_json"}
    assert codes(nonfinite) == {"invalid_json"}
    assert codes(wrong_type) == {"invalid_input_type"}
    assert codes(escaped_surrogate) == {"invalid_unicode"}


def test_json_parser_handles_deep_nesting_without_leaking_parser_exception():
    result = validate_production_package_json("[" * 20_000 + "]" * 20_000)
    assert codes(result) == {"invalid_json"}


def test_json_parser_controls_post_parse_recursion_in_unicode_scan():
    nested = 0
    for _ in range(400):
        nested = [nested]
    payload = copy.deepcopy(VALID)
    payload["nestedProbe"] = nested
    raw = json.dumps(payload, separators=(",", ":"))
    assert len(raw.encode("utf-8")) < MAX_PACKAGE_BYTES

    result = validate_production_package_json(raw)

    assert codes(result) == {"package_schema_invalid"}
    assert all(len(issue.message) <= 120 for issue in result.issues)


def test_json_byte_limit_accepts_exact_boundary_and_rejects_one_byte_over():
    compact = json.dumps(VALID, separators=(",", ":"))
    exact = compact + " " * (MAX_PACKAGE_BYTES - len(compact.encode("utf-8")))
    assert len(exact.encode("utf-8")) == MAX_PACKAGE_BYTES
    assert validate_production_package_json(exact).valid
    assert codes(validate_production_package_json(exact + " ")) == {"payload_too_large"}


def test_cross_reference_findings_have_stable_order():
    payload = copy.deepcopy(VALID)
    payload["scenes"][0]["durationFrames"] = 179
    payload["scenes"][0]["elements"][0]["content"]["text"] = "mismatch"
    first = validate_production_package(payload).issues
    second = validate_production_package(payload).issues
    assert first == second
    assert tuple(first) == tuple(sorted(first, key=lambda issue: (issue.path, issue.code, issue.message)))


def test_validation_has_no_filesystem_network_or_subprocess_side_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("pure package validation attempted external I/O")

    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    result = validate_production_package(copy.deepcopy(VALID))

    assert result.valid
