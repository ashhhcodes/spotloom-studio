from __future__ import annotations

import builtins
import copy
from datetime import datetime
from pathlib import Path
import socket
import sqlite3
import subprocess
from typing import get_args

import pytest
from pydantic import ValidationError

from adforge_renderer.production_package import ManagedAudioAsset, PROFILE_ID
from adforge_renderer.asset_contract import (
    ASSET_FORMAT,
    MAX_DECLARED_DURATION_FRAMES,
    AssetDeclaration,
    AssetLifecycleSnapshot,
    AssetVersionBinding,
    AssetLeaseRecord,
    AssetLeaseRequest,
    AssetLeaseTransitionCommand,
    AssetTransitionCommand,
    AssetValidationEvidence,
    LeaseAssetPin,
    ManagedAsset,
    ObservedAudioMetadata,
    ObservedWavProperties,
    PrivateObjectVersionReference,
    VersionBoundValidationEvidence,
    asset_lease_is_valid_at,
    check_asset_transition_preconditions,
    check_asset_lease_transition_preconditions,
    compare_version_bound_evidence,
    create_managed_asset,
    transition_asset,
    validate_asset_declaration,
    validate_asset_validation_evidence,
    validate_observed_audio_metadata,
)


DECLARATION = {
    "asset_id": "ast_demo_audio_01",
    "project_id": "sample-northstar",
    "tenant_id": None,
    "owner_id": None,
    "kind": "audio",
    "declared_format": ASSET_FORMAT,
    "declared_duration_frames": 360,
    "original_filename": "demo-audio.wav",
}
ASSET_VERSION_ID = "ver_demo_audio_0001"

OBSERVED = {
    "container": "wav",
    "codec": "pcm_s16le",
    "byte_size": 100_000,
    "sha256": "a" * 64,
    "duration_frames": 360,
    "sample_rate": 48_000,
    "channels": 2,
}

EVIDENCE = {
    "asset_id": DECLARATION["asset_id"],
    "project_id": DECLARATION["project_id"],
    "asset_version_id": ASSET_VERSION_ID,
    "observed": OBSERVED,
    "validated_at": "2026-10-24T00:00:00Z",
    "validator_version": "wav-checker-1.0",
    "profile_id": PROFILE_ID,
}

VERSION_BOUND_EVIDENCE = {
    "evidence_contract_version": "contract-version-under-review",
    "project_id": DECLARATION["project_id"],
    "asset_id": DECLARATION["asset_id"],
    "asset_version_id": ASSET_VERSION_ID,
    "validation_attempt_id": "attempt-2",
    "object_version": {"value": "opaque-object-version-0001"},
    "sha256": "a" * 64,
    "byte_size": 100_000,
    "observed": {
        "container": "wav",
        "codec": "pcm_s16le",
        "sample_format": "s16le",
        "sample_rate": 48_000,
        "channels": 2,
        "sample_count": 720_000,
        "duration_frames": 360,
    },
    "media_profile_id": ASSET_FORMAT,
    "media_profile_version": "provisional-profile-version",
    "validator_identity": "audio-validator",
    "validator_build": "build-2026.10.24",
    "validated_at": "2026-10-24T00:00:00Z",
    "evidence_revision": 1,
}


def version_binding(**overrides):
    return AssetVersionBinding.model_validate({
        "project_id": DECLARATION["project_id"],
        "asset_id": DECLARATION["asset_id"],
        "asset_version_id": ASSET_VERSION_ID,
        "object_version": {"value": "opaque-object-version-0001"},
        "sha256": "a" * 64,
        "byte_size": 100_000,
        "declared_duration_frames": 360,
        "media_profile_id": ASSET_FORMAT,
        "media_profile_version": "provisional-profile-version",
        **overrides,
    })


def issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def make_asset(declaration: AssetDeclaration, version_id: str = ASSET_VERSION_ID) -> ManagedAsset:
    result = create_managed_asset(declaration, version_id)
    assert result.valid and result.value is not None
    return result.value


def test_valid_declaration_accepts_opaque_ids_and_initializes_uploading_state():
    result = validate_asset_declaration(DECLARATION)

    assert result.valid
    assert result.value is not None
    assert result.value.asset_id == "ast_demo_audio_01"
    asset = make_asset(result.value)
    assert asset.state == "uploading"
    assert asset.asset_version_id == ASSET_VERSION_ID


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("asset_id", "C:/private/audio.wav", "invalid_asset_id"),
        ("asset_id", "https://example.test/audio.wav", "invalid_asset_id"),
        ("asset_id", "ast_short", "invalid_asset_id"),
        ("project_id", "../other-project", "invalid_project_id"),
        ("project_id", "https://example.test", "invalid_project_id"),
        ("tenant_id", "C:\\tenant", "invalid_owner_id"),
        ("owner_id", "https://example.test/user", "invalid_owner_id"),
    ],
)
def test_identifiers_reject_paths_urls_and_malformed_values(field, value, code):
    payload = copy.deepcopy(DECLARATION)
    payload[field] = value

    result = validate_asset_declaration(payload)

    assert not result.valid
    assert code in issue_codes(result)
    assert value not in repr(result.issues)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("declared_duration_frames", True),
        ("declared_duration_frames", 0),
        ("declared_duration_frames", -1),
        ("declared_duration_frames", 86_401),
        ("declared_format", "wav"),
        ("kind", "video"),
        ("original_filename", "../secret.wav"),
        ("original_filename", "x" * 256),
        ("extra", "unexpected"),
        ("lifecycle_state", "ready"),
    ],
)
def test_declaration_is_strict_bounded_and_has_no_caller_state_field(field, value):
    payload = copy.deepcopy(DECLARATION)
    payload[field] = value

    result = validate_asset_declaration(payload)

    assert not result.valid
    assert result.issues
    assert all(value_repr not in repr(result.issues) for value_repr in [str(value)])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("byte_size", True),
        ("byte_size", 0),
        ("byte_size", -5),
        ("duration_frames", True),
        ("duration_frames", -1),
        ("sample_rate", 0),
        ("channels", 0),
        ("sha256", "not-a-digest"),
        ("codec", "x" * 65),
    ],
)
def test_observed_metadata_rejects_wrong_types_and_out_of_bounds_values(field, value):
    payload = copy.deepcopy(OBSERVED)
    payload[field] = value

    result = validate_observed_audio_metadata(payload)

    assert not result.valid
    assert "invalid_asset_metadata" in issue_codes(result)


def test_caller_declaration_and_observed_metadata_are_separate_immutable_models():
    payload = copy.deepcopy(DECLARATION)
    declaration = validate_asset_declaration(payload).value
    observed = validate_observed_audio_metadata(OBSERVED).value

    assert declaration is not None and observed is not None
    assert not hasattr(declaration, "byte_size")
    assert not hasattr(declaration, "sha256")
    assert declaration.declared_duration_frames == 360
    assert observed.duration_frames == 360
    with pytest.raises(ValidationError):
        declaration.asset_id = "ast_other_asset_01"
    with pytest.raises(ValidationError):
        observed.byte_size = 1


def test_audio_contract_constants_match_production_package_schema():
    duration = {
        "id": "ast_demo_audio_01",
        "kind": "audio",
        "format": ASSET_FORMAT,
        "declaredDurationFrames": MAX_DECLARED_DURATION_FRAMES,
    }

    assert ASSET_FORMAT in get_args(ManagedAudioAsset.model_fields["format"].annotation)
    assert ManagedAudioAsset.model_validate(duration).declaredDurationFrames == MAX_DECLARED_DURATION_FRAMES
    duration["declaredDurationFrames"] += 1
    with pytest.raises(ValidationError):
        ManagedAudioAsset.model_validate(duration)
    assert get_args(AssetValidationEvidence.model_fields["profile_id"].annotation) == (PROFILE_ID,)


def test_ready_requires_matching_typed_validation_evidence():
    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None
    asset = make_asset(declaration)
    quarantined = transition_asset(asset, "quarantined")
    validating = transition_asset(quarantined.asset, "validating")

    missing = transition_asset(validating.asset, "ready")
    assert not missing.valid
    assert issue_codes(missing) == {"asset_validation_evidence_required"}

    evidence_result = validate_asset_validation_evidence(EVIDENCE)
    assert evidence_result.valid and evidence_result.value is not None
    ready = transition_asset(validating.asset, "ready", evidence=evidence_result.value)
    assert ready.valid and ready.asset is not None
    assert ready.asset.state == "ready"
    assert ready.asset.validation == evidence_result.value
    assert ready.asset.declaration.asset_id == evidence_result.value.asset_id
    assert ready.asset.declaration.project_id == evidence_result.value.project_id
    assert ready.asset.asset_version_id == evidence_result.value.asset_version_id


def test_managed_record_cannot_be_created_ready_by_setting_state_alone():
    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None

    with pytest.raises(ValueError, match="ready assets require matching validation evidence"):
        ManagedAsset(declaration, ASSET_VERSION_ID, state="ready")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed", {**OBSERVED, "duration_frames": 359}),
        ("observed", {**OBSERVED, "container": "mp3"}),
        ("observed", {**OBSERVED, "codec": "aac"}),
        ("observed", {**OBSERVED, "sample_rate": 44_100}),
        ("observed", {**OBSERVED, "channels": 1}),
    ],
)
def test_ready_rejects_evidence_that_does_not_match_declared_profile(field, value):
    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None
    asset = make_asset(declaration)
    validating = transition_asset(transition_asset(asset, "quarantined").asset, "validating").asset
    evidence_payload = copy.deepcopy(EVIDENCE)
    evidence_payload[field] = value
    evidence = validate_asset_validation_evidence(evidence_payload)
    assert evidence.valid and evidence.value is not None

    result = transition_asset(validating, "ready", evidence=evidence.value)

    assert not result.valid
    assert issue_codes(result) == {"asset_validation_evidence_mismatch"}


@pytest.mark.parametrize(
    ("declaration_change", "version_id"),
    [
        ({"asset_id": "ast_demo_audio_02"}, ASSET_VERSION_ID),
        ({"project_id": "other-project"}, ASSET_VERSION_ID),
        ({}, "ver_demo_audio_0002"),
    ],
)
def test_evidence_cannot_be_reused_for_another_asset_project_or_version(declaration_change, version_id):
    declaration = validate_asset_declaration({**DECLARATION, **declaration_change}).value
    evidence = validate_asset_validation_evidence(EVIDENCE).value
    assert declaration is not None and evidence is not None
    asset = make_asset(declaration, version_id)
    validating = transition_asset(transition_asset(asset, "quarantined").asset, "validating").asset
    before = validating

    result = transition_asset(validating, "ready", evidence=evidence)

    assert not result.valid
    assert issue_codes(result) == {"asset_validation_evidence_mismatch"}
    assert validating is before
    assert validating.state == "validating"
    assert validating.validation is None


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("asset_id", None, "invalid_asset_id"),
        ("asset_id", "https://example.test/a", "invalid_asset_id"),
        ("project_id", None, "invalid_project_id"),
        ("project_id", "../project", "invalid_project_id"),
        ("asset_version_id", None, "invalid_asset_version"),
        ("asset_version_id", "ver_short", "invalid_asset_version"),
    ],
)
def test_evidence_identity_bindings_are_required_and_sanitized(field, value, code):
    payload = copy.deepcopy(EVIDENCE)
    if value is None:
        payload.pop(field)
    else:
        payload[field] = value

    result = validate_asset_validation_evidence(payload)

    assert not result.valid
    assert code in issue_codes(result)
    assert "example.test" not in repr(result.issues)
    assert "../project" not in repr(result.issues)


def test_invalid_asset_version_is_rejected_with_a_stable_sanitized_issue():
    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None

    first = create_managed_asset(declaration, "C:/secret/version")
    second = create_managed_asset(declaration, "C:/secret/version")

    assert not first.valid
    assert first == second
    assert issue_codes(first) == {"invalid_asset_version"}
    assert "C:/secret" not in repr(first.issues)


def test_validation_evidence_requires_a_timezone_aware_timestamp():
    payload = copy.deepcopy(EVIDENCE)
    payload["validated_at"] = "2026-10-24T00:00:00"

    result = validate_asset_validation_evidence(payload)

    assert not result.valid
    assert "invalid_asset_metadata" in issue_codes(result)


def test_validation_evidence_rejects_unsupported_profile():
    payload = copy.deepcopy(EVIDENCE)
    payload["profile_id"] = "unsupported-profile"

    result = validate_asset_validation_evidence(payload)

    assert not result.valid
    assert "invalid_asset_metadata" in issue_codes(result)


def test_allowed_lifecycle_transitions_retry_and_idempotency():
    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None
    initial = make_asset(declaration)
    same = transition_asset(initial, "uploading")
    quarantine = transition_asset(same.asset, "quarantined")
    validating = transition_asset(quarantine.asset, "validating")
    failed = transition_asset(validating.asset, "failed")
    retry = transition_asset(failed.asset, "quarantined")
    validating_again = transition_asset(retry.asset, "validating")
    evidence = validate_asset_validation_evidence(EVIDENCE).value
    ready = transition_asset(validating_again.asset, "ready", evidence=evidence)

    assert same.valid and same.asset is initial
    assert quarantine.valid and quarantine.asset.state == "quarantined"
    assert validating.valid and validating.asset.state == "validating"
    assert failed.valid and failed.asset.state == "failed"
    assert retry.valid and retry.asset.state == "quarantined"
    assert ready.valid and ready.asset.state == "ready"
    assert transition_asset(ready.asset, "ready").asset is ready.asset


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("uploading", "ready"),
        ("ready", "validating"),
        ("rejected", "ready"),
        ("deleted", "uploading"),
        ("deleted", "deleted"),
    ],
)
def test_illegal_and_terminal_lifecycle_transitions_are_rejected(start, target):
    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None
    if start == "ready":
        evidence = validate_asset_validation_evidence(EVIDENCE).value
        assert evidence is not None
        asset = ManagedAsset(declaration, ASSET_VERSION_ID, state=start, validation=evidence)
    else:
        asset = ManagedAsset(declaration, ASSET_VERSION_ID, state=start)
    before = asset

    result = transition_asset(asset, target)

    if start == target == "deleted":
        assert result.valid and result.asset is asset
    else:
        assert not result.valid
        assert issue_codes(result) == {"asset_transition_not_allowed"}
        assert asset is before
        assert result.asset is None
        assert asset.state == start


def test_deletion_and_expiration_paths_are_explicit_and_terminal():
    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None
    initial = make_asset(declaration)
    expired = transition_asset(initial, "expired")
    deletion = transition_asset(expired.asset, "deletion_pending")
    deleted = transition_asset(deletion.asset, "deleted")

    assert expired.valid and expired.asset.state == "expired"
    assert deletion.valid and deletion.asset.state == "deletion_pending"
    assert deleted.valid and deleted.asset.state == "deleted"
    assert not transition_asset(deleted.asset, "expired").valid


def test_invalid_values_have_deterministic_sanitized_issues():
    payload = copy.deepcopy(DECLARATION)
    payload["asset_id"] = "C:/secret/user-audio.wav"
    payload["original_filename"] = "private-sensitive-name.wav"

    first = validate_asset_declaration(payload)
    second = validate_asset_declaration(payload)

    assert first == second
    assert first.issues
    assert "private-sensitive-name.wav" not in repr(first.issues)
    assert "C:/secret" not in repr(first.issues)
    assert all(len(issue.message) <= 100 for issue in first.issues)


def test_validation_does_not_mutate_input():
    payload = copy.deepcopy(DECLARATION)
    before = copy.deepcopy(payload)

    result = validate_asset_declaration(payload)

    assert result.valid
    assert payload == before


def test_version_bound_evidence_is_immutable_and_binds_object_digest_and_observations():
    evidence = VersionBoundValidationEvidence.model_validate(VERSION_BOUND_EVIDENCE)

    assert evidence.project_id == DECLARATION["project_id"]
    assert evidence.asset_id == DECLARATION["asset_id"]
    assert evidence.asset_version_id == ASSET_VERSION_ID
    assert evidence.object_version.value == "opaque-object-version-0001"
    assert evidence.validation_attempt_id == "attempt-2"
    assert evidence.sha256 == "a" * 64
    assert evidence.byte_size == 100_000
    assert evidence.observed.sample_count == 720_000
    assert evidence.observed.duration_frames == 360
    with pytest.raises(ValidationError):
        evidence.evidence_revision = 2
    with pytest.raises(ValidationError):
        evidence.object_version.value = "replacement"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_version_id", "ver_short"),
        ("sha256", "not-a-digest"),
        ("byte_size", True),
        ("validator_identity", ""),
        ("validated_at", "2026-10-24T00:00:00"),
    ],
)
def test_version_bound_evidence_rejects_invalid_binding_and_metadata(field, value):
    payload = copy.deepcopy(VERSION_BOUND_EVIDENCE)
    payload[field] = value
    with pytest.raises(ValidationError):
        VersionBoundValidationEvidence.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "other-project"),
        ("asset_id", "ast_other_asset_01"),
        ("asset_version_id", "ver_other_asset_0002"),
        ("object_version", {"value": "opaque-object-version-0002"}),
        ("sha256", "b" * 64),
        ("byte_size", 100_001),
        ("declared_duration_frames", 359),
        ("media_profile_version", "other-profile-version"),
    ],
)
def test_version_bound_evidence_comparison_rejects_every_binding_mismatch(field, value):
    evidence = VersionBoundValidationEvidence.model_validate(VERSION_BOUND_EVIDENCE)
    binding = version_binding(**{field: value})

    result = compare_version_bound_evidence(evidence, binding)

    assert not result.matches
    assert result.issues
    assert all(issue.code == "evidence_binding_mismatch" for issue in result.issues)
    assert "other-project" not in repr(result.issues)


def test_version_bound_evidence_requires_existing_supported_media_profile():
    payload = copy.deepcopy(VERSION_BOUND_EVIDENCE)
    payload["media_profile_id"] = "invented-profile"
    with pytest.raises(ValidationError):
        VersionBoundValidationEvidence.model_validate(payload)


def test_evidence_comparison_revalidates_copied_models_and_returns_safe_issue():
    evidence = VersionBoundValidationEvidence.model_validate(VERSION_BOUND_EVIDENCE).model_copy(
        update={"byte_size": []},
    )
    result = compare_version_bound_evidence(evidence, version_binding())
    assert not result.matches
    assert {issue.code for issue in result.issues} == {"invalid_evidence_binding"}
    assert "byte_size" not in repr(result.issues)


def test_observed_wav_properties_require_exact_sample_frame_alignment():
    valid = ObservedWavProperties.model_validate(VERSION_BOUND_EVIDENCE["observed"])
    assert valid.sample_count // 2_000 == valid.duration_frames
    for sample_count in (719_999, 720_001):
        payload = {**VERSION_BOUND_EVIDENCE["observed"], "sample_count": sample_count}
        with pytest.raises(ValidationError):
            ObservedWavProperties.model_validate(payload)


def test_lifecycle_transition_command_rejects_stale_attempt_revision_and_version():
    current = AssetLifecycleSnapshot(
        project_id="sample-northstar", asset_id=DECLARATION["asset_id"],
        asset_version_id=ASSET_VERSION_ID, state="validating", state_revision=7,
        validation_attempt_id="attempt-2",
    )
    command = AssetTransitionCommand(
        project_id=current.project_id, asset_id=current.asset_id,
        asset_version_id=current.asset_version_id, expected_state="validating",
        expected_state_revision=7, expected_validation_attempt_id="attempt-1",
        target_state="ready", evidence_revision=1,
    )
    evidence_payload = copy.deepcopy(VERSION_BOUND_EVIDENCE)
    evidence = VersionBoundValidationEvidence.model_validate(evidence_payload)
    binding = version_binding()

    stale_attempt = check_asset_transition_preconditions(current, command)
    stale_worker_result = check_asset_transition_preconditions(
        current,
        command.model_copy(update={"expected_validation_attempt_id": "attempt-2"}),
        validation_result_attempt_id="attempt-1",
        validation_evidence=evidence,
        authoritative_binding=binding,
    )
    stale_revision = check_asset_transition_preconditions(
        current, command.model_copy(update={"expected_validation_attempt_id": "attempt-2", "expected_state_revision": 6}),
    )
    stale_version = check_asset_transition_preconditions(
        current, command.model_copy(update={"expected_validation_attempt_id": "attempt-2", "asset_version_id": "ver_other_version_0002"}),
    )
    accepted = check_asset_transition_preconditions(
        current, command.model_copy(update={"expected_validation_attempt_id": "attempt-2"}),
        validation_result_attempt_id="attempt-2", validation_evidence=evidence,
        authoritative_binding=binding,
    )

    assert not stale_attempt.accepted
    assert {issue.code for issue in stale_attempt.issues} == {"stale_asset_transition"}
    assert not stale_worker_result.accepted
    assert {issue.code for issue in stale_worker_result.issues} == {"validation_attempt_mismatch"}
    assert not stale_revision.accepted
    assert {issue.code for issue in stale_revision.issues} == {"stale_asset_transition"}
    assert not stale_version.accepted
    assert {issue.code for issue in stale_version.issues} == {"stale_asset_transition"}
    assert accepted.accepted and not accepted.issues


@pytest.mark.parametrize(
    ("copy_target", "copy_value"),
    [
        ("target_state", []),
        ("expected_state_revision", []),
        ("project_id", []),
        ("asset_version_id", {"bad": "id"}),
        ("expected_validation_attempt_id", []),
    ],
)
def test_transition_preconditions_revalidate_model_copy_updates(copy_target, copy_value):
    current = AssetLifecycleSnapshot(
        project_id="sample-northstar", asset_id="ast_demo_audio_01",
        asset_version_id=ASSET_VERSION_ID, state="validating", state_revision=7,
        validation_attempt_id="attempt-2",
    )
    command = AssetTransitionCommand(
        project_id=current.project_id, asset_id=current.asset_id,
        asset_version_id=current.asset_version_id, expected_state="validating",
        expected_state_revision=7, expected_validation_attempt_id="attempt-2",
        target_state="ready", evidence_revision=1,
    )
    malformed = command.model_copy(update={copy_target: copy_value})

    result = check_asset_transition_preconditions(current, malformed)

    assert not result.accepted
    assert {issue.code for issue in result.issues} == {"invalid_transition_precondition"}
    assert "bad" not in repr(result.issues)


@pytest.mark.parametrize(
    ("copy_target", "copy_value"),
    [
        ("state", []),
        ("state_revision", []),
        ("project_id", []),
        ("asset_version_id", {"bad": "id"}),
        ("validation_attempt_id", []),
    ],
)
def test_transition_preconditions_revalidate_malformed_current_snapshot(copy_target, copy_value):
    current = AssetLifecycleSnapshot(
        project_id="sample-northstar", asset_id="ast_demo_audio_01",
        asset_version_id=ASSET_VERSION_ID, state="validating", state_revision=7,
        validation_attempt_id="attempt-2",
    )
    command = AssetTransitionCommand(
        project_id=current.project_id, asset_id=current.asset_id,
        asset_version_id=current.asset_version_id, expected_state="validating",
        expected_state_revision=7, expected_validation_attempt_id="attempt-2",
        target_state="failed",
    )
    malformed = current.model_copy(update={copy_target: copy_value})

    result = check_asset_transition_preconditions(malformed, command)

    assert not result.accepted
    assert {issue.code for issue in result.issues} == {"invalid_transition_precondition"}


def test_ready_preconditions_reject_missing_or_mismatched_evidence_and_attempt():
    current = AssetLifecycleSnapshot(
        project_id="sample-northstar", asset_id="ast_demo_audio_01",
        asset_version_id=ASSET_VERSION_ID, state="validating", state_revision=7,
        validation_attempt_id="attempt-2",
    )
    command = AssetTransitionCommand(
        project_id=current.project_id, asset_id=current.asset_id,
        asset_version_id=current.asset_version_id, expected_state="validating",
        expected_state_revision=7, expected_validation_attempt_id="attempt-2",
        target_state="ready", evidence_revision=1,
    )
    evidence = VersionBoundValidationEvidence.model_validate(VERSION_BOUND_EVIDENCE)
    binding = version_binding()

    missing = check_asset_transition_preconditions(current, command, validation_result_attempt_id="attempt-2")
    wrong_evidence_attempt = evidence.model_copy(update={"validation_attempt_id": "attempt-1"})
    mismatched_evidence = check_asset_transition_preconditions(
        current, command, validation_result_attempt_id="attempt-2",
        validation_evidence=wrong_evidence_attempt, authoritative_binding=binding,
    )
    missing_attempt = check_asset_transition_preconditions(
        current, command, validation_result_attempt_id=None, validation_evidence=evidence,
        authoritative_binding=binding,
    )

    assert not missing.accepted
    assert {issue.code for issue in missing.issues} == {"asset_validation_evidence_required"}
    assert not mismatched_evidence.accepted
    assert {issue.code for issue in mismatched_evidence.issues} == {"asset_validation_evidence_mismatch"}
    assert not missing_attempt.accepted
    assert {issue.code for issue in missing_attempt.issues} == {"validation_attempt_mismatch"}


def test_lease_contract_pins_complete_immutable_versions_and_rejects_duplicate_assets():
    pin = {
        "asset_id": "ast_demo_audio_01", "asset_version_id": ASSET_VERSION_ID,
        "object_version": {"value": "opaque-object-version-0001"}, "sha256": "a" * 64,
        "profile_id": PROFILE_ID, "declared_duration_frames": 360,
    }
    request = AssetLeaseRequest(
        project_id="sample-northstar", job_id="job-demo-0001", assets=(pin,),
    )
    lease = AssetLeaseRecord(
        lease_id="lease-demo-0001", project_id=request.project_id, job_id=request.job_id,
        assets=request.assets, created_at="2026-10-24T00:00:00Z",
        expires_at="2026-10-24T00:05:00Z", lease_revision=1, state="active",
    )
    assert lease.assets[0].asset_version_id == ASSET_VERSION_ID
    assert lease.assets[0].object_version.value == "opaque-object-version-0001"
    with pytest.raises(ValidationError):
        request.assets[0].asset_version_id = "ver_replacement_0002"
    with pytest.raises(ValidationError):
        AssetLeaseRequest(project_id="sample-northstar", job_id="job-1", assets=[pin])
    with pytest.raises(ValidationError):
        AssetLeaseRequest(project_id="sample-northstar", job_id="job-1", assets=(pin, pin))
    with pytest.raises(ValidationError):
        AssetLeaseTransitionCommand(
            lease_id="lease-demo-0001", expected_lease_revision=1,
            expected_state="released", target_state="active",
            target_expiry="2026-10-24T00:10:00Z",
        )
    release = AssetLeaseTransitionCommand(
        lease_id=lease.lease_id, expected_lease_revision=1,
        expected_state="active", target_state="released",
    )
    assert check_asset_lease_transition_preconditions(lease, release).accepted
    stale = check_asset_lease_transition_preconditions(
        lease, release.model_copy(update={"expected_lease_revision": 2}),
    )
    malformed = check_asset_lease_transition_preconditions(
        lease, release.model_copy(update={"target_state": []}),
    )
    wrong_lease = check_asset_lease_transition_preconditions(
        lease, release.model_copy(update={"lease_id": "lease-other"}),
    )
    assert not stale.accepted and {issue.code for issue in stale.issues} == {"stale_asset_lease"}
    assert not malformed.accepted and {issue.code for issue in malformed.issues} == {"invalid_lease_transition_precondition"}
    assert not wrong_lease.accepted and {issue.code for issue in wrong_lease.issues} == {"stale_asset_lease"}


def test_active_lease_state_alone_does_not_establish_validity():
    pin = LeaseAssetPin.model_validate({
        "asset_id": "ast_demo_audio_01", "asset_version_id": ASSET_VERSION_ID,
        "object_version": {"value": "opaque-object-version-0001"}, "sha256": "a" * 64,
        "profile_id": PROFILE_ID, "declared_duration_frames": 360,
    })
    expired_active = AssetLeaseRecord(
        lease_id="lease-demo-0001", project_id="sample-northstar", job_id="job-demo-0001",
        assets=(pin,), created_at="2026-10-24T00:00:00Z", expires_at="2026-10-24T00:05:00Z",
        lease_revision=1, state="active",
    )
    now = datetime.fromisoformat("2026-10-24T00:06:00+00:00")

    assert expired_active.state == "active"
    assert not asset_lease_is_valid_at(expired_active, now)
    assert asset_lease_is_valid_at(expired_active, datetime.fromisoformat("2026-10-24T00:04:00+00:00"))
    assert not asset_lease_is_valid_at(expired_active, datetime.fromisoformat("2026-10-24T00:04:00"))
    assert not asset_lease_is_valid_at(
        expired_active, datetime.fromisoformat("2026-10-23T23:59:00+00:00"),
    )


def test_contract_is_pure_and_invokes_no_io_or_external_operations(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected side effect")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)

    declaration = validate_asset_declaration(DECLARATION).value
    assert declaration is not None
    asset = make_asset(declaration)
    assert transition_asset(asset, "quarantined").valid
    assert validate_observed_audio_metadata(OBSERVED).valid
