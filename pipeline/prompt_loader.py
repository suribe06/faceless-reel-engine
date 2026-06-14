"""Load editable prompt templates from the prompts/ directory."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from config import PipelineConfig

logger = logging.getLogger(__name__)


def _prompts_dir(config: PipelineConfig) -> Path:
    return config.PROMPTS_DIR


@lru_cache(maxsize=32)
def _read_prompt_file(path_str: str) -> str:
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"Prompt no encontrado: {path}")
    return path.read_text(encoding="utf-8").strip()


def load_prompt(name: str, config: PipelineConfig) -> str:
    """
    Load a prompt template from prompts/{name}.md.

    Files are cached in memory for the process lifetime.
    Restart the pipeline after editing prompts to reload them.
    """
    path = _prompts_dir(config) / f"{name}.md"
    return _read_prompt_file(str(path.resolve()))


def format_prompt(template: str, **kwargs: object) -> str:
    """Fill placeholders in a prompt template."""
    return template.format(**kwargs)


def load_optional_prompt(name: str, config: PipelineConfig) -> str:
    """Load a prompt file if it exists; return empty string otherwise."""
    path = _prompts_dir(config) / f"{name}.md"
    if not path.exists():
        return ""
    content = load_prompt(name, config)
    if content.startswith("<!-- optional -->"):
        content = content.replace("<!-- optional -->", "", 1).strip()
    return content
