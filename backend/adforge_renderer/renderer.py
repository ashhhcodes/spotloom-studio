"""Pillow scene composition and bounded FFmpeg video rendering."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from .models import (
    MAX_STORYBOARD_RENDER_SECONDS,
    STORYBOARD_FADE_SECONDS,
    BusinessInput,
    StoryboardRenderScene,
    storyboard_render_duration,
)
from .validation import RendererError, find_tool, probe_video

WIDTH, HEIGHT = 1080, 1920
FPS = 24
SCENE_SECONDS = 2.8
TRANSITION_SECONDS = STORYBOARD_FADE_SECONDS


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
        parts: list[str] = []
        part = ""
        for character in word:
            candidate = part + character
            if part and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
                parts.append(part)
                part = character
            else:
                part = candidate
        if part:
            parts.append(part)
        for part in parts:
            trial = f"{line} {part}".strip()
            if draw.textbbox((0, 0), trial, font=font)[2] <= max_width:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = part
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


def _draw_fitted_block(draw: ImageDraw.ImageDraw, text: str, *, x: int, y: int,
                       max_width: int, max_height: int, max_size: int, min_size: int,
                       fill: str, bold: bool = True, align: str = "left") -> None:
    """Draw bounded copy inside a safe area, shrinking the font when needed."""
    selected_font = _font(min_size, bold=bold)
    selected_lines = _wrap(draw, text, selected_font, max_width)
    selected_height = 0
    fitted = False
    for size in range(max_size, min_size - 1, -2):
        candidate = _font(size, bold=bold)
        lines = _wrap(draw, text, candidate, max_width)
        heights = [draw.textbbox((0, 0), line, font=candidate)[3]
                   - draw.textbbox((0, 0), line, font=candidate)[1] for line in lines]
        block_height = sum(heights) + max(0, len(lines) - 1) * 20
        if block_height <= max_height:
            selected_font, selected_lines, selected_height = candidate, lines, block_height
            fitted = True
            break
    if not fitted:
        heights = [draw.textbbox((0, 0), line, font=selected_font)[3]
                   - draw.textbbox((0, 0), line, font=selected_font)[1] for line in selected_lines]
        line_step = (heights[0] if heights else min_size) + 20
        max_lines = max(1, (max_height + 20) // line_step)
        selected_lines = selected_lines[:max_lines]
        if len(_wrap(draw, text, selected_font, max_width)) > max_lines:
            last = selected_lines[-1]
            while last and draw.textbbox((0, 0), f"{last}…", font=selected_font)[2] > max_width:
                last = last[:-1]
            selected_lines[-1] = f"{last.rstrip()}…"
        selected_height = max_height
    if align == "center":
        y += max(0, (max_height - selected_height) // 2)
    for line in selected_lines:
        box = draw.textbbox((0, 0), line, font=selected_font)
        draw_x = x if align == "left" else x + (max_width - (box[2] - box[0])) // 2
        draw.text((draw_x, y), line, font=selected_font, fill=fill)
        y += (box[3] - box[1]) + 20


def _contrast_text(color: str) -> str:
    """Choose readable near-black or white text for a solid brand-color surface."""
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    return "#11191E" if luminance > 0.179 else "#FFFFFF"


def _storyboard_palette(business: BusinessInput) -> tuple[str, str, str, str, str]:
    primary = business.brand_colors[0]
    accent = business.brand_colors[1] if len(business.brand_colors) > 1 else "#F5EFE7"
    return "#151C21", primary, accent, "#FFFDF7", "#CDD3D4"


def _draw_brand_header(draw: ImageDraw.ImageDraw, business: BusinessInput, section: str,
                       primary: str, muted: str) -> None:
    """Repeat a bounded brand lockup while letting each scene keep its purpose."""
    _draw_fitted_block(draw, business.business_name.upper(), x=145, y=190,
                       max_width=470, max_height=48, max_size=28, min_size=20,
                       fill=muted, bold=True)
    label_font = _font(24, bold=True)
    label_box = draw.textbbox((0, 0), section.upper(), font=label_font)
    draw.text((935 - (label_box[2] - label_box[0]), 200), section.upper(),
              font=label_font, fill=primary)
    draw.rounded_rectangle((145, 282, 935, 290), radius=4, fill=primary)


def _draw_scene_footer(draw: ImageDraw.ImageDraw, index: int, total: int, muted: str) -> None:
    """Keep sequence context and progress in the same safe-margin footer."""
    draw.text((145, 1660), f"{index + 1:02d}   /   {total:02d}",
              font=_font(30, bold=True), fill=muted)
    draw.line((145, 1715, 935, 1715), fill="#414A4E", width=4)
    progress_end = 145 + round(790 * (index + 1) / total)
    draw.line((145, 1715, progress_end, 1715), fill=muted, width=6)


def _draw_hook_layout(draw: ImageDraw.ImageDraw, business: BusinessInput,
                      scene: StoryboardRenderScene, index: int, total: int,
                      primary: str, accent: str, foreground: str, muted: str) -> None:
    _draw_brand_header(draw, business, "Opening", primary, muted)
    draw.rounded_rectangle((145, 380, 935, 1360), radius=38, fill="#202A30", outline=primary, width=4)
    draw.rounded_rectangle((145, 380, 166, 1360), radius=10, fill=accent)
    draw.rounded_rectangle((198, 438, 420, 495), radius=16, fill=primary)
    draw.text((220, 453), "THE HOOK", font=_font(24, bold=True), fill=_contrast_text(primary))
    _draw_fitted_block(draw, scene.title, x=205, y=540, max_width=680, max_height=145,
                       max_size=48, min_size=30, fill=muted)
    _draw_fitted_block(draw, scene.on_screen_text, x=205, y=720, max_width=680,
                       max_height=540, max_size=104, min_size=48, fill=foreground)
    _draw_fitted_block(draw, business.product_or_service, x=145, y=1460, max_width=790,
                       max_height=110, max_size=34, min_size=24, fill=muted, bold=False)
    _draw_scene_footer(draw, index, total, muted)


def _draw_benefit_layout(draw: ImageDraw.ImageDraw, business: BusinessInput,
                         scene: StoryboardRenderScene,
                         index: int, total: int, primary: str, accent: str,
                         foreground: str, muted: str) -> None:
    _draw_brand_header(draw, business, "Benefits", primary, muted)
    draw.rounded_rectangle((96, 430, 984, 1400), radius=34, fill="#222C33", outline=primary, width=3)
    draw.rectangle((96, 500, 118, 1320), fill=accent)
    chip = (160, 500, 530, 558)
    draw.rounded_rectangle(chip, radius=15, fill=primary)
    draw.text((chip[0] + 18, chip[1] + 16), f"BENEFIT  /  {index + 1:02d} OF {total:02d}",
              font=_font(23, bold=True), fill=_contrast_text(primary))
    _draw_fitted_block(draw, scene.title, x=160, y=660, max_width=760, max_height=165,
                       max_size=52, min_size=34, fill=muted)
    _draw_fitted_block(draw, scene.on_screen_text, x=160, y=870, max_width=760,
                       max_height=400, max_size=72, min_size=42, fill=foreground)
    benefit_chip = (160, 1460, 570, 1525)
    draw.rounded_rectangle(benefit_chip, radius=16, fill=accent)
    draw.text((benefit_chip[0] + 20, benefit_chip[1] + 18), "A CLEAR BENEFIT",
              font=_font(25, bold=True), fill=_contrast_text(accent))
    _draw_scene_footer(draw, index, total, muted)


def _draw_proof_layout(draw: ImageDraw.ImageDraw, business: BusinessInput,
                       scene: StoryboardRenderScene,
                       index: int, total: int, primary: str, accent: str,
                       foreground: str, muted: str) -> None:
    _draw_brand_header(draw, business, "Supporting detail", primary, muted)
    # This is a supporting-detail composition, not evidence that the copy is verified.
    draw.rounded_rectangle((112, 390, 968, 1460), radius=22, outline=primary, width=5)
    draw.rectangle((112, 390, 128, 1460), fill=accent)
    draw.text((176, 465), f"DETAIL  /  {index + 1:02d} OF {total:02d}",
              font=_font(27, bold=True), fill=accent)
    draw.line((176, 530, 880, 530), fill="#414A4E", width=3)
    _draw_fitted_block(draw, scene.title, x=176, y=610, max_width=700, max_height=175,
                       max_size=46, min_size=32, fill=muted)
    draw.rounded_rectangle((176, 835, 900, 1330), radius=18, fill="#202A30")
    draw.rectangle((176, 835, 188, 1330), fill=primary)
    _draw_fitted_block(draw, scene.on_screen_text, x=220, y=890, max_width=620,
                       max_height=380, max_size=58, min_size=36, fill=foreground, bold=False)
    _draw_scene_footer(draw, index, total, muted)


def _draw_cta_layout(draw: ImageDraw.ImageDraw, business: BusinessInput,
                     scene: StoryboardRenderScene, index: int, total: int,
                     primary: str, accent: str, foreground: str, muted: str) -> None:
    _draw_brand_header(draw, business, "Next step", primary, muted)
    draw.rounded_rectangle((112, 430, 968, 1190), radius=34, fill="#202A30", outline=accent, width=3)
    draw.rounded_rectangle((145, 465, 161, 1155), radius=7, fill=primary)
    _draw_fitted_block(draw, scene.title, x=205, y=520, max_width=680, max_height=140,
                       max_size=46, min_size=30, fill=muted)
    _draw_fitted_block(draw, scene.on_screen_text, x=205, y=705, max_width=680,
                       max_height=400, max_size=76, min_size=40, fill=foreground)
    button = (145, 1300, 935, 1535)
    draw.rounded_rectangle((145, 1260, 935, 1272), radius=6, fill=accent)
    draw.rounded_rectangle(button, radius=44, fill=primary)
    cta_fill = _contrast_text(primary)
    _draw_fitted_block(draw, business.cta, x=button[0] + 28, y=button[1] + 30,
                       max_width=button[2] - button[0] - 56,
                       max_height=button[3] - button[1] - 60, max_size=58,
                       min_size=32, fill=cta_fill, align="center")
    _draw_scene_footer(draw, index, total, muted)


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


def _make_storyboard_scene(business: BusinessInput, scene: StoryboardRenderScene,
                           index: int, total: int) -> Image.Image:
    """Draw one role-specific storyboard composition from the submitted scene."""
    role = scene.role or ("hook" if index == 0 else "cta" if index == total - 1 else "benefit")
    background, primary, accent, foreground, muted = _storyboard_palette(business)
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((92, 125, 988, 1795), radius=48, outline=primary, width=5)
    layouts = {
        "hook": lambda: _draw_hook_layout(draw, business, scene, index, total, primary, accent, foreground, muted),
        "benefit": lambda: _draw_benefit_layout(draw, business, scene, index, total, primary, accent, foreground, muted),
        "proof": lambda: _draw_proof_layout(draw, business, scene, index, total, primary, accent, foreground, muted),
        "cta": lambda: _draw_cta_layout(draw, business, scene, index, total, primary, accent, foreground, muted),
    }
    layouts[role]()
    return image


def render_ad(business: BusinessInput, output_path: Path, *,
              storyboard_scenes: Sequence[StoryboardRenderScene] | None = None,
              width: int = WIDTH,
              height: int = HEIGHT, timeout_seconds: int = 120) -> dict:
    """Render a legacy fixed or submitted storyboard sequence as H.264 MP4."""
    if width < 360 or height < 640 or width % 2 or height % 2:
        raise RendererError("Video dimensions must be even and at least 360x640.")
    is_storyboard = storyboard_scenes is not None
    scene_count = len(storyboard_scenes) if storyboard_scenes is not None else 3
    if storyboard_scenes is not None and not 1 <= scene_count <= 6:
        raise RendererError("Storyboard renders require between 1 and 6 scenes.")
    if storyboard_scenes is not None and len({scene.scene_id for scene in storyboard_scenes}) != scene_count:
        raise RendererError("Storyboard scene IDs must be unique.")
    if storyboard_scenes is not None and storyboard_scenes[0].transition != "cut":
        raise RendererError("The first storyboard scene must use a cut transition.")
    render_duration = (storyboard_render_duration(storyboard_scenes) if storyboard_scenes is not None
                       else SCENE_SECONDS * 3 - TRANSITION_SECONDS * 2)
    if storyboard_scenes is not None and render_duration > MAX_STORYBOARD_RENDER_SECONDS:
        raise RendererError("Storyboard render duration exceeds the 30-second local demo limit.")
    ffmpeg = find_tool("ffmpeg")
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="adforge-render-") as temp_dir:
            temp = Path(temp_dir)
            for index in range(scene_count):
                scene = (_make_storyboard_scene(business, storyboard_scenes[index], index, scene_count)
                         if storyboard_scenes is not None else _make_scene(business, index))
                if (width, height) != (WIDTH, HEIGHT):
                    scene = scene.resize((width, height), Image.Resampling.LANCZOS)
                scene.save(temp / f"scene-{index}.png", optimize=True)
            inputs: list[str] = []
            filters: list[str] = []
            for index in range(scene_count):
                scene_duration = (storyboard_scenes[index].duration_seconds
                                  if storyboard_scenes is not None else SCENE_SECONDS)
                inputs.extend(["-loop", "1", "-framerate", str(FPS), "-t",
                               str(scene_duration), "-i", str(temp / f"scene-{index}.png")])
                filters.append(
                    f"[{index}:v]zoompan=z='min(zoom+0.00035,1.035)':d=1:"
                    f"s={width}x{height}:fps={FPS},trim=duration={scene_duration},"
                    f"setpts=PTS-STARTPTS,format=yuv420p,settb=AVTB[v{index}]"
                )
            if storyboard_scenes is None:
                first_offset = SCENE_SECONDS - TRANSITION_SECONDS
                second_offset = first_offset * 2
                filters.extend([
                    f"[v0][v1]xfade=transition=fade:duration={TRANSITION_SECONDS}:"
                    f"offset={first_offset}[mix1]",
                    f"[mix1][v2]xfade=transition=fade:duration={TRANSITION_SECONDS}:"
                    f"offset={second_offset},format=yuv420p[outv]",
                ])
            else:
                prior = "[v0]"
                elapsed = float(storyboard_scenes[0].duration_seconds)
                for index in range(1, scene_count):
                    output = f"[sequence{index}]"
                    scene = storyboard_scenes[index]
                    if scene.transition == "fade":
                        filters.append(
                            f"{prior}[v{index}]xfade=transition=fade:duration={TRANSITION_SECONDS}:"
                            f"offset={elapsed - TRANSITION_SECONDS},settb=AVTB,setpts=PTS-STARTPTS{output}"
                        )
                        elapsed += scene.duration_seconds - TRANSITION_SECONDS
                    else:
                        filters.append(
                            f"{prior}[v{index}]concat=n=2:v=1:a=0,settb=AVTB,setpts=PTS-STARTPTS{output}"
                        )
                        elapsed += scene.duration_seconds
                    prior = output
                filters.append(f"{prior}format=yuv420p[outv]")
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs,
                       "-filter_complex", ";".join(filters), "-map", "[outv]", "-an",
                       "-c:v", "libx264", "-preset", "ultrafast", "-movflags", "+faststart",
                       "-t", str(render_duration), str(output_path)]
            try:
                result = subprocess.run(command, capture_output=True, text=True,
                                        timeout=timeout_seconds, check=False)
            except subprocess.TimeoutExpired as exc:
                raise RendererError(f"FFmpeg exceeded its {timeout_seconds}s time limit.") from exc
            except OSError as exc:
                raise RendererError(f"Could not start FFmpeg: {exc}") from exc
            if result.returncode:
                raise RendererError(f"FFmpeg render failed: {result.stderr.strip() or 'unknown error'}")
        if is_storyboard:
            metadata = probe_video(
                output_path, expected_width=width, expected_height=height,
                min_duration=max(0.5, render_duration - 0.2), max_duration=render_duration + 0.2,
            )
        else:
            metadata = probe_video(output_path, expected_width=width, expected_height=height,
                                   min_duration=6.5, max_duration=8.5)
        return metadata
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
