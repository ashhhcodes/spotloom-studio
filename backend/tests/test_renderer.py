from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from adforge_renderer.models import BusinessInput
from adforge_renderer.renderer import render_ad
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
