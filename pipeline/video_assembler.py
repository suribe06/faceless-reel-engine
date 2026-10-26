"""Final video assembly via FFmpeg."""

from __future__ import annotations

import logging
from typing import Any

from config import PipelineConfig

logger = logging.getLogger(__name__)


def assemble_video(
    scenes: list[dict[str, Any]],
    audio_files: list[str],
    config: PipelineConfig,
    *,
    title: str = "video",
    cleanup_temp: bool = True,
) -> str:
    """
    Assemble scene images and narration into a vertical MP4.

    Each scene dict must include image_paths (list of 1 or 2 image files).
    """
    if len(scenes) != len(audio_files):
        raise ValueError(
            f"Cantidad inconsistente: {len(scenes)} escenas, {len(audio_files)} audios"
        )

    for i, scene in enumerate(scenes, start=1):
        if not scene.get("image_paths"):
            raise ValueError(f"Escena {i}: sin image_paths — ejecuta generate_images primero")

    from pipeline.ffmpeg_assembler import assemble_video_ffmpeg

    logger.info(
        "Ensamblando con FFmpeg (preset=%s, fps=%d)",
        config.FFMPEG_PRESET,
        config.VIDEO_FPS,
    )
    return assemble_video_ffmpeg(
        scenes,
        audio_files,
        config,
        title=title,
        cleanup_temp=cleanup_temp,
    )
