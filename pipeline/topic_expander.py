"""Turn a one-line topic into a saved brief, then the video run continues."""

from __future__ import annotations

import logging
import re

from config import PipelineConfig
from pipeline.ollama_client import chat as ollama_chat
from pipeline.topic_loader import TopicBrief, _load_topic_file

logger = logging.getLogger(__name__)

_MIN_BRIEF_CHARS = 400


def needs_brief(topic: TopicBrief) -> bool:
    """A saved file is the brief. A one-line --topic still has to be researched."""
    if topic.source_path is not None:
        return False
    return "\n" not in topic.brief.strip()


def _instruction_prompt(config: PipelineConfig, idea: str) -> str:
    template_path = config.TOPICS_DIR / "topic_template.txt"
    raw = template_path.read_text(encoding="utf-8")
    instructions = raw.split("EJEMPLO DE ESTRUCTURA", 1)[0].strip()
    instructions = instructions.replace("[TU IDEA]", idea.strip())
    return re.sub(
        r"Duración objetivo del video:.*",
        (
            "Duración objetivo del video: "
            f"{config.TARGET_DURATION_MIN_SECONDS}–{config.TARGET_DURATION_MAX_SECONDS} segundos"
        ),
        instructions,
        count=1,
    )


def parse_generated_brief(text: str) -> tuple[str, str]:
    """Return (label, body) starting at TITLE:. Raises ValueError if it is not a brief."""
    cleaned = text.strip()
    fence = re.search(r"```(?:\w+)?\s*([\s\S]*?)```", cleaned)
    if fence:
        cleaned = fence.group(1).strip()

    start = cleaned.find("TITLE:")
    if start < 0:
        raise ValueError("El brief no trae TITLE:")
    cleaned = cleaned[start:]
    line, _, body = cleaned.partition("\n")
    label = line.removeprefix("TITLE:").strip()
    body = body.strip()
    if not label:
        raise ValueError("TITLE está vacío")
    if "Hechos clave" not in body or len(body) < _MIN_BRIEF_CHARS:
        raise ValueError(
            f"Brief incompleto ({len(body)} caracteres, falta el bloque de hechos)"
        )
    return label, body


def expand_inline_topic(topic: TopicBrief, config: PipelineConfig) -> TopicBrief:
    """Research a one-line topic, save assets/topics/<slug>.txt, and keep going."""
    if not needs_brief(topic):
        return topic

    path = config.TOPICS_DIR / f"{topic.key}.txt"
    if path.exists():
        return _load_topic_file(path)

    user_prompt = _instruction_prompt(config, topic.label)
    system = (
        "Escribes briefs de investigación para videos de true crime. "
        "Respondes solo con el brief, empezando por TITLE:. Sin markdown."
    )
    last_error = "respuesta vacía"
    label = ""
    body = ""
    for attempt in range(2):
        prompt = user_prompt
        if attempt:
            prompt = (
                f"{user_prompt}\n\nEl intento anterior no sirve: {last_error}. "
                "Responde de nuevo solo el brief, desde TITLE:."
            )
        raw = ollama_chat(
            config,
            prompt,
            use_json_format=False,
            system_prompt=system,
        )
        try:
            label, body = parse_generated_brief(raw)
            break
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("Brief intento %d/2 falló: %s", attempt + 1, last_error)
    else:
        raise RuntimeError(
            f"No se pudo armar el brief automático. Último error: {last_error}"
        )

    config.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TITLE: {label}\n\n{body}\n", encoding="utf-8")
    logger.info("Brief automático guardado: %s (%d caracteres)", path.name, len(body))
    return TopicBrief(
        key=topic.key,
        label=label,
        brief=body,
        source_path=path.resolve(),
    )
