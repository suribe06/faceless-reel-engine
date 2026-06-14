"""Load detailed video briefs from assets/topics/*.txt."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from config import PipelineConfig

logger = logging.getLogger(__name__)

_TITLE_PREFIX = re.compile(r"^(?:#\s*title:|title:)\s*(.+)$", re.IGNORECASE)

# Plantillas y archivos auxiliares — no son topics ejecutables
_SKIP_TOPIC_STEMS = frozenset({"topic_template"})


def _is_pipeline_topic_file(path: Path) -> bool:
    if path.stem in _SKIP_TOPIC_STEMS:
        return False
    if path.name.startswith("_"):
        return False
    return True


@dataclass(frozen=True)
class TopicBrief:
    """Resolved topic: short label + detailed brief for script generation."""

    key: str
    label: str
    brief: str
    source_path: Path | None = None

    @classmethod
    def from_inline(cls, text: str) -> TopicBrief:
        text = text.strip()
        if not text:
            raise ValueError("El topic no puede estar vacío")
        key = _slugify(text)[:80] or "topic"
        return cls(key=key, label=text, brief=text, source_path=None)

    @classmethod
    def from_saved(
        cls,
        *,
        topic: str,
        title: str | None = None,
        topic_label: str | None = None,
        topic_brief: str | None = None,
        topic_file: str | None = None,
    ) -> TopicBrief:
        label = (topic_label or title or topic).strip()
        brief = (topic_brief or topic).strip()
        path = Path(topic_file) if topic_file else None
        return cls(
            key=_slugify(topic)[:80] or "topic",
            label=label or topic,
            brief=brief or topic,
            source_path=path if path and path.exists() else None,
        )


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = ascii_text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def _parse_topic_file(path: Path) -> tuple[str, str]:
    """Return (label, brief) from a topic .txt file."""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"El archivo de topic está vacío: {path}")

    lines = raw.splitlines()
    label: str | None = None
    body_start = 0

    for i, line in enumerate(lines):
        match = _TITLE_PREFIX.match(line.strip())
        if match:
            label = match.group(1).strip()
            body_start = i + 1
            break

    body = "\n".join(lines[body_start:]).strip()
    if not body:
        body = raw
    if not label:
        label = path.stem.replace("-", " ").replace("_", " ")

    return label, body


def _reject_template_path(path: Path) -> None:
    if not _is_pipeline_topic_file(path):
        raise ValueError(
            f"'{path.name}' es una plantilla o archivo auxiliar, no un topic ejecutable. "
            "Copia la plantilla con otro nombre (ej. assets/topics/mi-caso.txt) "
            "o usa --list-topics para ver briefs válidos."
        )


def _load_topic_file(path: Path) -> TopicBrief:
    _reject_template_path(path)
    label, brief = _parse_topic_file(path)
    return TopicBrief(
        key=path.stem,
        label=label,
        brief=brief,
        source_path=path.resolve(),
    )


def list_topic_keys(config: PipelineConfig) -> list[str]:
    """Return sorted topic slugs (filenames without .txt)."""
    topics_dir = config.TOPICS_DIR
    if not topics_dir.exists():
        return []
    return sorted(
        p.stem for p in topics_dir.glob("*.txt") if _is_pipeline_topic_file(p)
    )


def resolve_topic(topic_arg: str, config: PipelineConfig) -> TopicBrief:
    """
    Resolve a CLI topic argument to a TopicBrief.

    Lookup order:
    1. Path to an existing .txt file
    2. assets/topics/{topic_arg}.txt
    3. assets/topics/{slugify(topic_arg)}.txt
    4. Inline brief (legacy one-line topic)
    """
    topic_arg = topic_arg.strip()
    if not topic_arg:
        raise ValueError("El topic no puede estar vacío")

    direct_path = Path(topic_arg)
    if direct_path.suffix.lower() == ".txt":
        candidates = [direct_path]
        if not direct_path.is_absolute():
            candidates.append(config.TOPICS_DIR / direct_path.name)
            candidates.append(config.TOPICS_DIR / direct_path)
        for candidate in candidates:
            if candidate.exists():
                _reject_template_path(candidate)
                brief = _load_topic_file(candidate)
                logger.info("Brief cargado: %s", candidate)
                return brief

    slug = topic_arg if re.fullmatch(r"[\w-]+", topic_arg) else _slugify(topic_arg)
    for name in (topic_arg, slug):
        if not name:
            continue
        file_path = config.TOPICS_DIR / f"{name}.txt"
        if file_path.exists():
            if not _is_pipeline_topic_file(file_path):
                _reject_template_path(file_path)
            brief = _load_topic_file(file_path)
            logger.info("Brief cargado: %s", file_path)
            return brief

    logger.info(
        "No hay archivo en %s — usando topic inline. "
        "Crea assets/topics/%s.txt para un brief detallado.",
        config.TOPICS_DIR,
        slug or "mi-tema",
    )
    return TopicBrief.from_inline(topic_arg)
