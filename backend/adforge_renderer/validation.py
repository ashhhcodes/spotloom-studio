"""FFprobe-backed verification for rendered MP4 artifacts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class RendererError(RuntimeError):
    """Expected, user-actionable renderer failure."""


def find_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RendererError(f"{name} was not found on PATH. Install FFmpeg and reopen PowerShell.")
    return path


def probe_video(path: Path, *, expected_width: int, expected_height: int,
                min_duration: float, max_duration: float) -> dict:
    if not path.is_file() or path.stat().st_size == 0:
        raise RendererError("Renderer produced no video file.")
    command = [find_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format",
               "-of", "json", str(path)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RendererError(f"FFprobe could not inspect the output: {exc}") from exc
    if result.returncode:
        raise RendererError(f"FFprobe rejected the output: {result.stderr.strip() or 'unknown error'}")
    try:
        metadata = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RendererError("FFprobe returned malformed metadata.") from exc
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    fmt = metadata.get("format", {})
    duration = float(fmt.get("duration", 0))
    if not video or fmt.get("format_name", "").find("mp4") < 0:
        raise RendererError("Output is not a valid MP4 containing a video stream.")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (expected_width, expected_height):
        raise RendererError("Output dimensions do not match the requested dimensions.")
    if video.get("codec_name") != "h264":
        raise RendererError("Output video codec is not H.264.")
    if not min_duration <= duration <= max_duration:
        raise RendererError(f"Output duration {duration:.2f}s is outside the expected range.")
    return {"container": "mp4", "codec": "h264", "width": expected_width,
            "height": expected_height, "duration_seconds": duration,
            "size_bytes": path.stat().st_size}
