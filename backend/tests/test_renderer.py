from pathlib import Path
import re
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from adforge_renderer.models import BusinessInput, StoryboardRenderScene
from adforge_renderer.renderer import render_ad
from adforge_renderer.renderer import _make_storyboard_scene
from adforge_renderer.validation import RendererError, probe_video


SAMPLE = {
    "business_name": "Northstar Coffee",
    "product_or_service": "Small-batch coffee, thoughtfully roasted",
    "selling_points": ["Roasted in small batches", "A good cup, made simple"],
    "brand_colors": ["#D98B45", "#F5EFE7"],
    "cta": "Find your next cup",
}


def test_valid_input_is_accepted():
    value = BusinessInput.model_validate(SAMPLE)
    assert value.business_name == "Northstar Coffee"
    assert value.brand_colors == ["#D98B45", "#F5EFE7"]


@pytest.mark.parametrize("field,value", [
    ("business_name", "  "),
    ("product_or_service", ""),
    ("selling_points", [""]),
    ("brand_colors", ["red"]),
    ("cta", "x" * 51),
])
def test_invalid_required_input_is_rejected(field, value):
    data = {**SAMPLE, field: value}
    with pytest.raises(ValidationError):
        BusinessInput.model_validate(data)


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        BusinessInput.model_validate({**SAMPLE, "unreviewed_claim": "best in town"})


def test_empty_selling_points_are_supported_for_milestone_two():
    value = BusinessInput.model_validate({**SAMPLE, "selling_points": []})
    assert value.selling_points == []


def test_missing_ffmpeg_is_actionable(tmp_path: Path):
    with patch("adforge_renderer.renderer.find_tool", side_effect=RendererError("missing")):
        with pytest.raises(RendererError, match="missing"):
            render_ad(BusinessInput.model_validate(SAMPLE), tmp_path / "out.mp4")
    assert not (tmp_path / "out.mp4").exists()


def test_failed_ffmpeg_render_removes_partial_output(tmp_path: Path):
    target = tmp_path / "partial.mp4"
    class Failed:
        returncode = 1
        stdout = ""
        stderr = "simulated encoder failure"
    def fail_after_creating_partial(command, **_kwargs):
        Path(command[-1]).write_bytes(b"partial")
        return Failed()
    with patch("adforge_renderer.renderer.find_tool", return_value="ffmpeg"), \
         patch("adforge_renderer.renderer.subprocess.run", side_effect=fail_after_creating_partial):
        with pytest.raises(RendererError, match="simulated encoder failure"):
            render_ad(BusinessInput.model_validate(SAMPLE), target)
    assert not target.exists()


def test_ffprobe_metadata_validation(tmp_path: Path):
    fake = tmp_path / "sample.mp4"
    fake.write_bytes(b"test")
    payload = {"streams": [{"codec_type": "video", "codec_name": "h264",
                            "width": 1080, "height": 1920}],
               "format": {"format_name": "mov,mp4,m4a", "duration": "7.5"}}
    class Result:
        returncode = 0
        stdout = __import__("json").dumps(payload)
        stderr = ""
    with patch("adforge_renderer.validation.find_tool", return_value="ffprobe"), \
         patch("adforge_renderer.validation.subprocess.run", return_value=Result()):
        metadata = probe_video(fake, expected_width=1080, expected_height=1920,
                               min_duration=6.5, max_duration=8.5)
    assert metadata["codec"] == "h264"
    assert metadata["duration_seconds"] == 7.5


def test_storyboard_renderer_composes_all_scenes_in_submitted_order(tmp_path: Path):
    scenes = tuple(StoryboardRenderScene.model_validate(item) for item in [
        {"scene_id": "scene-first", "title": "First", "on_screen_text": "Opening copy", "duration_seconds": 2, "transition": "cut"},
        {"scene_id": "scene-added", "title": "Added", "on_screen_text": "New scene copy", "duration_seconds": 3, "transition": "fade"},
        {"scene_id": "scene-last", "title": "Last", "on_screen_text": "Closing copy", "duration_seconds": 4, "transition": "cut"},
        {"scene_id": "scene-fourth", "title": "Fourth", "on_screen_text": "Fourth copy", "duration_seconds": 5, "transition": "fade"},
    ])
    composed: list[str] = []
    commands: list[list[str]] = []

    def make_frame(_business, scene, _index, _total):
        composed.append(scene.scene_id)
        from PIL import Image

        return Image.new("RGB", (1080, 1920), "black")

    class Completed:
        returncode = 0
        stderr = ""

    def run_ffmpeg(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"test output")
        return Completed()

    with patch("adforge_renderer.renderer.find_tool", return_value="ffmpeg"), \
         patch("adforge_renderer.renderer._make_storyboard_scene", side_effect=make_frame), \
         patch("adforge_renderer.renderer.subprocess.run", side_effect=run_ffmpeg), \
         patch("adforge_renderer.renderer.probe_video", return_value={"codec": "h264"}):
        metadata = render_ad(
            BusinessInput.model_validate(SAMPLE), tmp_path / "storyboard.mp4", storyboard_scenes=scenes,
        )

    assert metadata == {"codec": "h264"}
    assert composed == [scene.scene_id for scene in scenes]
    assert commands[0].count("-i") == len(scenes)
    filter_graph = commands[0][commands[0].index("-filter_complex") + 1]
    assert "[v3]" in filter_graph
    assert filter_graph.count("xfade=transition=fade") == 2
    assert "concat=n=2:v=1:a=0" in filter_graph
    assert re.findall(r"offset=([0-9.]+)", filter_graph) == ["1.65", "8.3"]
    input_durations = [commands[0][index + 1] for index, value in enumerate(commands[0])
                       if value == "-t"]
    assert input_durations == ["2", "3", "4", "5", "13.3"]


def test_scene_durations_change_the_rendered_timeline(tmp_path: Path):
    business = BusinessInput.model_validate(SAMPLE)
    duration_arguments: list[str] = []

    def capture_command(command, **_kwargs):
        duration_arguments.append(command[command.index("-t", command.index("-filter_complex")) + 1])
        Path(command[-1]).write_bytes(b"test output")

        class Completed:
            returncode = 0
            stderr = ""

        return Completed()

    def make_frames(_business, _scene, _index, _total):
        from PIL import Image

        return Image.new("RGB", (1080, 1920), "black")

    for first_duration in (2, 4):
        scenes = tuple(StoryboardRenderScene.model_validate({
            "scene_id": f"scene-{index}", "title": f"Scene {index}", "on_screen_text": "Copy",
            "duration_seconds": first_duration if index == 0 else 3,
            "transition": "cut" if index == 0 else "fade",
        }) for index in range(2))
        with patch("adforge_renderer.renderer.find_tool", return_value="ffmpeg"), \
             patch("adforge_renderer.renderer._make_storyboard_scene", side_effect=make_frames), \
             patch("adforge_renderer.renderer.subprocess.run", side_effect=capture_command), \
             patch("adforge_renderer.renderer.probe_video", return_value={"codec": "h264"}):
            render_ad(business, tmp_path / f"storyboard-{first_duration}.mp4", storyboard_scenes=scenes)

    assert duration_arguments == ["4.65", "6.65"]


def test_storyboard_renderer_rejects_empty_or_excessive_scene_lists(tmp_path: Path):
    business = BusinessInput.model_validate(SAMPLE)
    with pytest.raises(RendererError, match="between 1 and 6 scenes"):
        render_ad(business, tmp_path / "empty.mp4", storyboard_scenes=())
    excessive = tuple(StoryboardRenderScene.model_validate({
        "scene_id": f"scene-{index}", "title": "Scene", "on_screen_text": "Copy",
        "duration_seconds": 1, "transition": "cut",
    }) for index in range(7))
    with pytest.raises(RendererError, match="between 1 and 6 scenes"):
        render_ad(business, tmp_path / "excessive.mp4", storyboard_scenes=excessive)


def test_each_scene_role_selects_a_distinct_rendered_layout():
    from PIL import ImageChops

    business = BusinessInput.model_validate(SAMPLE)
    frames = []
    for role in ("hook", "benefit", "proof", "cta"):
        scene = StoryboardRenderScene.model_validate({
            "scene_id": f"scene-{role}", "title": "A considered scene",
            "on_screen_text": "A message with deliberate hierarchy", "duration_seconds": 3,
            "transition": "cut", "role": role,
        })
        frames.append(_make_storyboard_scene(business, scene, 1, 4))

    assert all(ImageChops.difference(frames[0], frame).getbbox() for frame in frames[1:])
    assert len({frame.tobytes() for frame in frames}) == 4


def test_non_default_brand_palette_is_consistent_across_all_scene_roles():
    business = BusinessInput.model_validate({**SAMPLE, "brand_colors": ["#176B87", "#E8B84D"]})
    for role in ("hook", "benefit", "proof", "cta"):
        scene = StoryboardRenderScene.model_validate({
            "scene_id": f"scene-{role}", "title": "A considered scene",
            "on_screen_text": "A message with deliberate hierarchy", "duration_seconds": 3,
            "transition": "cut", "role": role,
        })
        frame = _make_storyboard_scene(business, scene, 1, 4)
        colors = frame.getcolors(maxcolors=1080 * 1920)
        observed = {color for count, color in colors or [] if count > 8}
        assert (23, 107, 135) in observed, f"primary color absent from {role} composition"
        assert (232, 184, 77) in observed, f"accent color absent from {role} composition"


def test_default_and_single_color_brand_profiles_are_supported():
    default_business = BusinessInput.model_validate(SAMPLE)
    single_color = BusinessInput.model_validate({**SAMPLE, "brand_colors": ["#176B87"]})
    scene = StoryboardRenderScene.model_validate({
        "scene_id": "scene-default", "title": "Title", "on_screen_text": "Copy",
        "duration_seconds": 3, "transition": "cut",
    })
    default_frame = _make_storyboard_scene(default_business, scene, 0, 3)
    assert default_frame.size == (1080, 1920)
    assert default_frame.getpixel((500, 285)) == (217, 139, 69)
    assert _make_storyboard_scene(single_color, scene, 0, 3).size == (1080, 1920)


def test_role_compositions_share_brand_header_and_use_distinct_role_markers():
    business = BusinessInput.model_validate({**SAMPLE, "brand_colors": ["#176B87", "#E8B84D"]})
    expected_markers = {
        "hook": ((150, 700), (232, 184, 77)),
        "benefit": ((100, 700), (232, 184, 77)),
        "proof": ((120, 700), (232, 184, 77)),
        "cta": ((150, 700), (23, 107, 135)),
    }
    frames = []
    for role, (point, marker) in expected_markers.items():
        scene = StoryboardRenderScene.model_validate({
            "scene_id": f"scene-{role}", "title": "Campaign message",
            "on_screen_text": "A concise supporting line", "duration_seconds": 3,
            "transition": "cut", "role": role,
        })
        frame = _make_storyboard_scene(business, scene, 1, 4)
        assert frame.getpixel((500, 285)) == (23, 107, 135)
        assert frame.getpixel(point) == marker
        frames.append(frame)

    assert len({frame.tobytes() for frame in frames}) == 4


def test_longest_supported_copy_stays_inside_storyboard_safe_frame():
    from PIL import Image, ImageChops

    business = BusinessInput.model_validate({
        **SAMPLE,
        "business_name": "Northstar " * 7,
        "product_or_service": "Thoughtfully prepared everyday coffee " * 2,
        "cta": "Find your next considered everyday cup today",
    })
    background = (21, 28, 33)
    for role in ("hook", "benefit", "proof", "cta"):
        scene = StoryboardRenderScene.model_validate({
            "scene_id": f"scene-{role}", "title": "A deliberately long scene title " * 2,
            "on_screen_text": "A long illustrative message that should wrap safely within the composition. " * 2,
            "duration_seconds": 3, "transition": "cut", "role": role,
        })
        frame = _make_storyboard_scene(business, scene, 0, 4)
        assert frame.size == (1080, 1920)
        assert ImageChops.difference(frame.crop((0, 0, 1080, 124)),
                                    Image.new("RGB", (1080, 124), background)).getbbox() is None
        assert ImageChops.difference(frame.crop((0, 1796, 1080, 1920)),
                                    Image.new("RGB", (1080, 124), background)).getbbox() is None
        assert ImageChops.difference(frame.crop((0, 0, 91, 1920)),
                                    Image.new("RGB", (91, 1920), background)).getbbox() is None
        assert ImageChops.difference(frame.crop((989, 0, 1080, 1920)),
                                    Image.new("RGB", (91, 1920), background)).getbbox() is None


def test_long_unbroken_copy_is_wrapped_and_clipped_to_the_safe_block():
    from PIL import Image, ImageChops, ImageDraw

    base = Image.new("RGB", (240, 150), "black")
    image = base.copy()
    draw = ImageDraw.Draw(image)
    from adforge_renderer.renderer import _draw_fitted_block

    _draw_fitted_block(draw, "UNBROKEN" * 100, x=20, y=25, max_width=180,
                       max_height=80, max_size=34, min_size=20, fill="white")
    bounds = ImageChops.difference(base, image).getbbox()
    assert bounds is not None
    left, top, right, bottom = bounds
    assert left >= 20
    assert right <= 200
    assert top >= 25
    assert bottom <= 105


def test_omitted_scene_roles_keep_position_based_layout_defaults():
    business = BusinessInput.model_validate(SAMPLE)
    expected = ((0, 3, "hook"), (1, 3, "benefit"), (2, 3, "cta"))
    for index, total, expected_role in expected:
        scene = StoryboardRenderScene.model_validate({
            "scene_id": f"scene-{index}", "title": "Scene title", "on_screen_text": "Copy",
            "duration_seconds": 3, "transition": "cut",
        })
        with patch(f"adforge_renderer.renderer._draw_{expected_role}_layout", side_effect=lambda *_, **__: None) as renderer:
            image = _make_storyboard_scene(business, scene, index, total)
        assert image.size == (1080, 1920)
        renderer.assert_called_once()


def test_storyboard_render_scene_rejects_unsupported_and_explicit_null_roles():
    for role in ("unsupported", None):
        with pytest.raises(ValidationError):
            StoryboardRenderScene.model_validate({
                "scene_id": "scene-role", "title": "Title", "on_screen_text": "Copy",
                "duration_seconds": 3, "transition": "cut", "role": role,
            })


def test_render_is_skipped_without_ffmpeg():
    import shutil
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for the real MP4 integration test")
    target = Path("artifacts/test-render.mp4")
    metadata = render_ad(BusinessInput.model_validate(SAMPLE), target)
    assert metadata["width"] == 1080
    assert metadata["height"] == 1920
    assert metadata["codec"] == "h264"
    target.unlink(missing_ok=True)
