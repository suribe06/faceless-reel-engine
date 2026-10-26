#!/usr/bin/env python3
"""CLI entry for the faceless video generation pipeline."""

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

    console_handler: logging.Handler
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
        description="Genera videos faceless (true crime / misterio) con Ollama, Kokoro, ComfyUI y FFmpeg.",
    )
    parser.add_argument("--topic", default=None, help="Slug del brief (assets/topics/SLUG.txt) o frase corta")
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
    return parser.parse_args()


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

    log_file = _make_log_file(config.LOG_DIR)
    _setup_logging(log_file)

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

    from pipeline.preflight import run_preflight

    preflight = run_preflight(config)
    if not preflight.ok:
        return 1

    from pipeline.topic_loader import resolve_topic

    topic = resolve_topic(args.topic, config)

    try:
        logger.info("Log de ejecución: %s", log_file)
        logger.info("Tema: %s", topic.label)
        if topic.source_path:
            logger.info("Brief: %s (%d caracteres)", topic.source_path, len(topic.brief))
        else:
            logger.info(
                "Frase corta (%d caracteres) — el pipeline escribe %s/%s.txt y sigue",
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

        from pipeline.orchestrator import run_pipeline

        run_pipeline(
            config,
            topic,
            resume_from=args.resume_from,
            output_name=args.output,
            keep_temp=args.keep_temp,
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
            'temp/ conservado. Reanuda con: python main.py --topic "%s" --resume-from images|video',
            topic.key,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
