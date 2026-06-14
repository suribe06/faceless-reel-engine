"""Ollama helper utilities."""

from __future__ import annotations

import logging

import requests

from config import PipelineConfig

logger = logging.getLogger(__name__)


def unload_ollama_model(config: PipelineConfig) -> None:
    """
    Unload the Ollama model from VRAM to free memory for ComfyUI/SDXL.

    Ollama keeps models loaded by default; on 8GB GPUs this blocks SDXL inference.
    """
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": "",
        "keep_alive": 0,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info(
            "Modelo Ollama descargado de VRAM (%s)",
            config.OLLAMA_MODEL,
        )
    except requests.RequestException as exc:
        logger.warning(
            "No se pudo descargar el modelo Ollama de VRAM: %s. "
            "Si ComfyUI falla por OOM, ejecuta: ollama stop && ollama serve",
            exc,
        )
