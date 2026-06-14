"""Module 3: Image generation via ComfyUI API."""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from config import PipelineConfig
from pipeline.prompt_loader import load_optional_prompt, load_prompt

logger = logging.getLogger(__name__)


def _negative_prompt(config: PipelineConfig) -> str:
    return load_prompt("image_negative", config)


def _apply_image_style(prompt: str, config: PipelineConfig) -> str:
    suffix = load_optional_prompt("image_style_suffix", config)
    if not suffix:
        return prompt
    return f"{prompt.rstrip().rstrip(',')}, {suffix.lstrip(', ')}"

IMAGE_TIMEOUT_SECONDS = 120


def _format_comfyui_error(messages: Any) -> str:
    """Extract a readable error summary from ComfyUI status messages."""
    if not isinstance(messages, list):
        return str(messages)[:1000]

    for item in messages:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        event, payload = item[0], item[1]
        if event != "execution_error" or not isinstance(payload, dict):
            continue

        node_type = payload.get("node_type", "unknown")
        raw_message = payload.get("exception_message", "error desconocido")
        first_line = raw_message.strip().split("\n", maxsplit=1)[0]
        if "out of memory" in raw_message.lower():
            return (
                f"ComfyUI ({node_type}): {first_line}. "
                "Causa probable: Ollama u otra app usando la GPU. "
                "El pipeline intenta descargar Ollama antes de generar imágenes; "
                "cierra apps pesadas y reinicia ComfyUI con --lowvram."
            )
        return f"ComfyUI ({node_type}): {first_line}"

    return str(messages)[:1000]


def _build_workflow(
    prompt: str,
    negative_prompt: str,
    checkpoint: str,
    width: int,
    height: int,
    seed: int,
    filename_prefix: str,
    steps: int = 20,
) -> dict[str, Any]:
    """Build a ComfyUI API workflow for SDXL image generation."""
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": 7.0,
                "sampler_name": "euler_ancestral",
                "scheduler": "karras",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["6", 0]},
        },
    }


def _queue_prompt(base_url: str, workflow: dict[str, Any], client_id: str) -> str:
    """Submit workflow to ComfyUI and return prompt_id."""
    url = f"{base_url.rstrip('/')}/prompt"
    payload = {"prompt": workflow, "client_id": client_id}

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
    except requests.ConnectionError as exc:
        raise ConnectionError(
            f"No se pudo conectar con ComfyUI en {base_url}. "
            "Verifica que ComfyUI esté corriendo en el puerto 8188."
        ) from exc
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"ComfyUI rechazó el workflow ({response.status_code}): {response.text[:500]}"
        ) from exc

    data = response.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI no retornó prompt_id: {data}")
    return prompt_id


def _wait_for_completion(
    base_url: str,
    prompt_id: str,
    timeout: int = IMAGE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Poll ComfyUI history until the prompt completes or times out."""
    url = f"{base_url.rstrip('/')}/history/{prompt_id}"
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                history = response.json()
                if prompt_id in history:
                    entry = history[prompt_id]
                    status = entry.get("status", {})
                    if status.get("completed"):
                        return entry
                    if status.get("status_str") == "error":
                        messages = status.get("messages", [])
                        summary = _format_comfyui_error(messages)
                        logger.error("ComfyUI detalle completo: %s", messages)
                        raise RuntimeError(summary)
        except requests.RequestException:
            pass
        time.sleep(1)

    raise TimeoutError(
        f"Timeout ({timeout}s) esperando imagen de ComfyUI (prompt_id={prompt_id})"
    )


def _download_image(
    base_url: str,
    history_entry: dict[str, Any],
    dest_path: Path,
) -> None:
    """Download generated image from ComfyUI outputs."""
    outputs = history_entry.get("outputs", {})
    for node_output in outputs.values():
        images = node_output.get("images", [])
        if not images:
            continue

        image_info = images[0]
        params = {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        url = f"{base_url.rstrip('/')}/view"
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        dest_path.write_bytes(response.content)
        return

    raise RuntimeError("ComfyUI completó pero no se encontró imagen en outputs")


def _free_comfyui_vram(base_url: str) -> None:
    """Ask ComfyUI to unload models and free CUDA cache."""
    url = f"{base_url.rstrip('/')}/free"
    try:
        response = requests.post(
            url,
            json={"unload_models": True, "free_memory": True},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("No se pudo liberar VRAM en ComfyUI: %s", exc)


def release_comfyui_resources(config: PipelineConfig) -> None:
    """Unload all ComfyUI models from VRAM after the image phase."""
    _free_comfyui_vram(config.COMFYUI_BASE_URL)
    logger.info("Modelos ComfyUI descargados de VRAM")


def generate_images(
    scenes: list[dict[str, Any]],
    config: PipelineConfig,
) -> int:
    """
    Generate SDXL images for each scene via ComfyUI.

    Key scenes (hook/twist/closing) get 2 images; others get 1.
    Populates scene['image_paths'] on each scene dict.
    Returns total number of images generated.
    """
    from pipeline.comfyui_client import ensure_comfyui_running

    ensure_comfyui_running(config)

    images_dir = config.TEMP_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    client_id = str(uuid.uuid4())
    base_url = config.COMFYUI_BASE_URL
    total_scenes = len(scenes)
    total_images = 0

    for idx, scene in enumerate(scenes, start=1):
        key_moment = scene.get("key_moment")
        if key_moment in {"hook", "twist", "closing"}:
            raw_prompts = scene.get("image_prompts", [])
            prompts = [_apply_image_style(str(p).strip(), config) for p in raw_prompts[:2]]
            labels = ["a", "b"]
        else:
            prompt = _apply_image_style(scene.get("image_prompt", "").strip(), config)
            if not prompt:
                raise ValueError(f"Escena {idx}: image_prompt vacío")
            prompts = [prompt]
            labels = [""]

        scene_paths: list[str] = []
        existing = scene.get("image_paths") or []
        if existing and all(Path(p).exists() for p in existing):
            logger.info("[IMG] Escena %d/%d — omitiendo (resume, %d imágenes)", idx, total_scenes, len(existing))
            total_images += len(existing)
            continue

        for prompt, label in zip(prompts, labels):
            suffix = f"_{label}" if label else ""
            logger.info(
                "[IMG] Escena %d/%d%s (%s) %dx%d...",
                idx,
                total_scenes,
                f" shot {label}" if label else "",
                key_moment or "normal",
                config.COMFYUI_IMAGE_WIDTH,
                config.COMFYUI_IMAGE_HEIGHT,
            )

            _free_comfyui_vram(base_url)

            seed = random.randint(0, 2**32 - 1)
            prefix = f"scene_{idx}{suffix}_{seed}"
            dest = images_dir / f"scene_{idx}{suffix}.png"
            workflow = _build_workflow(
                prompt=prompt,
                negative_prompt=_negative_prompt(config),
                checkpoint=config.SDXL_CHECKPOINT,
                width=config.COMFYUI_IMAGE_WIDTH,
                height=config.COMFYUI_IMAGE_HEIGHT,
                seed=seed,
                filename_prefix=prefix,
                steps=config.COMFYUI_STEPS,
            )

            last_error = ""
            for attempt in range(1, config.COMFYUI_IMAGE_RETRIES + 1):
                try:
                    prompt_id = _queue_prompt(base_url, workflow, client_id)
                    history = _wait_for_completion(base_url, prompt_id)
                    _download_image(base_url, history, dest)
                    break
                except (TimeoutError, RuntimeError, requests.RequestException) as exc:
                    last_error = str(exc)
                    if attempt >= config.COMFYUI_IMAGE_RETRIES:
                        raise RuntimeError(
                            f"Escena {idx} falló tras {config.COMFYUI_IMAGE_RETRIES} intentos: {last_error}"
                        ) from exc
                    logger.warning(
                        "[IMG] Escena %d intento %d/%d falló: %s — reintentando",
                        idx,
                        attempt,
                        config.COMFYUI_IMAGE_RETRIES,
                        last_error,
                    )
                    _free_comfyui_vram(base_url)

            scene_paths.append(str(dest))
            total_images += 1

            logger.info("[IMG] Guardada: %s", dest.name)
            _free_comfyui_vram(base_url)

        scene["image_paths"] = scene_paths

    return total_images


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cfg = PipelineConfig()
    cfg.resolve_paths()
    cfg.ensure_directories()

    sample = [
        {
            "scene_number": 1,
            "narration": "test",
            "image_prompt": (
                "abandoned courthouse at night, dramatic lighting, photorealistic, "
                "cinematic mood, 8k detail"
            ),
            "duration_hint": 5,
        }
    ]
    paths = generate_images(sample, cfg)
    print(f"Imagen generada: {sample[0]['image_paths'][0]}")
