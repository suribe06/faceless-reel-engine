"""Pre-flight checks before starting the pipeline."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field

import requests

from config import PipelineConfig

logger = logging.getLogger(__name__)


@dataclass
class PreflightResult:
    """Outcome of startup checks."""

    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _check_command(name: str, cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, capture_output=True, check=False, timeout=10)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.error("No se encontró %s en PATH", name)
        return False


def run_preflight(config: PipelineConfig) -> PreflightResult:
    """Verify dependencies, services, and assets before a long run."""
    result = PreflightResult()

    if not _check_command("ffmpeg", ["ffmpeg", "-version"]):
        result.errors.append("ffmpeg no instalado (requerido para ensamblar el video)")
        result.ok = False

    if not _check_command("espeak-ng", ["espeak-ng", "--version"]):
        result.warnings.append(
            "espeak-ng no detectado — Kokoro TTS puede fallar (sudo apt install espeak-ng)"
        )

    try:
        url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            result.errors.append(f"Ollama no responde en {config.OLLAMA_BASE_URL}")
            result.ok = False
        else:
            models = {m.get("name", "") for m in response.json().get("models", [])}
            if config.OLLAMA_MODEL not in models and f"{config.OLLAMA_MODEL}:latest" not in models:
                result.warnings.append(
                    f"Modelo {config.OLLAMA_MODEL} no listado en Ollama — "
                    f"ejecuta: ollama pull {config.OLLAMA_MODEL}"
                )
    except requests.RequestException:
        result.errors.append(f"Ollama no alcanzable en {config.OLLAMA_BASE_URL}")
        result.ok = False

    if not config.LOGO_PATH.exists():
        result.warnings.append(f"Logo no encontrado: {config.LOGO_PATH} (video sin marca de agua)")

    default_track = config.ASSETS_MUSIC_DIR / config.DEFAULT_MUSIC_FILE
    if not default_track.exists() and config.MUSIC_MODE == "default":
        result.warnings.append(
            f"Pista default no encontrada: {default_track}. "
            f"Ejecuta: python scripts/download_music.py"
        )

    music_dir = config.ASSETS_MUSIC_DIR
    tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.MP3"))
    if len(tracks) < config.MUSIC_MIN_TRACKS:
        result.warnings.append(
            f"Solo {len(tracks)} pistas en {music_dir} "
            f"(recomendado ≥{config.MUSIC_MIN_TRACKS}). "
            "Ejecuta: python scripts/download_music.py"
        )
    else:
        logger.info("Música de fondo: %d pistas disponibles", len(tracks))

    if result.errors:
        for err in result.errors:
            logger.error("[preflight] %s", err)
    for warn in result.warnings:
        logger.warning("[preflight] %s", warn)

    if result.ok:
        logger.info("Pre-flight OK")
    return result
