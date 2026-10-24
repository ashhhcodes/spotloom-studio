from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from adforge_renderer.asset_contract import (
    ASSET_FORMAT,
    AssetLeaseRequest,
    AssetDeclaration,
    AssetValidationEvidence,
    ManagedAsset,
    PrivateObjectVersionReference,
)
from adforge_renderer.asset_resolution import (
    AssetVersionRecord,
    bind_lease_request_to_resolution,
    resolve_versioned_assets,
)
from adforge_renderer.production_package import PROFILE_ID, validate_production_package, validate_production_package_v2
from adforge_renderer.render_plan import compile_render_plan, compile_versioned_render_plan


FIXTURES = Path(__file__).parent / "fixtures"
V1_PACKAGE = json.loads((FIXTURES / "production-package-valid.json").read_text(encoding="utf-8"))
V2_PACKAGE = json.loads((FIXTURES / "production-package-v2-valid.json").read_text(encoding="utf-8"))
ASSET_ID = "ast_demo_audio_01"
VERSION_ID = "ver_demo_audio_0001"
DIGEST = "a" * 64


def make_managed_asset(
    *,
    asset_id: str = ASSET_ID,
    project_id: str = "sample-northstar",
    version_id: str = VERSION_ID,
    digest: str = DIGEST,
    state: str = "ready",
    evidence_overrides: dict | None = None,
) -> ManagedAsset:
    declaration = AssetDeclaration.model_validate({
        "asset_id": asset_id,
        "project_id": project_id,
        "kind": "audio",
        "declared_format": ASSET_FORMAT,
        "declared_duration_frames": 360,
    })
    evidence = {
        "asset_id": asset_id,
        "project_id": project_id,
        "asset_version_id": version_id,
        "observed": {
            "container": "wav", "codec": "pcm_s16le", "byte_size": 1000,
            "sha256": digest, "duration_frames": 360, "sample_rate": 48000, "channels": 2,
        },
        "validated_at": "2026-10-24T00:00:00Z",
        "validator_version": "demo-validator-1",
        "profile_id": PROFILE_ID,
    }
    evidence.update(evidence_overrides or {})
    evidence_value = AssetValidationEvidence.model_validate(evidence)
    return ManagedAsset(declaration, version_id, state=state, validation=evidence_value)


def make_plan(payload: dict | None = None):
    result = compile_versioned_render_plan(validate_production_package_v2(payload or copy.deepcopy(V2_PACKAGE)))
    assert result.succeeded and result.plan is not None
    return result.plan


def records_for(plan, asset: ManagedAsset | None = None):
    asset = asset or make_managed_asset()
    return (AssetVersionRecord(asset=asset, content_digest=DIGEST),)


def test_matches_valid_v2_plan_to_one_immutable_snapshot():
    plan = make_plan()

    result = resolve_versioned_assets(plan, records_for(plan))

    assert result.succeeded
    assert result.issues == ()
    assert result.snapshot is not None
    assert result.snapshot.project_id == "sample-northstar"
    assert result.snapshot.profile_id == PROFILE_ID
    assert len(result.snapshot.assets) == 1
    entry = result.snapshot.assets[0]
    assert (entry.asset_id, entry.asset_version_id, entry.sha256, entry.profile_id) == (
        ASSET_ID, VERSION_ID, DIGEST, PROFILE_ID,
    )


@pytest.mark.parametrize("bad_plan", [None, {}, "plan"])
def test_rejects_non_versioned_plan_inputs(bad_plan):
    result = resolve_versioned_assets(bad_plan, ())

    assert result.snapshot is None
    assert result.issues[0].code == "invalid_plan_type"


def test_rejects_legacy_plan_raw_package_and_validation_result():
    legacy = compile_render_plan(validate_production_package(V1_PACKAGE))
    assert legacy.plan is not None
    for value in (legacy.plan, V2_PACKAGE, validate_production_package_v2(V2_PACKAGE)):
        result = resolve_versioned_assets(value, ())
        assert result.snapshot is None
        assert result.issues
    assert resolve_versioned_assets(legacy.plan, ()).issues[0].code == "legacy_plan_unsupported"


@pytest.mark.parametrize("records", [[], None, "records"])
def test_requires_an_immutable_tuple_of_records(records):
    result = resolve_versioned_assets(make_plan(), records)
    assert result.snapshot is None
    assert result.issues[0].code == "invalid_records_type"


def test_missing_duplicate_and_wrongly_typed_records_fail_without_partial_snapshot():
    plan = make_plan()
    good = records_for(plan)[0]
    cases = [
        ((), "missing_asset_record"),
        ((good, good), "duplicate_asset_record"),
        ((object(),), "invalid_asset_record"),
    ]
    for records, expected in cases:
        result = resolve_versioned_assets(plan, records)
        assert result.snapshot is None
        assert expected in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    ("asset", "expected"),
    [
        (make_managed_asset(project_id="another-project"), "project_mismatch"),
        (make_managed_asset(version_id="ver_other_asset_0001"), "version_mismatch"),
        (make_managed_asset(asset_id="ast_other_asset_01"), "missing_asset_record"),
    ],
)
def test_project_asset_and_version_mismatches_are_rejected(asset, expected):
    result = resolve_versioned_assets(make_plan(), records_for(make_plan(), asset))
    assert result.snapshot is None
    assert expected in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    "state",
    ["uploading", "quarantined", "validating", "failed", "rejected", "deletion_pending", "deleted", "expired"],
)
def test_only_ready_lifecycle_state_is_accepted(state):
    asset = make_managed_asset(state=state)
    result = resolve_versioned_assets(make_plan(), records_for(make_plan(), asset))
    assert result.snapshot is None
    assert "asset_not_ready" in {issue.code for issue in result.issues}


def test_ready_record_requires_matching_validation_evidence_and_digest():
    plan = make_plan()
    no_evidence = ManagedAsset(make_managed_asset().declaration, VERSION_ID, state="quarantined")
    absent = resolve_versioned_assets(plan, records_for(plan, no_evidence))
    assert absent.snapshot is None
    assert "asset_not_ready" in {issue.code for issue in absent.issues}
    assert "validation_evidence_missing" in {issue.code for issue in absent.issues}

    mismatch = resolve_versioned_assets(plan, (AssetVersionRecord(make_managed_asset(), "b" * 64),))
    assert mismatch.snapshot is None
    assert "asset_digest_mismatch" in {issue.code for issue in mismatch.issues}

    malformed = resolve_versioned_assets(plan, (AssetVersionRecord(make_managed_asset(), "not-a-digest"),))
    assert malformed.snapshot is None
    assert "invalid_asset_digest" in {issue.code for issue in malformed.issues}


def test_bad_evidence_identity_and_observed_metadata_are_rejected():
    plan = make_plan()
    bad_evidence_asset = make_managed_asset(
        state="failed", evidence_overrides={"asset_id": "ast_different_01"},
    )
    result = resolve_versioned_assets(plan, records_for(plan, bad_evidence_asset))
    assert result.snapshot is None
    assert "validation_evidence_mismatch" in {issue.code for issue in result.issues}

    base_asset = make_managed_asset(state="failed")
    invalid_profile_evidence = base_asset.validation.model_copy(
        update={"profile_id": "unsupported-profile"},
    )
    unsupported_profile = ManagedAsset(
        base_asset.declaration, VERSION_ID, state="failed", validation=invalid_profile_evidence,
    )
    result = resolve_versioned_assets(plan, records_for(plan, unsupported_profile))
    assert result.snapshot is None
    assert "invalid_validation_evidence" in {issue.code for issue in result.issues}

    bad_observed_asset = make_managed_asset(
        state="failed", evidence_overrides={"observed": {
            "container": "mp3", "codec": "other", "byte_size": 1000,
            "sha256": DIGEST, "duration_frames": 360, "sample_rate": 48000, "channels": 2,
        }},
    )
    result = resolve_versioned_assets(plan, records_for(plan, bad_observed_asset))
    assert result.snapshot is None
    assert "validation_evidence_mismatch" in {issue.code for issue in result.issues}


def test_unsupported_plan_profile_and_inconsistent_segment_pins_fail_closed():
    plan = make_plan()
    bad_profile = replace(plan, profile=replace(plan.profile, profile_id="other-profile"))
    result = resolve_versioned_assets(bad_profile, records_for(plan))
    assert result.snapshot is None
    assert "unsupported_profile" in {issue.code for issue in result.issues}

    altered_profile = replace(plan, profile=replace(plan.profile, width=720))
    result = resolve_versioned_assets(altered_profile, records_for(plan))
    assert result.snapshot is None
    assert "unsupported_profile" in {issue.code for issue in result.issues}

    bad_audio = replace(plan.audio_segments[0], asset_version_id="ver_other_asset_0001")
    bad_plan = replace(plan, audio_segments=(bad_audio,))
    result = resolve_versioned_assets(bad_plan, records_for(plan))
    assert result.snapshot is None
    assert "segment_version_mismatch" in {issue.code for issue in result.issues}


def test_duplicate_plan_declarations_and_ambiguous_audio_references_fail():
    plan = make_plan()
    duplicate_plan = replace(plan, assets=plan.assets + plan.assets)
    result = resolve_versioned_assets(duplicate_plan, records_for(plan))
    assert result.snapshot is None
    assert "duplicate_plan_asset" in {issue.code for issue in result.issues}

    orphan_segment = replace(plan.audio_segments[0], asset_id="ast_missing_audio_01")
    result = resolve_versioned_assets(replace(plan, audio_segments=(orphan_segment,)), records_for(plan))
    assert result.snapshot is None
    assert "segment_asset_missing" in {issue.code for issue in result.issues}

    malformed_segment = replace(plan.audio_segments[0], asset_id=[])
    result = resolve_versioned_assets(replace(plan, audio_segments=(malformed_segment,)), records_for(plan))
    assert result.snapshot is None
    assert "invalid_plan_segment" in {issue.code for issue in result.issues}


def test_multiple_segments_reuse_one_declaration_and_snapshot_is_deterministic():
    plan = make_plan()
    extra_segment = replace(plan.audio_segments[0], segment_id="second-segment")
    plan = replace(plan, audio_segments=plan.audio_segments + (extra_segment,))

    first = resolve_versioned_assets(plan, records_for(plan))
    second = resolve_versioned_assets(plan, records_for(plan))

    assert first.succeeded and first == second
    assert first.snapshot is not None
    assert len(first.snapshot.assets) == 1
    assert len(plan.audio_segments) == 2


def test_multiple_assets_and_segments_keep_each_exact_pin():
    plan = make_plan()
    second_id = "ast_demo_audio_02"
    second_version = "ver_demo_audio_0002"
    second_asset = replace(plan.assets[0], asset_id=second_id, asset_version_id=second_version)
    second_segment = replace(
        plan.audio_segments[0], segment_id="second-asset-segment",
        asset_id=second_id, asset_version_id=second_version,
    )
    expanded = replace(
        plan,
        assets=plan.assets + (second_asset,),
        audio_segments=plan.audio_segments + (second_segment,),
    )
    records = (
        AssetVersionRecord(make_managed_asset(), DIGEST),
        AssetVersionRecord(make_managed_asset(
            asset_id=second_id, version_id=second_version, digest="b" * 64,
        ), "b" * 64),
    )

    result = resolve_versioned_assets(expanded, records)

    assert result.succeeded
    assert result.snapshot is not None
    assert [(item.asset_id, item.asset_version_id, item.sha256) for item in result.snapshot.assets] == [
        (ASSET_ID, VERSION_ID, DIGEST),
        (second_id, second_version, "b" * 64),
    ]


def _lease_ready_snapshot(two_assets: bool = False):
    plan = make_plan()
    reference = PrivateObjectVersionReference(value="opaque-object-version-0001")
    records = [AssetVersionRecord(make_managed_asset(), DIGEST, reference)]
    if two_assets:
        second_id = "ast_demo_audio_02"
        second_version = "ver_demo_audio_0002"
        second_plan_asset = replace(plan.assets[0], asset_id=second_id, asset_version_id=second_version)
        second_segment = replace(
            plan.audio_segments[0], segment_id="second-asset-segment",
            asset_id=second_id, asset_version_id=second_version,
        )
        plan = replace(
            plan, assets=plan.assets + (second_plan_asset,),
            audio_segments=plan.audio_segments + (second_segment,),
        )
        records.append(AssetVersionRecord(
            make_managed_asset(asset_id=second_id, version_id=second_version, digest="b" * 64),
            "b" * 64,
            PrivateObjectVersionReference(value="opaque-object-version-0002"),
        ))
    resolution = resolve_versioned_assets(plan, tuple(records))
    assert resolution.succeeded and resolution.snapshot is not None
    return resolution.snapshot


def _lease_request(snapshot, assets=None):
    pins = tuple({
        "asset_id": item.asset_id,
        "asset_version_id": item.asset_version_id,
        "object_version": item.object_version.model_dump(mode="python"),
        "sha256": item.sha256,
        "profile_id": item.profile_id,
        "declared_duration_frames": item.declared_duration_frames,
    } for item in (snapshot.assets if assets is None else assets))
    return AssetLeaseRequest(project_id=snapshot.project_id, job_id="job-demo-0001", assets=pins)


def test_lease_request_must_match_the_complete_resolution_pin_set():
    snapshot = _lease_ready_snapshot(two_assets=True)
    complete = _lease_request(snapshot)
    assert bind_lease_request_to_resolution(snapshot, complete).matches

    missing = _lease_request(snapshot, snapshot.assets[:1])
    missing_result = bind_lease_request_to_resolution(snapshot, missing)
    assert not missing_result.matches
    assert "lease_pin_missing" in {issue.code for issue in missing_result.issues}

    single_snapshot = _lease_ready_snapshot()
    complete_single = _lease_request(single_snapshot)
    extra_asset = replace(
        single_snapshot.assets[0], asset_id="ast_extra_asset_01",
        asset_version_id="ver_extra_asset_01",
    )
    extra = _lease_request(single_snapshot, (single_snapshot.assets[0], extra_asset))
    extra_result = bind_lease_request_to_resolution(single_snapshot, extra)
    assert not extra_result.matches
    assert "lease_pin_extra" in {issue.code for issue in extra_result.issues}

    duplicate = complete_single.model_copy(update={"assets": (complete_single.assets[0],) * 2})
    duplicate_result = bind_lease_request_to_resolution(single_snapshot, duplicate)
    assert not duplicate_result.matches
    assert "invalid_lease_binding" in {issue.code for issue in duplicate_result.issues}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_version_id", "ver_other_asset_0001"),
        ("object_version", PrivateObjectVersionReference(value="different-object-version")),
        ("sha256", "b" * 64),
        ("declared_duration_frames", 359),
    ],
)
def test_lease_request_rejects_each_mismatched_resolution_pin(field, value):
    snapshot = _lease_ready_snapshot()
    request = _lease_request(snapshot)
    mismatched_pin = request.assets[0].model_copy(update={field: value})
    malformed_request = request.model_copy(update={"assets": (mismatched_pin,)})

    result = bind_lease_request_to_resolution(snapshot, malformed_request)

    assert not result.matches
    assert "lease_pin_mismatch" in {issue.code for issue in result.issues}


def test_lease_binding_rejects_unsupported_or_duplicate_resolution_assets():
    snapshot = _lease_ready_snapshot()
    request = _lease_request(snapshot)

    unsupported = replace(snapshot, profile_id="unsupported-profile")
    unsupported_result = bind_lease_request_to_resolution(unsupported, request)
    duplicate = replace(snapshot, assets=snapshot.assets + snapshot.assets)
    duplicate_result = bind_lease_request_to_resolution(duplicate, request)

    assert not unsupported_result.matches
    assert "unsupported_resolution_profile" in {issue.code for issue in unsupported_result.issues}
    assert not duplicate_result.matches
    assert "duplicate_resolution_asset" in {issue.code for issue in duplicate_result.issues}


def test_all_or_nothing_results_have_sorted_sanitized_issues():
    plan = make_plan()
    secret = "SENTINEL_PRIVATE_ASSET_VALUE"
    bad_one = make_managed_asset(asset_id="ast_bad_asset_0001", project_id=secret, state="failed")
    bad_two = make_managed_asset(asset_id="ast_bad_asset_0002", project_id=secret, state="failed")
    records = (
        AssetVersionRecord(bad_two, DIGEST),
        AssetVersionRecord(bad_one, DIGEST),
        AssetVersionRecord(make_managed_asset(), "bad-digest"),
    )
    first = resolve_versioned_assets(plan, records)
    second = resolve_versioned_assets(plan, records)
    assert first.snapshot is None and second.snapshot is None
    assert first.issues == second.issues
    assert list(first.issues) == sorted(first.issues, key=lambda item: (item.path, item.code, item.message))
    assert secret not in repr(first.issues)
    assert "asset_not_ready" in {issue.code for issue in first.issues}
    assert "invalid_asset_digest" in {issue.code for issue in first.issues}


def test_snapshot_and_nested_values_are_immutable():
    result = resolve_versioned_assets(make_plan(), records_for(make_plan()))
    assert result.snapshot is not None
    snapshot = result.snapshot
    with pytest.raises(FrozenInstanceError):
        snapshot.project_id = "changed"
    with pytest.raises(FrozenInstanceError):
        snapshot.assets[0].sha256 = "b" * 64
    with pytest.raises(TypeError):
        snapshot.assets[0] = snapshot.assets[0]


def test_unexpected_record_is_rejected_and_no_extra_values_enter_snapshot():
    plan = make_plan()
    extra = make_managed_asset(asset_id="ast_extra_asset_0001")
    result = resolve_versioned_assets(plan, records_for(plan) + (AssetVersionRecord(extra, DIGEST),))
    assert result.snapshot is None
    assert "unexpected_asset_record" in {issue.code for issue in result.issues}
