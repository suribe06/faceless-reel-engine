"""Sequential resource lifecycle — release GPU/RAM after each pipeline phase."""

from __future__ import annotations

import gc
import logging

from config import PipelineConfig

logger = logging.getLogger(__name__)


def _gc_gpu() -> None:
    """Run Python GC and clear PyTorch CUDA cache if available."""
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except ImportError:
        pass


def release_after_script(config: PipelineConfig) -> None:
    """Unload Ollama model from VRAM after script generation."""
    from pipeline.ollama_client import unload_ollama_model

    logger.info("--- Liberando recursos del paso 1 (Ollama) ---")
    unload_ollama_model(config)
    _gc_gpu()


def release_after_tts() -> None:
    """Release Kokoro TTS models from memory after audio generation."""
    from pipeline.tts_generator import release_tts_resources

    logger.info("--- Liberando recursos del paso 2 (Kokoro TTS) ---")
    release_tts_resources()
    _gc_gpu()


def release_after_images(config: PipelineConfig) -> None:
    """Unload ComfyUI models from VRAM after image generation."""
    from pipeline.image_generator import release_comfyui_resources

    logger.info("--- Liberando recursos del paso 3 (ComfyUI) ---")
    release_comfyui_resources(config)
    _gc_gpu()
