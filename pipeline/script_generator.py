"""Module 1: Script generation via Ollama LLM."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from config import PipelineConfig
from pipeline.prompt_loader import format_prompt, load_prompt
from pipeline.topic_loader import TopicBrief

logger = logging.getLogger(__name__)

KEY_MOMENTS = frozenset({"hook", "twist", "closing"})

_WIDE_SUFFIX = ", wide establishing shot, cinematic composition"
_CLOSEUP_SUFFIX = ", close-up detail shot, different angle, shallow depth of field"


def _prompt_text(value: Any) -> str:
    return str(value).strip() if value else ""


def _first_valid_prompt(scene: dict[str, Any]) -> str:
    """Extract the first usable image prompt from common LLM field variants."""
    prompt = _prompt_text(scene.get("image_prompt"))
    if prompt:
        return prompt

    for key in ("image_prompt_1", "visual_prompt", "prompt"):
        prompt = _prompt_text(scene.get(key))
        if prompt:
            return prompt

    prompts = scene.get("image_prompts")
    if isinstance(prompts, list):
        for item in prompts:
            text = _prompt_text(item)
            if text:
                return text

    return ""


def _fallback_prompt_from_narration(narration: str) -> str:
    snippet = narration.strip()[:120].rstrip("., ")
    return (
        f"Cinematic photorealistic true crime scene, {snippet}, "
        "dramatic moody lighting, high detail, 8k"
    )


def _dual_prompts(base: str, key_moment: str) -> list[str]:
    """Build two SDXL prompts from one base prompt for hook/twist/closing."""
    base = base.rstrip("., ")
    if key_moment == "hook":
        return [f"{base}{_WIDE_SUFFIX}", f"{base}{_CLOSEUP_SUFFIX}"]
    if key_moment == "twist":
        return [
            f"{base}, dramatic revelation moment{_WIDE_SUFFIX}",
            f"{base}{_CLOSEUP_SUFFIX}",
        ]
    return [
        f"{base}{_WIDE_SUFFIX}",
        f"{base}, emotional final frame, subtle fade mood",
    ]


def _normalize_scene_images(scenes: list[dict[str, Any]]) -> None:
    """
    Repair missing or inconsistent image fields from LLM output.

    Every scene gets image_prompt. Key moments also get image_prompts (2 shots)
    derived automatically when the model omits or partial-fills them.
    """
    for i, scene in enumerate(scenes, start=1):
        base = _first_valid_prompt(scene)
        if not base:
            base = _fallback_prompt_from_narration(scene.get("narration", ""))
            logger.warning(
                "Escena %d: sin image_prompt — generado automáticamente desde narración",
                i,
            )

        scene["image_prompt"] = base
        key_moment = scene.get("key_moment")

        if key_moment in KEY_MOMENTS:
            existing = scene.get("image_prompts")
            if isinstance(existing, list):
                valid = [_prompt_text(p) for p in existing if _prompt_text(p)]
                if len(valid) >= 2:
                    scene["image_prompts"] = valid[:2]
                    continue
                if len(valid) == 1:
                    scene["image_prompts"] = _dual_prompts(valid[0], key_moment)
                    logger.info(
                        "Escena %d (%s): segundo shot generado desde image_prompts[0]",
                        i,
                        key_moment,
                    )
                    continue

            scene["image_prompts"] = _dual_prompts(base, key_moment)
            logger.info(
                "Escena %d (%s): 2 shots generados desde image_prompt",
                i,
                key_moment,
            )
        else:
            scene.pop("image_prompts", None)


def _normalize_scenes(scenes: list[dict[str, Any]], config: PipelineConfig) -> None:
    """Fix scene numbers and duration hints when the LLM omits them."""
    avg = config.avg_scene_duration_seconds()
    for i, scene in enumerate(scenes, start=1):
        scene["scene_number"] = i
        if "duration_hint" not in scene or not scene["duration_hint"]:
            scene["duration_hint"] = avg


def _normalize_key_moments(scenes: list[dict[str, Any]]) -> None:
    """Assign hook/twist/closing to strategic scenes."""
    n = len(scenes)
    twist_idx = max(1, n // 2)
    if twist_idx >= n - 1:
        twist_idx = max(1, n - 2)

    for i, scene in enumerate(scenes):
        if i == 0:
            scene["key_moment"] = "hook"
        elif i == n - 1:
            scene["key_moment"] = "closing"
        elif i == twist_idx:
            scene["key_moment"] = "twist"
        else:
            scene["key_moment"] = None


def _build_user_prompt(topic: TopicBrief, config: PipelineConfig) -> str:
    """Build the user prompt with duration targets from config."""
    min_scenes, max_scenes = config.scene_count_range()
    target_min = config.TARGET_DURATION_MIN_SECONDS
    target_max = config.TARGET_DURATION_MAX_SECONDS
    target_mid = config.target_duration_mid()
    avg = config.avg_scene_duration_seconds()
    narration_chars_min, narration_chars_max = config.narration_char_bounds()

    return format_prompt(
        load_prompt("script_user", config),
        topic_label=topic.label.strip(),
        topic_brief=topic.brief.strip(),
        target_min=target_min,
        target_max=target_max,
        target_min_minutes=target_min / 60,
        target_max_minutes=target_max / 60,
        target_duration_mid=target_mid,
        min_scenes=min_scenes,
        max_scenes=max_scenes,
        avg_scene_duration=avg,
        narration_chars_min=narration_chars_min,
        narration_chars_max=narration_chars_max,
    )


def _extract_json(text: str) -> str:
    """Strip markdown fences and surrounding whitespace from LLM output."""
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    return cleaned


def normalize_script_scenes(scenes: list[dict[str, Any]], config: PipelineConfig) -> None:
    """Apply all scene normalizers after script load or extension."""
    _normalize_scenes(scenes, config)
    _normalize_key_moments(scenes)
    _normalize_scene_images(scenes)


def extend_script_for_duration(
    existing_scenes: list[dict[str, Any]],
    config: PipelineConfig,
    topic: TopicBrief,
    title: str,
    current_duration: float,
) -> list[dict[str, Any]]:
    """Ask Ollama for extra scenes when TTS audio falls short of duration-min."""
    deficit = config.TARGET_DURATION_MIN_SECONDS - current_duration
    if deficit <= 2:
        return []

    avg = config.avg_scene_duration_seconds()
    extra_count = max(1, min(5, int(deficit / avg) + 1))
    char_min, char_max = config.narration_char_bounds()
    last_n = min(3, len(existing_scenes))
    context = json.dumps(
        existing_scenes[-last_n:],
        ensure_ascii=False,
        indent=2,
    )

    user_prompt = (
        f'Continúa el guión del video "{title}" sobre: {topic.label}\n\n'
        f"CONTEXTO DEL TEMA:\n{topic.brief.strip()}\n\n"
        f"Faltan ~{int(deficit)}s de narración. Añade exactamente {extra_count} escenas NUEVAS.\n"
        f"Cada narration: {char_min}–{char_max} caracteres (español colombiano).\n"
        f"Cada escena: scene_number, narration, image_prompt (inglés), duration_hint.\n"
        f"NO repitas escenas anteriores. Responde SOLO JSON:\n"
        f'{{"scenes": [ ... {extra_count} escenas ... ]}}\n\n'
        f"Contexto (últimas escenas):\n{context}"
    )

    raw = _call_ollama(config, user_prompt)
    parsed = json.loads(_extract_json(raw))
    extra = parsed.get("scenes", parsed if isinstance(parsed, list) else [])
    if not isinstance(extra, list) or not extra:
        raise ValueError("Ollama no devolvió escenas extra válidas")

    start_num = len(existing_scenes) + 1
    for i, scene in enumerate(extra):
        scene["scene_number"] = start_num + i
        if "duration_hint" not in scene:
            scene["duration_hint"] = avg

    logger.info(
        "Añadidas %d escenas extra para cubrir ~%.0fs de déficit",
        len(extra),
        deficit,
    )
    return extra


def _validate_script(data: dict[str, Any], config: PipelineConfig) -> None:
    """Validate script structure, normalize fields, raise ValueError on failure."""
    required_top = {"title", "scenes", "total_estimated_duration"}
    missing = required_top - set(data.keys())
    if missing:
        raise ValueError(f"Faltan campos obligatorios: {missing}")

    scenes = data["scenes"]
    if not isinstance(scenes, list):
        raise ValueError("'scenes' debe ser una lista")

    min_scenes, max_scenes = config.scene_count_range()
    scene_count = len(scenes)
    if not (min_scenes <= scene_count <= max_scenes):
        raise ValueError(
            f"Se requieren entre {min_scenes} y {max_scenes} escenas "
            f"({config.TARGET_DURATION_MIN_SECONDS}–{config.TARGET_DURATION_MAX_SECONDS}s), "
            f"se recibieron {scene_count}"
        )

    target_min = config.TARGET_DURATION_MIN_SECONDS
    target_max = config.TARGET_DURATION_MAX_SECONDS
    tolerance = 0.15
    estimated = data["total_estimated_duration"]
    min_allowed = int(target_min * (1 - tolerance))
    max_allowed = int(target_max * (1 + tolerance))
    if not (min_allowed <= estimated <= max_allowed):
        raise ValueError(
            f"total_estimated_duration debe estar entre {target_min} y {target_max}s "
            f"(±15%), se recibió {estimated}s"
        )

    normalize_script_scenes(scenes, config)

    for i, scene in enumerate(scenes, start=1):
        if not scene.get("narration", "").strip():
            raise ValueError(f"Escena {i}: 'narration' está vacía")
        if not _prompt_text(scene.get("image_prompt")):
            raise ValueError(f"Escena {i}: 'image_prompt' está vacío")


def _ollama_timeout(config: PipelineConfig) -> int:
    """Scale request timeout with expected script length."""
    base = 300
    extra = config.TARGET_DURATION_MAX_SECONDS // 30 * 30
    return min(base + extra, 900)


def _call_ollama(
    config: PipelineConfig,
    user_prompt: str,
    *,
    use_json_format: bool = True,
) -> str:
    """Send a prompt to Ollama chat API and return the raw response text."""
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload: dict[str, Any] = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": load_prompt("script_system", config)},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
    }
    if use_json_format:
        payload["format"] = "json"

    timeout = _ollama_timeout(config)

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


def generate_script(topic: TopicBrief, config: PipelineConfig) -> dict[str, Any]:
    """
    Generate a structured video script using Ollama and a topic brief.

    Returns a dict with title, scenes, and total_estimated_duration.
    """
    if not topic.brief.strip():
        raise ValueError("El brief del topic no puede estar vacío")

    if config.TARGET_DURATION_MIN_SECONDS > config.TARGET_DURATION_MAX_SECONDS:
        raise ValueError(
            "TARGET_DURATION_MIN_SECONDS no puede ser mayor que TARGET_DURATION_MAX_SECONDS"
        )

    user_prompt = _build_user_prompt(topic, config)
    min_scenes, max_scenes = config.scene_count_range()
    logger.info(
        "Objetivo de duración: %d–%ds (%d–%d escenas) | Tema: %s",
        config.TARGET_DURATION_MIN_SECONDS,
        config.TARGET_DURATION_MAX_SECONDS,
        min_scenes,
        max_scenes,
        topic.label,
    )

    last_error = "Respuesta vacía"
    raw = ""

    for attempt in range(3):
        try:
            if attempt == 0:
                raw = _call_ollama(config, user_prompt)
            else:
                correction = format_prompt(
                    load_prompt("script_correction", config),
                    error=last_error,
                    min_scenes=min_scenes,
                    max_scenes=max_scenes,
                )
                raw = _call_ollama(config, f"{user_prompt}\n\n{correction}")

            parsed = json.loads(_extract_json(raw))
            _validate_script(parsed, config)
            logger.info(
                "Guión generado: '%s' (%d escenas, ~%ds)",
                parsed["title"],
                len(parsed["scenes"]),
                parsed["total_estimated_duration"],
            )
            return parsed

        except (json.JSONDecodeError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("Intento %d/3 falló al parsear guión: %s", attempt + 1, last_error)
            if attempt == 0 and "Expecting value" in last_error:
                logger.debug("Respuesta cruda de Ollama: %r", raw[:500] if raw else "(vacía)")

    raise RuntimeError(
        f"No se pudo generar un guión válido después de 3 intentos. Último error: {last_error}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from pipeline.topic_loader import resolve_topic

    cfg = PipelineConfig()
    cfg.resolve_paths()
    brief = resolve_topic("El misterio del vuelo MH370", cfg)
    script = generate_script(brief, cfg)
    print(json.dumps(script, ensure_ascii=False, indent=2))
