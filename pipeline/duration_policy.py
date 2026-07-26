"""Single owner for 'is the video long enough?' policy."""

from __future__ import annotations

import logging
from typing import Any

from config import PipelineConfig

logger = logging.getLogger(__name__)

# Measured TTS must reach this fraction of duration-min before ComfyUI / extend loop
AUDIO_MIN_FACTOR = 0.97
# Soft warning when measured TTS exceeds duration-max by this factor
AUDIO_MAX_FACTOR = 1.08
# LLM estimate gate (± fraction of target range)
ESTIMATE_TOLERANCE = 0.15
# Soft char hint once audio exists (not a hard gate)
CHAR_MIN_TOLERANCE = 0.92


def min_audio_seconds(config: PipelineConfig) -> float:
    return config.TARGET_DURATION_MIN_SECONDS * AUDIO_MIN_FACTOR


def max_audio_seconds(config: PipelineConfig) -> float:
    return config.TARGET_DURATION_MAX_SECONDS * AUDIO_MAX_FACTOR


def estimate_bounds(config: PipelineConfig) -> tuple[int, int]:
    """Allowed total_estimated_duration range from the LLM."""
    target_min = config.TARGET_DURATION_MIN_SECONDS
    target_max = config.TARGET_DURATION_MAX_SECONDS
    min_allowed = int(target_min * (1 - ESTIMATE_TOLERANCE))
    max_allowed = int(target_max * (1 + ESTIMATE_TOLERANCE))
    return min_allowed, max_allowed


def validate_estimated_duration(estimated: float, config: PipelineConfig) -> None:
    min_allowed, max_allowed = estimate_bounds(config)
    if not (min_allowed <= estimated <= max_allowed):
        raise ValueError(
            f"total_estimated_duration debe estar entre "
            f"{config.TARGET_DURATION_MIN_SECONDS} y "
            f"{config.TARGET_DURATION_MAX_SECONDS}s "
            f"(±{int(ESTIMATE_TOLERANCE * 100)}%), se recibió {estimated}s"
        )


def needs_extension(total_audio: float, config: PipelineConfig) -> bool:
    return total_audio < min_audio_seconds(config)


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
    Block ComfyUI only when measured TTS misses the min threshold.

    Per-scene char counts are hints once audio exists, not hard gates.
    """
    min_target = min_audio_seconds(config)
    max_target = max_audio_seconds(config)

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
