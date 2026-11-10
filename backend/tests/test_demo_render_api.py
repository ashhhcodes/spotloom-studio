from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from adforge_renderer import api

VALID_SCENES = [
    {"scene_id": "northstar-scene-opening", "title": "Set the mood", "on_screen_text": "A moment to pause", "duration_seconds": 4, "transition": "cut", "role": "hook"},
    {"scene_id": "northstar-scene-middle", "title": "Make room", "on_screen_text": "Make space for good.", "duration_seconds": 6, "transition": "cut", "role": "benefit"},
    {"scene_id": "northstar-scene-close", "title": "Close simply", "on_screen_text": "Northstar Coffee · Learn more", "duration_seconds": 5, "transition": "fade", "role": "cta"},
]

VALID_RENDER_REQUEST = {
    "business_name": "Northstar Coffee",
    "product_or_service": "Small-batch roasted coffee",
    "selling_points": ["A moment to pause", "Make space for good."],
    "cta": "Learn more",
    "scenes": VALID_SCENES,
}


def test_demo_render_rejects_invalid_input_without_invoking_renderer(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid input must not invoke the renderer")

    monkeypatch.setattr(api, "render_ad", forbidden)
    with TestClient(api.app) as client:
        response = client.post("/render/demo", json={**VALID_RENDER_REQUEST, "unexpected": "field"})

    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_render_input",
        "detail": "Use 1–6 unique scenes, supported roles, #RRGGBB brand colors, durations of 1–60 seconds, supported transitions, a cut on the first scene, and a rendered timeline no longer than 30 seconds.",
    }


def test_demo_render_bounds_request_body():
    with TestClient(api.app) as client:
        response = client.post(
            "/render/demo",
            content=b" " * (api.MAX_PACKAGE_BYTES + 1),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["error"] == "payload_too_large"


def test_demo_render_passes_every_scene_to_renderer_in_submitted_order(monkeypatch):
    submitted = [*VALID_SCENES, {
        "scene_id": "new-scene-id", "title": "Added scene", "on_screen_text": "A newly added message",
        "duration_seconds": 3, "transition": "cut", "role": "proof",
    }]
    observed = []

    def capture(_business, output_path, *, storyboard_scenes):
        observed.extend((scene.scene_id, scene.duration_seconds, scene.transition, scene.role) for scene in storyboard_scenes)
        output_path.write_bytes(b"fake mp4 for response test")
        return {}

    monkeypatch.setattr(api, "render_ad", capture)
    with TestClient(api.app) as client:
        response = client.post("/render/demo", json={**VALID_RENDER_REQUEST, "scenes": submitted})

    assert response.status_code == 200
    assert observed == [
        (scene["scene_id"], scene["duration_seconds"], scene["transition"], scene["role"])
        for scene in submitted
    ]


def test_demo_render_uses_default_palette_for_older_requests(monkeypatch):
    observed = []

    def capture(business, output_path, *, storyboard_scenes):
        observed.extend(business.brand_colors)
        output_path.write_bytes(b"fake mp4 for response test")
        return {}

    monkeypatch.setattr(api, "render_ad", capture)
    with TestClient(api.app) as client:
        response = client.post("/render/demo", json=VALID_RENDER_REQUEST)

    assert response.status_code == 200
    assert observed == ["#D98B45", "#F5EFE7"]


def test_demo_render_passes_explicit_brand_colors_to_renderer(monkeypatch):
    observed = []

    def capture(business, output_path, *, storyboard_scenes):
        observed.extend(business.brand_colors)
        output_path.write_bytes(b"fake mp4 for response test")
        return {}

    monkeypatch.setattr(api, "render_ad", capture)
    with TestClient(api.app) as client:
        response = client.post("/render/demo", json={
            **VALID_RENDER_REQUEST, "primary_color": "#176B87", "accent_color": "#E8B84D",
        })

    assert response.status_code == 200
    assert observed == ["#176B87", "#E8B84D"]


@pytest.mark.parametrize("field,value", [
    ("primary_color", "blue"),
    ("primary_color", "#12345"),
    ("accent_color", "#12345678"),
    ("accent_color", 123),
])
def test_demo_render_rejects_invalid_brand_colors(field, value, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid color must not invoke the renderer")

    monkeypatch.setattr(api, "render_ad", forbidden)
    with TestClient(api.app) as client:
        response = client.post("/render/demo", json={**VALID_RENDER_REQUEST, field: value})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_render_input"


@pytest.mark.parametrize("scenes", [
    [],
    [*VALID_SCENES] + [{"scene_id": f"scene-{index}", "title": "Title", "on_screen_text": "Text"}
                       for index in range(4, 8)],
    [VALID_SCENES[0], VALID_SCENES[0]],
    [{"scene_id": "scene-blank", "title": " ", "on_screen_text": "Text"}],
    [{"scene_id": "scene-invalid id", "title": "Title", "on_screen_text": "Text"}],
    [{"scene_id": 12, "title": "Title", "on_screen_text": "Text"}],
    [{"scene_id": "scene-long-title", "title": "T" * 81, "on_screen_text": "Text"}],
    [{"scene_id": "scene-long-copy", "title": "Title", "on_screen_text": "T" * 181}],
    [{**VALID_SCENES[0], "duration_seconds": 0}],
    [{**VALID_SCENES[0], "duration_seconds": 61}],
    [{**VALID_SCENES[0], "duration_seconds": 1.5}],
    [{**VALID_SCENES[0], "transition": "wipe"}],
    [{**VALID_SCENES[0], "transition": "fade"}],
    [{**VALID_SCENES[0], "role": "unsupported"}],
    [{**VALID_SCENES[0], "role": None}],
    [{**VALID_SCENES[0], "duration_seconds": 11, "transition": "cut"},
     {**VALID_SCENES[1], "duration_seconds": 11, "transition": "cut"},
     {**VALID_SCENES[2], "duration_seconds": 11, "transition": "cut"}],
])
def test_demo_render_rejects_invalid_scene_sequences(monkeypatch, scenes):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid storyboard must not invoke the renderer")

    monkeypatch.setattr(api, "render_ad", forbidden)
    with TestClient(api.app) as client:
        response = client.post("/render/demo", json={**VALID_RENDER_REQUEST, "scenes": scenes})

    assert response.status_code == 422
    assert response.json()["error"] == "invalid_render_input"


def test_demo_render_failure_returns_sanitized_error(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("private ffmpeg path and input data")

    monkeypatch.setattr(api, "render_ad", fail)
    with TestClient(api.app) as client:
        response = client.post("/render/demo", json=VALID_RENDER_REQUEST)

    assert response.status_code == 500
    assert response.json()["error"] == "demo_render_failed"
    assert "private ffmpeg path" not in response.text


def test_demo_render_streams_real_mp4_from_existing_renderer():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        import pytest

        pytest.skip("FFmpeg and FFprobe are required for the demo-render integration test")

    with TestClient(api.app) as client:
        response = client.post("/render/demo", json={
            **VALID_RENDER_REQUEST,
            "scenes": [*VALID_SCENES, {
                "scene_id": "new-scene-id", "title": "Added scene", "on_screen_text": "A newly added message",
                "duration_seconds": 3, "transition": "cut", "role": "proof",
            }],
        })

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("video/mp4")
    assert "spotloom-illustrative-draft.mp4" in response.headers["content-disposition"]
    assert len(response.content) > 1024
    assert response.content[4:8] == b"ftyp"
