#!/usr/bin/env python3
"""Main orchestrator for the faceless video generation pipeline."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

from config import PipelineConfig

PROJECT_ROOT = Path(__file__).resolve().parent


def _make_log_file(log_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir / f"run_{timestamp}.log"


def _setup_logging(log_file: Path, *, use_rich: bool = True) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    root.addHandler(file_handler)

    if use_rich:
        try:
            from rich.logging import RichHandler

            console_handler = RichHandler(rich_tracebacks=True, show_path=False)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(logging.Formatter("%(message)s"))
            root.addHandler(console_handler)
            return
        except ImportError:
            pass

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(file_formatter)
    root.addHandler(console_handler)


def _write_error_snapshot(log_file: Path, exc: BaseException) -> Path:
    error_log = log_file.parent / "latest_error.log"
    error_log.write_text(
        "\n".join(
            [
                f"Timestamp: {datetime.now().isoformat(timespec='seconds')}",
                f"Log completo: {log_file}",
                "",
                f"{type(exc).__name__}: {exc}",
                "",
                traceback.format_exc(),
            ]
        ),
        encoding="utf-8",
    )
    return error_log


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera videos faceless (true crime / misterio) con Ollama, Kokoro, ComfyUI y MoviePy.",
    )
    parser.add_argument("--topic", default=None, help='Slug del brief (assets/topics/SLUG.txt) o frase corta')
    parser.add_argument(
        "--list-topics",
        action="store_true",
        help="Lista los briefs disponibles en assets/topics/ y sale",
    )
    parser.add_argument("--model", default=None, help="Modelo Ollama")
    parser.add_argument(
        "--duration-min",
        type=int,
        default=None,
        metavar="SEC",
        help="Duración mínima objetivo (default: 180)",
    )
    parser.add_argument(
        "--duration-max",
        type=int,
        default=None,
        metavar="SEC",
        help="Duración máxima objetivo (default: 240)",
    )
    parser.add_argument("--voice", default=None, help="Voz Kokoro TTS")
    parser.add_argument("--output", default=None, help="Nombre de salida (sin extensión)")
    parser.add_argument("--checkpoint", default=None, help="Checkpoint SDXL")
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="No eliminar archivos temporales al finalizar",
    )
    parser.add_argument(
        "--resume-from",
        choices=["tts", "images", "video"],
        default=None,
        help="Reanudar desde temp/pipeline_state.json (tts|images|video)",
    )
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Desactivar subtítulos quemados desde el guión",
    )
    parser.add_argument(
        "--video-engine",
        choices=["ffmpeg", "moviepy"],
        default=None,
        help="Motor de ensamblado (default: ffmpeg — mucho más rápido)",
    )
    return parser.parse_args()


def _load_saved_run(config: PipelineConfig, resume_from: str) -> dict:
    from pipeline.state import load_state

    state = load_state(config)
    if not state or not state.get("scenes"):
        raise FileNotFoundError(
            f"No hay estado guardado en {config.TEMP_DIR}/pipeline_state.json. "
            "Ejecuta un run completo primero o usa --keep-temp."
        )
    return state


def _audio_paths_for_scenes(config: PipelineConfig, n: int) -> list[str]:
    audio_dir = config.TEMP_DIR / "audio"
    paths = [str(audio_dir / f"scene_{i}.wav") for i in range(1, n + 1)]
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(
            f"Faltan audios en temp/audio ({len(missing)} archivos). "
            "Reanuda desde un paso anterior o regenera TTS."
        )
    return paths


def _topic_from_saved(saved: dict, fallback: str) -> "TopicBrief":
    from pipeline.topic_loader import TopicBrief

    return TopicBrief.from_saved(
        topic=saved.get("topic", fallback),
        title=saved.get("title"),
        topic_label=saved.get("topic_label"),
        topic_brief=saved.get("topic_brief"),
        topic_file=saved.get("topic_file"),
    )


def _state_topic_fields(topic: "TopicBrief") -> dict[str, str]:
    fields = {
        "topic": topic.key,
        "topic_label": topic.label,
        "topic_brief": topic.brief,
    }
    if topic.source_path:
        fields["topic_file"] = str(topic.source_path)
    return fields


def _ensure_duration_with_extensions(
    scenes: list,
    audio_files: list,
    durations: list,
    total_audio: float,
    config: PipelineConfig,
    topic: "TopicBrief",
    title: str,
    logger: logging.Logger,
) -> tuple[list, list, list, float]:
    from pipeline.resources import release_after_script
    from pipeline.script_generator import extend_script_for_duration, normalize_script_scenes
    from pipeline.tts_generator import generate_audio

    target = config.TARGET_DURATION_MIN_SECONDS * 0.97
    extensions = 0

    while total_audio < target and extensions < config.MAX_DURATION_EXTENSIONS:
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
            scenes, config, topic, title, total_audio
        )
        if not extra_scenes:
            break

        release_after_script(config)
        extra_audio, extra_durs = generate_audio(extra_scenes, config)
        scenes.extend(extra_scenes)
        audio_files.extend(extra_audio)
        durations.extend(extra_durs)
        normalize_script_scenes(scenes, config)
        total_audio = sum(durations)
        extensions += 1
        logger.info("Tras extensión %d: %.1fs (%d escenas)", extensions, total_audio, len(scenes))

    return scenes, audio_files, durations, total_audio


def main() -> int:
    args = _parse_args()

    config = PipelineConfig()
    config.resolve_paths(PROJECT_ROOT)
    config.ensure_directories()

    if args.list_topics:
        from pipeline.topic_loader import list_topic_keys

        keys = list_topic_keys(config)
        if not keys:
            print(f"No hay briefs en {config.TOPICS_DIR}/")
            print("Crea archivos .txt con contexto detallado del video.")
            return 0
        print(f"Briefs en {config.TOPICS_DIR}/:\n")
        for key in keys:
            print(f"  {key}")
        print('\nUso: python main.py --topic "SLUG" ...')
        return 0

    if not args.topic:
        print("Error: indica --topic SLUG o --list-topics", file=sys.stderr)
        return 1

    if args.no_subtitles:
        config.SUBTITLES_ENABLED = False
    if args.video_engine:
        config.VIDEO_ENGINE = args.video_engine

    log_file = _make_log_file(config.LOG_DIR)
    _setup_logging(log_file)

    from pipeline.image_generator import generate_images
    from pipeline.preflight import run_preflight
    from pipeline.resources import (
        release_after_images,
        release_after_script,
        release_after_tts,
    )
    from pipeline.script_generator import generate_script, normalize_script_scenes
    from pipeline.script_validator import validate_before_images
    from pipeline.state import save_state
    from pipeline.tts_generator import generate_audio
    from pipeline.video_assembler import assemble_video

    if args.model:
        config.OLLAMA_MODEL = args.model
    if args.voice:
        config.TTS_VOICE = args.voice
    if args.checkpoint:
        config.SDXL_CHECKPOINT = args.checkpoint
    if args.duration_min is not None:
        config.TARGET_DURATION_MIN_SECONDS = args.duration_min
    if args.duration_max is not None:
        config.TARGET_DURATION_MAX_SECONDS = args.duration_max

    logger = logging.getLogger("main")

    if config.TARGET_DURATION_MIN_SECONDS > config.TARGET_DURATION_MAX_SECONDS:
        logger.error(
            "duration-min (%ds) no puede ser mayor que duration-max (%ds)",
            config.TARGET_DURATION_MIN_SECONDS,
            config.TARGET_DURATION_MAX_SECONDS,
        )
        return 1

    preflight = run_preflight(config)
    if not preflight.ok:
        return 1

    keep_temp = args.keep_temp
    from pipeline.topic_loader import resolve_topic

    topic = resolve_topic(args.topic, config)

    try:
        logger.info("Log de ejecución: %s", log_file)
        logger.info("Tema: %s", topic.label)
        if topic.source_path:
            logger.info("Brief: %s (%d caracteres)", topic.source_path, len(topic.brief))
        else:
            logger.info(
                "Brief inline (%d caracteres) — considera crear %s/%s.txt",
                len(topic.brief),
                config.TOPICS_DIR.name,
                topic.key,
            )
        logger.info(
            "Duración objetivo: %d–%ds (%.1f–%.1f min)",
            config.TARGET_DURATION_MIN_SECONDS,
            config.TARGET_DURATION_MAX_SECONDS,
            config.TARGET_DURATION_MIN_SECONDS / 60,
            config.TARGET_DURATION_MAX_SECONDS / 60,
        )

        resume = args.resume_from
        if resume in ("images", "video"):
            saved = _load_saved_run(config, resume)
            scenes = saved["scenes"]
            title = saved.get("title", args.output or "video")
            topic = _topic_from_saved(saved, args.topic)
            logger.info("Reanudando desde '%s' (%d escenas)", resume, len(scenes))
        else:
            scenes = []
            title = args.output or topic.label

        topic_fields = _state_topic_fields(topic)

        if resume == "video":
            audio_files = _audio_paths_for_scenes(config, len(scenes))
            import soundfile as sf

            total_audio = 0.0
            for i, (scene, path) in enumerate(zip(scenes, audio_files), start=1):
                dur = scene.get("audio_duration") or sf.info(path).duration
                scene["audio_duration"] = dur
                total_audio += dur
        elif resume == "images":
            audio_files = _audio_paths_for_scenes(config, len(scenes))
            import soundfile as sf

            total_audio = 0.0
            for scene, path in zip(scenes, audio_files):
                dur = float(scene.get("audio_duration") or sf.info(path).duration)
                scene["audio_duration"] = dur
                total_audio += dur
        else:
            if resume != "tts":
                logger.info("=== Paso 1/4: Generando guión ===")
                script = generate_script(topic, config)
                scenes = script["scenes"]
                title = script["title"]
                logger.info(
                    "Guión: '%s' | %d escenas | ~%ds estimados",
                    title,
                    len(scenes),
                    script["total_estimated_duration"],
                )
                save_state(
                    config,
                    title=title,
                    scenes=scenes,
                    step="script",
                    **topic_fields,
                )
                release_after_script(config)
            else:
                saved = _load_saved_run(config, "tts")
                scenes = saved["scenes"]
                title = saved.get("title", title)
                topic = _topic_from_saved(saved, args.topic)
                topic_fields = _state_topic_fields(topic)
                logger.info("Reanudando TTS (%d escenas)", len(scenes))

            logger.info("=== Paso 2/4: Generando narración TTS ===")
            audio_files, durations = generate_audio(scenes, config)
            total_audio = sum(durations)
            scenes, audio_files, durations, total_audio = _ensure_duration_with_extensions(
                scenes, audio_files, durations, total_audio, config, topic, title, logger
            )
            save_state(config, title=title, scenes=scenes, step="tts", **topic_fields)

        if resume != "video":
            logger.info(
                "Audio total: %.1fs (%d archivos)",
                total_audio,
                len(audio_files),
            )
            if total_audio < config.TARGET_DURATION_MIN_SECONDS:
                logger.warning(
                    "Duración %.1fs sigue bajo mínimo %ds tras %d extensiones",
                    total_audio,
                    config.TARGET_DURATION_MIN_SECONDS,
                    config.MAX_DURATION_EXTENSIONS,
                )
            release_after_tts()

            validate_before_images(scenes, config, total_audio)

            logger.info("=== Paso 3/4: Generando imágenes SDXL ===")
            image_count = generate_images(scenes, config)
            logger.info(
                "%d imágenes generadas (%d escenas)",
                image_count,
                len(scenes),
            )
            save_state(config, title=title, scenes=scenes, step="images", **topic_fields)
            release_after_images(config)

        logger.info("=== Paso 4/4: Ensamblando video ===")
        output_title = args.output or title
        video_path = assemble_video(
            scenes,
            audio_files,
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
            len(scenes),
            config.TARGET_DURATION_MIN_SECONDS,
            config.TARGET_DURATION_MAX_SECONDS,
        )
        return 0

    except KeyboardInterrupt:
        logger.warning("Pipeline cancelado — temp/ conservado para reanudar con --resume-from")
        return 130
    except Exception as exc:
        logger.exception("Pipeline falló: %s", exc)
        error_log = _write_error_snapshot(log_file, exc)
        logger.error("Error guardado en: %s", error_log)
        logger.error("Log completo en: %s", log_file)
        logger.error(
            "temp/ conservado. Reanuda con: python main.py --topic \"%s\" --resume-from images|video",
            topic.key,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
