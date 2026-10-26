"""Burn-in subtitles from script narration (no Whisper needed)."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any

from config import PipelineConfig


def resolve_font(config: PipelineConfig) -> str:
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


def split_spoken_sentences(text: str) -> list[str]:
    """Sentence units Kokoro speaks as one piece, so cue times can match the wav."""
    text = " ".join(text.strip().split())
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if not parts:
        return [text]
    sentences: list[str] = []
    for part in parts:
        if part[-1] not in ".!?":
            part += "."
        sentences.append(part)
    return sentences


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


def cues_from_spoken_durations(
    sentences: list[str],
    durations: list[float],
    config: PipelineConfig,
    gap: float,
) -> list[tuple[float, float, str]]:
    """Place lines inside each spoken sentence. Drift stays inside that sentence."""
    cues: list[tuple[float, float, str]] = []
    t = 0.0
    for i, (sentence, dur) in enumerate(zip(sentences, durations)):
        dur = max(0.0, float(dur))
        if dur <= 0 or not sentence.strip():
            continue
        for start, end, line in build_subtitle_cues(sentence, dur, config):
            cues.append((t + start, t + end, line))
        t += dur
        if i < len(sentences) - 1:
            t += max(0.0, gap)
    return cues


def scene_cues(
    scene: dict[str, Any],
    config: PipelineConfig,
) -> list[tuple[float, float, str]]:
    """Prefer timings measured at TTS. Fall back to a char split for old runs."""
    stored = scene.get("subtitle_cues")
    if isinstance(stored, list) and stored:
        cues: list[tuple[float, float, str]] = []
        for item in stored:
            if not isinstance(item, dict) or not str(item.get("text", "")).strip():
                continue
            cues.append((float(item["start"]), float(item["end"]), str(item["text"]).strip()))
        if cues:
            return cues
    return build_subtitle_cues(
        str(scene.get("narration", "")),
        float(scene.get("audio_duration") or 0),
        config,
    )


def cues_in_window(
    cues: list[tuple[float, float, str]],
    start: float,
    end: float,
) -> list[tuple[float, float, str]]:
    """Shift cues into a shot that only covers [start, end] of the scene."""
    selected: list[tuple[float, float, str]] = []
    for c0, c1, text in cues:
        if c1 <= start + 0.01 or c0 >= end - 0.01:
            continue
        selected.append((max(0.0, c0 - start), min(end, c1) - start, text))
    return selected


def _format_srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt_cues(cues: list[tuple[float, float, str]], path: Path) -> None:
    """Write an SRT whose zero is the start of this shot."""
    blocks: list[str] = []
    cue_index = 1
    for start, end, text in cues:
        if end <= start or not text.strip():
            continue
        blocks.append(
            f"{cue_index}\n"
            f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
            f"{text.strip()}\n"
        )
        cue_index += 1
    path.write_text("\n".join(blocks), encoding="utf-8")


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

        for start, end, text in scene_cues(scene, config):
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
