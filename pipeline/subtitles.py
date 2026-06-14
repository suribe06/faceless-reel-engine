"""Burn-in subtitles from script narration (no Whisper needed)."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import PipelineConfig

logger = logging.getLogger(__name__)


def _resolve_font(config: PipelineConfig) -> str:
    if config.SUBTITLE_FONT_PATH and Path(config.SUBTITLE_FONT_PATH).exists():
        return str(config.SUBTITLE_FONT_PATH)
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        "No se encontró fuente para subtítulos. "
        "Instala fonts-liberation o define SUBTITLE_FONT_PATH en config.py"
    )


def split_narration_lines(text: str, max_chars: int) -> list[str]:
    """Split narration into readable subtitle lines."""
    text = " ".join(text.strip().split())
    if not text:
        return []

    sentences: list[str] = []
    for part in text.replace("...", ".").split(". "):
        chunk = part.strip()
        if not chunk:
            continue
        if not chunk.endswith("."):
            chunk += "."
        sentences.extend(textwrap.wrap(chunk, width=max_chars) or [chunk])

    return sentences or [text[:max_chars]]


def build_subtitle_cues(
    narration: str,
    duration: float,
    config: PipelineConfig,
) -> list[tuple[float, float, str]]:
    """Build (start, end, text) cues proportional to line length."""
    lines = split_narration_lines(narration, config.SUBTITLE_MAX_CHARS)
    if not lines:
        return []

    total_chars = sum(len(line) for line in lines)
    cues: list[tuple[float, float, str]] = []
    t = 0.0
    for line in lines:
        share = len(line) / max(total_chars, 1)
        part_dur = max(0.35, duration * share)
        cues.append((t, min(duration, t + part_dur), line))
        t += part_dur
        if t >= duration:
            break

    if cues:
        start, _end, last = cues[-1]
        cues[-1] = (start, duration, last)
    return cues


def _format_srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt_for_scenes(
    scenes: list[dict[str, Any]],
    path: Path,
    config: PipelineConfig,
) -> None:
    """Write SRT subtitles from scene narrations (for FFmpeg burn-in)."""
    if not config.SUBTITLES_ENABLED:
        path.write_text("", encoding="utf-8")
        return

    blocks: list[str] = []
    cue_index = 1
    scene_offset = 0.0

    for scene in scenes:
        narration = scene.get("narration", "").strip()
        duration = float(scene.get("audio_duration", 0))
        if not narration or duration <= 0:
            scene_offset += duration
            continue

        for start, end, text in build_subtitle_cues(narration, duration, config):
            abs_start = scene_offset + start
            abs_end = scene_offset + end
            blocks.append(
                f"{cue_index}\n"
                f"{_format_srt_time(abs_start)} --> {_format_srt_time(abs_end)}\n"
                f"{text}\n"
            )
            cue_index += 1
        scene_offset += duration

    path.write_text("\n".join(blocks), encoding="utf-8")


def render_subtitle_rgba(text: str, config: PipelineConfig, font_path: str) -> np.ndarray:
    """Render one subtitle line to RGBA numpy array."""
    width = config.IMAGE_WIDTH - config.SUBTITLE_MARGIN_X * 2
    font = ImageFont.truetype(font_path, config.SUBTITLE_FONT_SIZE)
    lines = textwrap.wrap(text, width=config.SUBTITLE_MAX_CHARS) or [text]

    line_heights = []
    max_line_w = 0
    for line in lines:
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        line_h = bbox[3] - bbox[1]
        max_line_w = max(max_line_w, line_w)
        line_heights.append(line_h)

    pad_x, pad_y = 16, 12
    block_w = min(width, max_line_w + pad_x * 2)
    block_h = sum(line_heights) + pad_y * 2 + (len(lines) - 1) * 6

    img = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (0, 0, block_w - 1, block_h - 1),
        radius=8,
        fill=(0, 0, 0, int(255 * config.SUBTITLE_BG_OPACITY)),
    )

    y = pad_y
    for line, lh in zip(lines, line_heights):
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (block_w - line_w) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += lh + 6

    return np.array(img)


def overlay_subtitles_on_clip(
    base_clip,
    scene: dict[str, Any],
    duration: float,
    config: PipelineConfig,
    mpy_version: str,
    mp: dict,
):
    """Composite subtitle cues over a scene clip."""
    if not config.SUBTITLES_ENABLED:
        return base_clip

    narration = scene.get("narration", "").strip()
    if not narration:
        return base_clip

    font_path = _resolve_font(config)
    cues = build_subtitle_cues(narration, duration, config)
    if not cues:
        return base_clip

    CompositeVideoClip = mp["CompositeVideoClip"]
    ImageClip = mp["ImageClip"]
    layers = [base_clip]

    for start, end, text in cues:
        if end <= start:
            continue
        rgba = render_subtitle_rgba(text, config, font_path)
        sub = ImageClip(rgba, is_mask=False, transparent=True)
        clip_dur = end - start

        if mpy_version == "v2":
            sub = sub.with_duration(clip_dur)
            sub = sub.with_start(start)
            y = config.IMAGE_HEIGHT - rgba.shape[0] - config.SUBTITLE_MARGIN_Y
            x = (config.IMAGE_WIDTH - rgba.shape[1]) // 2
            sub = sub.with_position((x, y))
        else:
            sub = sub.set_duration(clip_dur)
            sub = sub.set_start(start)
            y = config.IMAGE_HEIGHT - rgba.shape[0] - config.SUBTITLE_MARGIN_Y
            x = (config.IMAGE_WIDTH - rgba.shape[1]) // 2
            sub = sub.set_position((x, y))

        layers.append(sub)

    if len(layers) == 1:
        return base_clip

    return CompositeVideoClip(layers, size=(config.IMAGE_WIDTH, config.IMAGE_HEIGHT))
