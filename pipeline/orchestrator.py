"""Run orchestrator: stage order, resume, duration extension, resource release."""

from __future__ import annotations

import logging

from config import PipelineConfig
from pipeline.comfyui_client import release_after_images
from pipeline.duration_policy import needs_extension, validate_before_images
from pipeline.image_generator import generate_images
from pipeline.ollama_client import release_after_script
from pipeline.run_state import RunState, load_run, save_run
from pipeline.script_generator import (
    extend_script_for_duration,
    generate_script,
    normalize_script_scenes,
)
from pipeline.topic_expander import expand_inline_topic, needs_brief
from pipeline.topic_loader import TopicBrief
from pipeline.tts_generator import generate_audio, release_after_tts
from pipeline.video_assembler import assemble_video

logger = logging.getLogger(__name__)


def _ensure_duration_with_extensions(
    run: RunState,
    durations: list[float],
    total_audio: float,
    config: PipelineConfig,
) -> float:
    """Extend script + TTS until measured audio meets min threshold."""
    extensions = 0

    while needs_extension(total_audio, config) and extensions < config.MAX_DURATION_EXTENSIONS:
        deficit = config.TARGET_DURATION_MIN_SECONDS - total_audio
        logger.warning(
            "Narración %.1fs < mínimo %ds (faltan ~%.0fs) — extensión %d/%d",
            total_audio,
            config.TARGET_DURATION_MIN_SECONDS,
            deficit,
            extensions + 1,
            config.MAX_DURATION_EXTENSIONS,
        )
        extra_scenes = extend_script_for_duration(
            run.scenes, config, run.topic, run.title, total_audio
        )
        if not extra_scenes:
            break

        release_after_script(config)
        extra_audio, extra_durs = generate_audio(extra_scenes, config)
        run.scenes.extend(extra_scenes)
        run.audio_files.extend(extra_audio)
        durations.extend(extra_durs)
        normalize_script_scenes(run.scenes, config)
        total_audio = sum(durations)
        extensions += 1
        logger.info(
            "Tras extensión %d: %.1fs (%d escenas)",
            extensions,
            total_audio,
            len(run.scenes),
        )

    return total_audio


def run_pipeline(
    config: PipelineConfig,
    topic: TopicBrief,
    *,
    resume_from: str | None = None,
    output_name: str | None = None,
    keep_temp: bool = False,
) -> str:
    """
    Execute the full pipeline (or resume from tts|images|video).

    Returns the path to the final MP4.
    """
    resume = resume_from

    if resume not in ("tts", "images", "video") and needs_brief(topic):
        logger.info("=== Paso 0: Brief automático desde la frase ===")
        topic = expand_inline_topic(topic, config)

    if resume in ("images", "video"):
        run = load_run(config, fallback_topic=topic.key)
        logger.info("Reanudando desde '%s' (%d escenas)", resume, len(run.scenes))
    else:
        run = RunState(topic=topic, title=output_name or topic.label, scenes=[])

    total_audio = 0.0

    if resume == "video":
        run.bind_audio_paths(config)
        total_audio = run.hydrate_audio_durations()
    elif resume == "images":
        run.bind_audio_paths(config)
        total_audio = run.hydrate_audio_durations()
    else:
        if resume != "tts":
            logger.info("=== Paso 1/4: Generando guión ===")
            script = generate_script(topic, config)
            run.scenes = script["scenes"]
            run.title = script["title"]
            run.step = "script"
            logger.info(
                "Guión: '%s' | %d escenas | ~%ds estimados",
                run.title,
                len(run.scenes),
                script["total_estimated_duration"],
            )
            save_run(config, run)
            release_after_script(config)
        else:
            run = load_run(config, fallback_topic=topic.key)
            logger.info("Reanudando TTS (%d escenas)", len(run.scenes))

        logger.info("=== Paso 2/4: Generando narración TTS ===")
        audio_files, durations = generate_audio(run.scenes, config)
        run.audio_files = audio_files
        total_audio = sum(durations)
        total_audio = _ensure_duration_with_extensions(run, durations, total_audio, config)
        run.step = "tts"
        save_run(config, run)

    if resume != "video":
        logger.info(
            "Audio total: %.1fs (%d archivos)",
            total_audio,
            len(run.audio_files),
        )
        if total_audio < config.TARGET_DURATION_MIN_SECONDS:
            logger.warning(
                "Duración %.1fs sigue bajo mínimo %ds tras %d extensiones",
                total_audio,
                config.TARGET_DURATION_MIN_SECONDS,
                config.MAX_DURATION_EXTENSIONS,
            )
        release_after_tts()

        validate_before_images(run.scenes, config, total_audio)

        logger.info("=== Paso 3/4: Generando imágenes SDXL ===")
        image_count = generate_images(run.scenes, config)
        logger.info(
            "%d imágenes generadas (%d escenas)",
            image_count,
            len(run.scenes),
        )
        run.step = "images"
        save_run(config, run)
        release_after_images(config)

    logger.info("=== Paso 4/4: Ensamblando video ===")
    output_title = output_name or run.title
    video_path = assemble_video(
        run.scenes,
        run.audio_files,
        config,
        title=output_title,
        cleanup_temp=not keep_temp,
    )

    logger.info("=== Pipeline completado ===")
    logger.info("Video final: %s", video_path)
    logger.info(
        "Duración narración: %.1fs (%.1f min) | Escenas: %d | Objetivo: %d–%ds",
        total_audio,
        total_audio / 60,
        len(run.scenes),
        config.TARGET_DURATION_MIN_SECONDS,
        config.TARGET_DURATION_MAX_SECONDS,
    )
    return video_path
