from __future__ import annotations

import builtins
import copy
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from dataclasses import FrozenInstanceError, replace

import pytest

from adforge_renderer.production_package import (
    CONTRACT_VERSION_V2,
    ProductionPackageV2Validation,
    ProductionPackageValidation,
    validate_production_package,
    validate_production_package_v2,
)
from adforge_renderer import render_plan as render_plan_module
from adforge_renderer.render_plan import (
    CompilationDiagnostic,
    RenderPlanCompilation,
    compile_render_plan,
    compile_versioned_render_plan,
)


FIXTURES = Path(__file__).parent / "fixtures"
VALID = json.loads((FIXTURES / "production-package-valid.json").read_text(encoding="utf-8"))
VALID_V2 = json.loads((FIXTURES / "production-package-v2-valid.json").read_text(encoding="utf-8"))


def _validated(payload: object = VALID):
    return validate_production_package(payload)


def test_valid_package_compiles_deterministically_and_preserves_ordered_half_open_timeline():
    validation = _validated()

    first = compile_render_plan(validation)
    second = compile_render_plan(validation)

    assert first.succeeded
    assert first == second
    plan = first.plan
    assert plan is not None
    assert [(scene.scene_id, scene.order) for scene in plan.scenes] == [("opening", 1), ("closing", 2)]
    assert [(scene.start_frame, scene.end_frame) for scene in plan.scenes] == [(0, 180), (180, 360)]
    assert all(scene.end_frame - scene.start_frame == scene.duration_frames for scene in plan.scenes)
    assert sum(scene.duration_frames for scene in plan.scenes) == 360
    assert plan.scenes[0].start_frame == 0
    assert plan.scenes[-1].end_frame == 360
    assert (plan.profile.width, plan.profile.height, plan.profile.frame_rate) == (1080, 1920, 24)
    assert (plan.profile.container, plan.profile.video_codec, plan.profile.pixel_format) == (
        "mp4", "h264", "yuv420p"
    )
    assert (plan.profile.audio_codec, plan.profile.audio_sample_rate, plan.profile.audio_channels) == (
        "aac-lc", 48_000, 2
    )


def test_visual_operations_preserve_claim_classification_and_exact_fact_reference():
    payload = copy.deepcopy(VALID)
    payload["brief"]["targetAudience"] = {
        "kind": "claim", "text": "Northstar Coffee", "factId": "brand"
    }
    result = compile_render_plan(_validated(payload))

    assert result.succeeded
    assert result.plan is not None
    assert result.plan.brief.target_audience.classification == "claim"
    assert result.plan.brief.target_audience.text == "Northstar Coffee"
    assert result.plan.brief.target_audience.fact_id == "brand"
    operation = result.plan.scenes[0].operations[0]
    assert operation.operation == "text"
    assert operation.content.classification == "claim"
    assert operation.content.text == "Northstar Coffee"
    assert operation.content.fact_id == "brand"
    assert result.plan.scenes[0].title.classification == "creative"


def test_audio_frames_source_offsets_and_opaque_asset_id_are_preserved():
    payload = copy.deepcopy(VALID)
    payload["assets"][0]["declaredDurationFrames"] = 400
    payload["audioSegments"][0]["sourceStartFrame"] = 17
    payload["audioSegments"].append({
        "id": "voice-over",
        "kind": "narration",
        "assetId": "ast_demo_audio_01",
        "sceneId": "opening",
        "startFrame": 0,
        "endFrame": 24,
        "sourceStartFrame": 31,
        "transcript": {"kind": "creative", "text": "An illustrative spoken line"},
    })

    result = compile_render_plan(_validated(payload))

    assert result.succeeded
    assert result.plan is not None
    music, narration = result.plan.audio_segments
    assert (music.role, music.asset_id, music.start_frame, music.end_frame) == (
        "music", "ast_demo_audio_01", 0, 360
    )
    assert (music.scene_relative_start_frame, music.scene_relative_end_frame) == (None, None)
    assert (music.source_start_frame, music.source_end_frame) == (17, 377)
    assert (narration.role, narration.scene_id, narration.start_frame, narration.end_frame) == (
        "narration", "opening", 0, 24
    )
    assert (narration.scene_relative_start_frame, narration.scene_relative_end_frame) == (0, 24)
    assert (narration.source_start_frame, narration.source_end_frame) == (31, 55)
    assert narration.transcript is not None
    assert narration.transcript.classification == "creative"


def test_v2_validation_is_not_accepted_by_legacy_render_plan_compiler():
    validation = validate_production_package(VALID_V2)

    assert validation.valid
    result = compile_render_plan(validation)  # type: ignore[arg-type]

    assert result.plan is None
    assert result.diagnostics[0].code == "invalid_validation_result"


def test_legacy_compiler_rejects_v2_package_inside_caller_constructed_v1_result():
    v2_validation = validate_production_package(VALID_V2)
    assert v2_validation.valid
    assert v2_validation.package is not None
    forged_v1_result = ProductionPackageValidation(
        valid=True,
        issues=(),
        package=v2_validation.package,
        correlation_id=v2_validation.correlation_id,
        contract_version="spotloom.production-package.v1",
    )

    result = compile_render_plan(forged_v1_result)

    assert result.plan is None
    assert result.diagnostics == (
        CompilationDiagnostic(
            "unsupported_contract_version",
            "contractVersion",
            "The legacy render-plan compiler accepts only explicitly validated v1 packages.",
        ),
    )


def test_v2_compilation_preserves_project_asset_versions_and_segment_binding():
    validation = validate_production_package(VALID_V2)

    result = compile_versioned_render_plan(validation)  # type: ignore[arg-type]

    assert result.succeeded
    assert result.plan is not None
    plan = result.plan
    assert plan.project_id == "sample-northstar"
    assert [(asset.asset_id, asset.asset_version_id) for asset in plan.assets] == [
        ("ast_demo_audio_01", "ver_demo_audio_0001"),
    ]
    assert len(plan.audio_segments) == 1
    assert (plan.audio_segments[0].asset_id, plan.audio_segments[0].asset_version_id) == (
        plan.assets[0].asset_id, plan.assets[0].asset_version_id,
    )
    assert plan.scenes == compile_render_plan(_validated()).plan.scenes


def test_v2_compilation_maps_multiple_segments_to_their_declared_pins():
    payload = copy.deepcopy(VALID_V2)
    payload["assets"].append({
        "id": "ast_demo_audio_02",
        "kind": "audio",
        "format": "wav-pcm-s16le-48000-stereo",
        "declaredDurationFrames": 360,
        "assetVersionId": "ver_demo_audio_0002",
    })
    payload["audioSegments"] = [
        {**payload["audioSegments"][0], "id": "music-first", "endFrame": 180},
        {
            "id": "music-second", "kind": "music", "assetId": "ast_demo_audio_02",
            "sceneId": None, "startFrame": 180, "endFrame": 360,
            "sourceStartFrame": 0, "transcript": None,
        },
    ]

    result = compile_versioned_render_plan(validate_production_package(  # type: ignore[arg-type]
        payload
    ))

    assert result.succeeded
    assert result.plan is not None
    assert [(asset.asset_id, asset.asset_version_id) for asset in result.plan.assets] == [
        ("ast_demo_audio_01", "ver_demo_audio_0001"),
        ("ast_demo_audio_02", "ver_demo_audio_0002"),
    ]
    assert [(item.asset_id, item.asset_version_id) for item in result.plan.audio_segments] == [
        ("ast_demo_audio_01", "ver_demo_audio_0001"),
        ("ast_demo_audio_02", "ver_demo_audio_0002"),
    ]


def test_v2_compilation_rejects_invalid_and_mutated_asset_references_without_partial_plan():
    invalid = copy.deepcopy(VALID_V2)
    invalid["audioSegments"][0]["assetId"] = "ast_missing_0001"
    invalid_result = compile_versioned_render_plan(validate_production_package(  # type: ignore[arg-type]
        invalid
    ))
    assert invalid_result.plan is None
    assert any(issue.code == "asset_reference_missing" for issue in invalid_result.package_issues)

    validated = validate_production_package_v2(copy.deepcopy(VALID_V2))
    assert validated.package is not None
    validated.package.assets[0] = validated.package.assets[0].model_copy(
        update={"assetVersionId": "bad-version"}
    )
    mutated_result = compile_versioned_render_plan(validated)
    assert mutated_result.plan is None
    assert any(issue.code == "package_schema_invalid" for issue in mutated_result.package_issues)


def test_v2_compiler_rejects_failed_wrong_type_and_wrong_version_results():
    failed = validate_production_package_v2({"contractVersion": CONTRACT_VERSION_V2})
    v1_validation = validate_production_package(VALID)
    wrong_type = compile_versioned_render_plan(ProductionPackageValidation(  # type: ignore[arg-type]
        valid=True, issues=(), contract_version=CONTRACT_VERSION_V2,
    ))
    failed_result = compile_versioned_render_plan(failed)
    v1_result = compile_versioned_render_plan(v1_validation)  # type: ignore[arg-type]
    wrong_version = compile_versioned_render_plan(replace(
        validate_production_package_v2(copy.deepcopy(VALID_V2)),
        contract_version="spotloom.production-package.v1",
    ))

    assert wrong_type.plan is None
    assert [item.code for item in wrong_type.diagnostics] == ["invalid_validation_result"]
    assert failed_result.plan is None
    assert failed_result.package_issues
    assert v1_result.plan is None
    assert [item.code for item in v1_result.diagnostics] == ["invalid_validation_result"]
    assert wrong_version.plan is None
    assert [item.code for item in wrong_version.diagnostics] == ["unsupported_contract_version"]


def test_v2_compiled_plan_and_nested_version_pins_are_immutable():
    result = compile_versioned_render_plan(validate_production_package_v2(copy.deepcopy(VALID_V2)))
    assert result.plan is not None
    plan = result.plan
    original = copy.deepcopy(plan)

    with pytest.raises(FrozenInstanceError):
        plan.project_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.assets[0].asset_version_id = "ver_changed_001"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.audio_segments[0].asset_version_id = "ver_changed_001"  # type: ignore[misc]
    with pytest.raises(TypeError):
        plan.assets[0] = plan.assets[0]  # type: ignore[index]
    with pytest.raises(AttributeError):
        plan.scenes.append(plan.scenes[0])  # type: ignore[attr-defined]

    assert plan == original


def test_v2_compiler_diagnostics_are_deterministic_sanitized_and_have_no_partial_plan(monkeypatch):
    payload = copy.deepcopy(VALID_V2)
    secret_text = "PRIVATE_V2_SENTINEL_DO_NOT_EXPOSE"
    payload["brief"]["targetAudience"]["text"] = secret_text
    validation = validate_production_package_v2(payload)
    assert validation.valid

    def multiple_diagnostics(_element: object, path: str):
        if path == "scenes.0.elements.0":
            return None, CompilationDiagnostic(
                "unsupported_visual_instruction", "scenes.1.elements.0",
                "The visual instruction is not supported by this render-plan compiler.",
            )
        return None, CompilationDiagnostic(
            "unsupported_text_classification", "scenes.0.elements.0",
            "The text classification is not supported by this render-plan compiler.",
        )

    monkeypatch.setattr(render_plan_module, "_compile_visual", multiple_diagnostics)
    first = compile_versioned_render_plan(validation)
    second = compile_versioned_render_plan(validation)

    assert first == second
    assert first.plan is None
    assert [(item.path, item.code) for item in first.diagnostics] == [
        ("scenes.0.elements.0", "unsupported_text_classification"),
        ("scenes.1.elements.0", "unsupported_visual_instruction"),
    ]
    assert secret_text not in repr(first)


@pytest.mark.parametrize("invalid_change", ["overlap", "outside_scene"])
def test_existing_audio_overlap_and_scene_boundary_rules_remain_package_validation_errors(invalid_change):
    payload = copy.deepcopy(VALID)
    payload["audioSegments"].append({
        "id": "voice-over",
        "kind": "narration",
        "assetId": "ast_demo_audio_01",
        "sceneId": "opening",
        "startFrame": 0 if invalid_change == "overlap" else 179,
        "endFrame": 24 if invalid_change == "overlap" else 181,
        "sourceStartFrame": 0,
        "transcript": {"kind": "creative", "text": "An illustrative spoken line"},
    })
    if invalid_change == "overlap":
        payload["audioSegments"].append({
            "id": "voice-over-two",
            "kind": "narration",
            "assetId": "ast_demo_audio_01",
            "sceneId": "opening",
            "startFrame": 12,
            "endFrame": 36,
            "sourceStartFrame": 24,
            "transcript": {"kind": "creative", "text": "A second illustrative line"},
        })

    validation = _validated(payload)
    result = compile_render_plan(validation)

    assert not validation.valid
    assert not result.succeeded
    assert result.plan is None
    expected = "narration_overlap" if invalid_change == "overlap" else "narration_outside_scene"
    assert expected in {issue.code for issue in result.package_issues}
    assert not result.diagnostics


def test_invalid_frame_duration_is_rejected_before_compilation_without_partial_plan():
    payload = copy.deepcopy(VALID)
    payload["scenes"][0]["durationFrames"] = 1.5
    validation = _validated(payload)

    result = compile_render_plan(validation)

    assert not validation.valid
    assert result.plan is None
    assert result.package_issues
    assert not result.diagnostics


def test_schema_rejects_unsupported_visual_type_before_compiler():
    payload = copy.deepcopy(VALID)
    payload["scenes"][0]["elements"][0] = {
        "type": "image", "id": "photo", "assetId": "ast_photo_12345678"
    }
    validation = _validated(payload)

    result = compile_render_plan(validation)

    assert not validation.valid
    assert result.plan is None
    assert any(issue.code == "package_schema_invalid" for issue in result.package_issues)
    assert not result.diagnostics


def test_failed_compilation_never_returns_a_partial_plan_and_diagnostics_are_stable():
    first = compile_render_plan(object())  # type: ignore[arg-type]
    second = compile_render_plan(object())  # type: ignore[arg-type]

    assert first == second
    assert first.plan is None
    assert [issue.code for issue in first.diagnostics] == ["invalid_validation_result"]


def test_inconsistent_or_mutated_validation_results_fail_without_a_plan():
    inconsistent = compile_render_plan(ProductionPackageValidation(valid=True, issues=()))
    missing_issues = compile_render_plan(ProductionPackageValidation(valid=False, issues=()))
    changed = _validated()
    assert changed.package is not None
    changed.package.scenes.reverse()

    reordered = compile_render_plan(changed)

    assert isinstance(inconsistent, RenderPlanCompilation)
    assert inconsistent.plan is None
    assert [item.code for item in inconsistent.diagnostics] == ["inconsistent_validation_result"]
    assert missing_issues.plan is None
    assert [item.code for item in missing_issues.diagnostics] == ["inconsistent_validation_result"]
    assert reordered.plan is None
    assert "scene_order_invalid" in {item.code for item in reordered.package_issues}


def test_compiler_does_not_mutate_the_validated_package():
    validation = _validated()
    assert validation.package is not None
    before = validation.package.model_dump(mode="python")

    result = compile_render_plan(validation)

    assert result.succeeded
    assert validation.package.model_dump(mode="python") == before


def test_compiled_plan_is_deeply_immutable():
    result = compile_render_plan(_validated())
    assert result.plan is not None
    plan = result.plan
    original = copy.deepcopy(plan)
    text_operation = plan.scenes[0].operations[0]
    audio_segment = plan.audio_segments[0]

    with pytest.raises(FrozenInstanceError):
        plan.profile = plan.profile  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.scenes[0].start_frame = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        text_operation.element_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        audio_segment.asset_id = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        plan.scenes.append(plan.scenes[0])  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        plan.audio_segments[0] = audio_segment  # type: ignore[index]

    assert plan == original


def test_multiple_compiler_diagnostics_are_sorted_stable_and_sanitized(monkeypatch):
    payload = copy.deepcopy(VALID)
    secret_text = "PRIVATE_SENTINEL_DO_NOT_EXPOSE"
    payload["brief"]["targetAudience"]["text"] = secret_text
    validation = _validated(payload)
    assert validation.valid

    def multiple_diagnostics(_element: object, path: str):
        # Every currently valid package is fully representable, and package
        # revalidation rejects unsupported data before compilation. Inject two
        # independent visual-compiler failures here to exercise the aggregation
        # and sorting seam without weakening or fabricating the package schema.
        if path == "scenes.0.elements.0":
            return None, CompilationDiagnostic(
                "unsupported_visual_instruction",
                "scenes.1.elements.0",
                "The visual instruction is not supported by this render-plan compiler.",
            )
        return None, CompilationDiagnostic(
            "unsupported_text_classification",
            "scenes.0.elements.0",
            "The text classification is not supported by this render-plan compiler.",
        )

    monkeypatch.setattr(render_plan_module, "_compile_visual", multiple_diagnostics)
    first = compile_render_plan(validation)
    second = compile_render_plan(validation)

    assert first == second
    assert first.plan is None
    assert [(item.path, item.code) for item in first.diagnostics] == [
        ("scenes.0.elements.0", "unsupported_text_classification"),
        ("scenes.1.elements.0", "unsupported_visual_instruction"),
    ]
    assert [item.code for item in first.diagnostics] == [
        "unsupported_text_classification",
        "unsupported_visual_instruction",
    ]
    assert all(secret_text not in item.message for item in first.diagnostics)
    assert secret_text not in repr(first)


def test_compiler_has_no_filesystem_network_subprocess_database_or_renderer_side_effects(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("render-plan compilation attempted a forbidden side effect")

    from adforge_renderer import renderer

    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(renderer, "render_ad", forbidden)

    result = compile_render_plan(_validated())

    assert result.succeeded
    assert result.plan is not None
    assert result.plan.audio_segments[0].asset_id == "ast_demo_audio_01"
