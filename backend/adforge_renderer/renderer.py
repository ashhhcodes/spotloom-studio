"""Pillow scene composition and bounded FFmpeg video rendering."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import BusinessInput
from .validation import RendererError, find_tool, probe_video

WIDTH, HEIGHT = 1080, 1920
FPS = 24
SCENE_SECONDS = 2.8
TRANSITION_SECONDS = 0.35


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = ([r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf"] if bold
                  else [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"])
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
          max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def _draw_centered(draw: ImageDraw.ImageDraw, text: str, y: int,
                   font: ImageFont.ImageFont, fill: str, max_width: int) -> int:
    lines = _wrap(draw, text, font, max_width)
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font, stroke_width=0)
        x = (WIDTH - (box[2] - box[0])) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += (box[3] - box[1]) + 18
    return y


def _make_scene(business: BusinessInput, index: int) -> Image.Image:
    primary = business.brand_colors[0]
    secondary = business.brand_colors[1] if len(business.brand_colors) > 1 else "#F5EFE7"
    backgrounds = [("#151A20", primary), ("#F2EEE7", secondary), ("#17191D", primary)]
    background, accent = backgrounds[index]
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    # Restrained geometric brand motif, generated from original shapes rather than stock imagery.
    draw.rounded_rectangle((92, 125, 988, 1795), radius=48, outline=accent, width=5)
    draw.ellipse((790, 180, 1110, 500), fill=accent)
    draw.ellipse((-140, 1390, 260, 1790), fill=accent)
    foreground = "#FFFFFF" if index != 1 else "#17191D"
    muted = "#D8D5D0" if index != 1 else "#55514B"
    draw.text((145, 205), "ADFORGE  /  BRAND STORY", font=_font(28, bold=True), fill=muted)
    draw.rounded_rectangle((145, 330, 320, 342), radius=6, fill=accent)

    if index == 0:
        y = _draw_centered(draw, business.business_name, 560, _font(92, bold=True), foreground, 790)
        _draw_centered(draw, business.product_or_service, y + 70, _font(54), muted, 760)
    elif index == 1:
        if len(business.selling_points) >= 3:
            _draw_centered(draw, "SELLING POINTS", 570, _font(34, bold=True), accent, 800)
            y = 700
            for point in business.selling_points:
                y = _draw_centered(draw, point, y, _font(48, bold=True), foreground, 750) + 35
        elif business.selling_points:
            _draw_centered(draw, "MADE FOR YOUR DAY", 570, _font(34, bold=True), accent, 800)
            y = _draw_centered(draw, business.selling_points[0], 750, _font(72, bold=True), foreground, 750)
            _draw_centered(draw, business.product_or_service, y + 45, _font(42), muted, 760)
        else:
            _draw_centered(draw, "A CLOSER LOOK", 650, _font(54, bold=True), foreground, 750)
    else:
        if len(business.selling_points) == 2:
            _draw_centered(draw, "A LITTLE MORE", 560, _font(38, bold=True), accent, 800)
            _draw_centered(draw, business.selling_points[-1], 650, _font(72, bold=True), foreground, 770)
        else:
            _draw_centered(draw, "YOUR NEXT STEP", 620, _font(46, bold=True), accent, 800)
        _draw_centered(draw, business.business_name, 1130, _font(44), muted, 800)
        # CTA is a deterministic text overlay, never embedded in generated imagery.
        cta_font = _font(54, bold=True)
        for size in range(54, 27, -2):
            candidate = _font(size, bold=True)
            if draw.textbbox((0, 0), business.cta, font=candidate)[2] <= 710:
                cta_font = candidate
                break
        box = draw.textbbox((0, 0), business.cta, font=cta_font)
        box_width = box[2] - box[0] + 110
        x0, y0 = (WIDTH - box_width) // 2, 1460
        draw.rounded_rectangle((x0, y0, x0 + box_width, y0 + 138), radius=36, fill=accent)
        luminance = (int(accent[1:3], 16) * 299 + int(accent[3:5], 16) * 587
                     + int(accent[5:7], 16) * 114) / 1000
        draw.text((WIDTH // 2 - (box[2] - box[0]) // 2, y0 + 35), business.cta,
                  font=cta_font, fill="#111111" if luminance > 155 else "#FFFFFF")

    draw.text((145, 1660), f"{index + 1:02d}   /   03", font=_font(30, bold=True), fill=muted)
    return image


def render_ad(business: BusinessInput, output_path: Path, *, width: int = WIDTH,
              height: int = HEIGHT, timeout_seconds: int = 120) -> dict:
    """Render and verify a 3-scene vertical H.264 MP4, removing partial outputs on failure."""
    if width < 360 or height < 640 or width % 2 or height % 2:
        raise RendererError("Video dimensions must be even and at least 360x640.")
    ffmpeg = find_tool("ffmpeg")
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="adforge-render-") as temp_dir:
            temp = Path(temp_dir)
            for index in range(3):
                scene = _make_scene(business, index)
                if (width, height) != (WIDTH, HEIGHT):
                    scene = scene.resize((width, height), Image.Resampling.LANCZOS)
                scene.save(temp / f"scene-{index}.png", optimize=True)
            inputs: list[str] = []
            filters: list[str] = []
            for index in range(3):
                inputs.extend(["-loop", "1", "-framerate", str(FPS), "-t",
                               str(SCENE_SECONDS), "-i", str(temp / f"scene-{index}.png")])
                filters.append(
                    f"[{index}:v]zoompan=z='min(zoom+0.00035,1.035)':d=1:"
                    f"s={width}x{height}:fps={FPS},trim=duration={SCENE_SECONDS},"
                    f"setpts=PTS-STARTPTS,format=yuv420p,settb=AVTB[v{index}]"
                )
            first_offset = SCENE_SECONDS - TRANSITION_SECONDS
            second_offset = first_offset * 2
            filters.extend([
                f"[v0][v1]xfade=transition=fade:duration={TRANSITION_SECONDS}:"
                f"offset={first_offset}[mix1]",
                f"[mix1][v2]xfade=transition=fade:duration={TRANSITION_SECONDS}:"
                f"offset={second_offset},format=yuv420p[outv]",
            ])
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                       "-filter_complex", ";".join(filters), "-map", "[outv]", "-an",
                       "-c:v", "libx264", "-preset", "ultrafast", "-movflags", "+faststart",
                       "-t", str(SCENE_SECONDS * 3 - TRANSITION_SECONDS * 2), str(output_path)]
            try:
                result = subprocess.run(command, capture_output=True, text=True,
                                        timeout=timeout_seconds, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RendererError(f"FFmpeg exceeded its {timeout_seconds}s time limit.") from exc
            except OSError as exc:
                raise RendererError(f"Could not start FFmpeg: {exc}") from exc
            if result.returncode:
                raise RendererError(f"FFmpeg render failed: {result.stderr.strip() or 'unknown error'}")
        metadata = probe_video(output_path, expected_width=width, expected_height=height,
                               min_duration=6.5, max_duration=8.5)
        return metadata
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
