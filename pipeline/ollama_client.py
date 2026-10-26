"""Ollama adapter: chat + VRAM unload."""

from __future__ import annotations

import gc
import logging
from typing import Any

import requests

from config import PipelineConfig
from pipeline.prompt_loader import load_prompt

logger = logging.getLogger(__name__)


def _gc_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except ImportError:
        pass


def chat_timeout(config: PipelineConfig) -> int:
    """Scale request timeout with expected script length."""
    base = 300
    extra = config.TARGET_DURATION_MAX_SECONDS // 30 * 30
    return min(base + extra, 900)


def chat(
    config: PipelineConfig,
    user_prompt: str,
    *,
    use_json_format: bool = True,
    system_prompt: str | None = None,
) -> str:
    """Send a prompt to Ollama chat API and return the raw response text."""
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    system = system_prompt if system_prompt is not None else load_prompt("script_system", config)
    payload: dict[str, Any] = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
    }
    if use_json_format:
        payload["format"] = "json"

    timeout = chat_timeout(config)

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.ConnectionError as exc:
        raise ConnectionError(
            f"No se pudo conectar con Ollama en {config.OLLAMA_BASE_URL}. "
            "Verifica que Ollama esté corriendo."
        ) from exc
    except requests.Timeout as exc:
        raise TimeoutError(
            f"Timeout al generar guión con Ollama (modelo: {config.OLLAMA_MODEL}, "
            f"{timeout}s). Prueba un rango de duración más corto o "
            f"`ollama pull {config.OLLAMA_MODEL}`."
        ) from exc
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Error HTTP de Ollama ({response.status_code}): {response.text[:500]}"
        ) from exc

    body = response.json()
    if body.get("error"):
        raise RuntimeError(
            f"Ollama error (modelo: {config.OLLAMA_MODEL}): {body['error']}. "
            f"Verifica que el modelo esté instalado: `ollama pull {config.OLLAMA_MODEL}`"
        )

    message = body.get("message", {})
    content = (message.get("content") or "").strip()

    if not content:
        thinking = (message.get("thinking") or "").strip()
        if thinking:
            raise RuntimeError(
                f"Ollama devolvió respuesta vacía. El modelo {config.OLLAMA_MODEL} "
                "usó modo thinking sin generar JSON. Esto ya debería estar corregido; "
                "reintenta o prueba otro modelo."
            )
        raise RuntimeError(
            f"Ollama devolvió respuesta vacía para el modelo {config.OLLAMA_MODEL}."
        )

    return content


def unload_ollama_model(config: PipelineConfig) -> None:
    """Unload the Ollama model from VRAM to free memory for ComfyUI/SDXL."""
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload: dict[str, Any] = {
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


def release_after_script(config: PipelineConfig) -> None:
    """Unload Ollama after script generation."""
    logger.info("--- Liberando recursos del paso 1 (Ollama) ---")
    unload_ollama_model(config)
    _gc_gpu()
