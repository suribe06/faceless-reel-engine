"""Image generation domain: SDXL prompts + ComfyUI workflow — transport via comfyui_client."""

from __future__ import annotations

import logging
import random
import uuid
from pathlib import Path
from typing import Any

import requests

from config import PipelineConfig
from pipeline import comfyui_client
from pipeline.prompt_loader import load_optional_prompt, load_prompt
from pipeline.run_state import is_key_moment

logger = logging.getLogger(__name__)


def _negative_prompt(config: PipelineConfig) -> str:
    return load_prompt("image_negative", config)


def _apply_image_style(prompt: str, config: PipelineConfig) -> str:
    suffix = load_optional_prompt("image_style_suffix", config)
    if not suffix:
        return prompt
    return f"{prompt.rstrip().rstrip(',')}, {suffix.lstrip(', ')}"


def sampling_params(config: PipelineConfig) -> tuple[int, float, str, str]:
    """Steps, CFG, sampler, scheduler.

    shortcut: a checkpoint whose name contains lightning/hyper/turbo uses the
    4–8 step recipe. Full RealVisXL at 4 steps looks broken; drop the filename
    match when you want an explicit flag.
    """
    name = config.SDXL_CHECKPOINT.lower()
    if any(tag in name for tag in ("lightning", "hyper", "turbo")):
        return 6, 1.5, "euler", "sgm_uniform"
    return (
        config.COMFYUI_STEPS,
        config.COMFYUI_CFG,
        config.COMFYUI_SAMPLER,
        config.COMFYUI_SCHEDULER,
    )


def shot_seed(base_seed: int, scene_index: int, shot_index: int) -> int:
    """Stable seed per shot so a resume does not reshuffle the whole film."""
    return (base_seed + scene_index * 1009 + shot_index * 17) % (2**32)


def _build_workflow(
    prompt: str,
    negative_prompt: str,
    checkpoint: str,
    width: int,
    height: int,
    seed: int,
    filename_prefix: str,
    steps: int = 20,
    cfg: float = 6.0,
    sampler: str = "dpmpp_2m",
    scheduler: str = "karras",
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
                "cfg": cfg,
                "sampler_name": sampler,
                "scheduler": scheduler,
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


def release_comfyui_resources(config: PipelineConfig) -> None:
    """Unload ComfyUI models — delegates to adapter."""
    comfyui_client.release_comfyui_resources(config)


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
    comfyui_client.ensure_comfyui_running(config)

    images_dir = config.TEMP_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    client_id = str(uuid.uuid4())
    base_url = config.COMFYUI_BASE_URL
    total_scenes = len(scenes)
    total_images = 0
    steps, cfg, sampler, scheduler = sampling_params(config)
    base_seed = (
        config.COMFYUI_SEED % (2**32)
        if config.COMFYUI_SEED >= 0
        else random.randint(0, 2**32 - 1)
    )
    logger.info(
        "SDXL %s | %d steps cfg %.1f %s/%s | seed base %d",
        config.SDXL_CHECKPOINT,
        steps,
        cfg,
        sampler,
        scheduler,
        base_seed,
    )
    model_cleared = False

    for idx, scene in enumerate(scenes, start=1):
        key_moment = scene.get("key_moment")
        if is_key_moment(key_moment):
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
            # Keep image_paths on the scene so resume/assemble never lose them
            scene["image_paths"] = list(existing)
            logger.info(
                "[IMG] Escena %d/%d — omitiendo (resume, %d imágenes)",
                idx,
                total_scenes,
                len(existing),
            )
            total_images += len(existing)
            continue

        for shot_index, (prompt, label) in enumerate(zip(prompts, labels)):
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

            # One unload before the batch so a leftover model does not sit next
            # to SDXL. Keeping the checkpoint loaded between shots is the
            # difference between ~15s and a full reload on every still.
            if not model_cleared:
                comfyui_client.free_vram(base_url)
                model_cleared = True

            seed = shot_seed(base_seed, idx, shot_index)
            prefix = f"scene_{idx}{suffix}_{seed}"
            dest = images_dir / f"scene_{idx}{suffix}.png"

            last_error = ""
            for attempt in range(1, config.COMFYUI_IMAGE_RETRIES + 1):
                workflow = _build_workflow(
                    prompt=prompt,
                    negative_prompt=_negative_prompt(config),
                    checkpoint=config.SDXL_CHECKPOINT,
                    width=config.COMFYUI_IMAGE_WIDTH,
                    height=config.COMFYUI_IMAGE_HEIGHT,
                    seed=seed + attempt - 1,
                    filename_prefix=prefix,
                    steps=steps,
                    cfg=cfg,
                    sampler=sampler,
                    scheduler=scheduler,
                )
                try:
                    prompt_id = comfyui_client.queue_prompt(base_url, workflow, client_id)
                    history = comfyui_client.wait_for_completion(base_url, prompt_id)
                    comfyui_client.download_image(base_url, history, dest)
                    break
                except (TimeoutError, RuntimeError, requests.RequestException) as exc:
                    last_error = str(exc)
                    if attempt >= config.COMFYUI_IMAGE_RETRIES:
                        raise RuntimeError(
                            f"Escena {idx} falló tras {config.COMFYUI_IMAGE_RETRIES} "
                            f"intentos: {last_error}"
                        ) from exc
                    logger.warning(
                        "[IMG] Escena %d intento %d/%d falló: %s — reintentando",
                        idx,
                        attempt,
                        config.COMFYUI_IMAGE_RETRIES,
                        last_error,
                    )
                    comfyui_client.free_vram(base_url)

            scene_paths.append(str(dest))
            total_images += 1

            logger.info("[IMG] Guardada: %s", dest.name)

        scene["image_paths"] = scene_paths

    return total_images


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cfg = PipelineConfig()
    cfg.resolve_paths()
    cfg.ensure_directories()

    sample: list[dict[str, Any]] = [
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
    generate_images(sample, cfg)
    print(f"Imagen generada: {sample[0]['image_paths'][0]}")
