"""Persist pipeline state for resume and failure recovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import PipelineConfig

logger = logging.getLogger(__name__)

STATE_FILENAME = "pipeline_state.json"


def state_path(config: PipelineConfig) -> Path:
    return config.TEMP_DIR / STATE_FILENAME


def save_state(
    config: PipelineConfig,
    *,
    topic: str,
    title: str,
    scenes: list[dict[str, Any]],
    step: str,
    topic_label: str | None = None,
    topic_brief: str | None = None,
    topic_file: str | None = None,
) -> None:
    """Write current pipeline progress to temp/."""
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "topic": topic,
        "title": title,
        "scenes": scenes,
        "step": step,
    }
    if topic_label:
        payload["topic_label"] = topic_label
    if topic_brief:
        payload["topic_brief"] = topic_brief
    if topic_file:
        payload["topic_file"] = topic_file
    path = state_path(config)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("Estado guardado: %s (paso %s)", path, step)


def load_state(config: PipelineConfig) -> dict[str, Any] | None:
    path = state_path(config)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("Estado corrupto en %s: %s", path, exc)
        return None
