"""Shared assembly planning helpers — public seam for ffmpeg and moviepy adapters."""

from __future__ import annotations

import logging
import random
import re
import shutil
from pathlib import Path

from config import PipelineConfig
from pipeline.run_state import dual_shot_durations

logger = logging.getLogger(__name__)


def sanitize_title(title: str) -> str:
    """Convert title to a safe lowercase filename slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "video"


def pick_background_music(config: PipelineConfig) -> Path | None:
    """Pick background music — default track or random from assets/music."""
    music_dir = config.ASSETS_MUSIC_DIR
    if not music_dir.exists():
        return None

    if config.MUSIC_MODE == "random":
        tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.MP3"))
        return random.choice(tracks) if tracks else None

    default_path = music_dir / config.DEFAULT_MUSIC_FILE
    if default_path.exists():
        return default_path

    logger.warning(
        "Pista default no encontrada (%s) — usando primera MP3 disponible",
        default_path.name,
    )
    tracks = sorted(music_dir.glob("*.mp3"))
    return tracks[0] if tracks else None


def cleanup_temp(temp_dir: Path) -> None:
    """Remove temporary working files."""
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        logger.info("Directorio temporal limpiado: %s", temp_dir)


def ass_font_size(config: PipelineConfig) -> int:
    """
    Map PIL subtitle size to libass FontSize for comparable burn-in.

    ASS units render larger than PIL pixels; ~0.4 keeps default 42 → 16.
    """
    return max(12, int(config.SUBTITLE_FONT_SIZE * 0.4))


def scene_image_part_durations(image_count: int, duration: float) -> list[float]:
    """Planner: durations per image for a scene."""
    if image_count <= 1:
        return [duration]
    first, second = dual_shot_durations(duration)
    return [first, second]
