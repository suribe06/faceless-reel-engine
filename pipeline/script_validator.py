"""Validate script and narration before expensive GPU steps."""

from __future__ import annotations

import logging
from typing import Any

from config import PipelineConfig

logger = logging.getLogger(__name__)

# Tolerancia en chars: el guión puede quedar 8% bajo el mínimo teórico si TTS cumple duración
CHAR_MIN_TOLERANCE = 0.92


def find_short_narrations(
    scenes: list[dict[str, Any]],
    config: PipelineConfig,
    *,
    tolerance: float = CHAR_MIN_TOLERANCE,
) -> list[tuple[int, int, int]]:
    """Return (scene_number, actual_chars, min_chars) for scenes below minimum."""
    char_min, _char_max = config.narration_char_bounds()
    effective_min = max(80, int(char_min * tolerance))
    short: list[tuple[int, int, int]] = []
    for i, scene in enumerate(scenes, start=1):
        length = len(scene.get("narration", "").strip())
        if length < effective_min:
            short.append((i, length, char_min))
    return short


def validate_before_images(
    scenes: list[dict[str, Any]],
    config: PipelineConfig,
    total_audio_seconds: float,
) -> None:
    """
    Block ComfyUI only when the real TTS duration misses the target.

    Per-scene char counts are hints for Ollama, not hard gates once audio exists.
    """
    min_target = config.TARGET_DURATION_MIN_SECONDS * 0.97
    max_target = config.TARGET_DURATION_MAX_SECONDS * 1.08

    if total_audio_seconds < min_target:
        short = find_short_narrations(scenes, config, tolerance=1.0)
        hint = ""
        if short:
            samples = ", ".join(
                f"escena {n} ({actual}/{need} chars)"
                for n, actual, need in short[:5]
            )
            hint = f" Escenas cortas: {samples}."
        raise ValueError(
            f"Audio total {total_audio_seconds:.1f}s < mínimo "
            f"{config.TARGET_DURATION_MIN_SECONDS}s (umbral {min_target:.0f}s). "
            f"No se inicia ComfyUI.{hint} "
            "Reintenta el guión o usa --duration-min más bajo."
        )

    short = find_short_narrations(scenes, config)
    if short:
        samples = ", ".join(
            f"escena {n} ({actual}/{need})" for n, actual, need in short[:3]
        )
        logger.warning(
            "%d escena(s) bajo mínimo de chars (%s) — OK porque audio total %.1fs cumple objetivo",
            len(short),
            samples,
            total_audio_seconds,
        )

    if total_audio_seconds > max_target:
        logger.warning(
            "Audio %.1fs supera --duration-max %ds (tolerancia %.0fs) — "
            "el video se exportará igual; sube --duration-max si quieres alinear objetivos",
            total_audio_seconds,
            config.TARGET_DURATION_MAX_SECONDS,
            max_target,
        )

    logger.info(
        "Validación pre-imágenes OK: %.1fs audio (objetivo %d–%ds)",
        total_audio_seconds,
        config.TARGET_DURATION_MIN_SECONDS,
        config.TARGET_DURATION_MAX_SECONDS,
    )
