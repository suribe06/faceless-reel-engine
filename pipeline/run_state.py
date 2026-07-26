"""Typed ownership of the pipeline RunState document (scenes + artifacts + step)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import PipelineConfig
from pipeline.topic_loader import TopicBrief

logger = logging.getLogger(__name__)

STATE_FILENAME = "pipeline_state.json"

# Dual-shot key moments — single source for script, images, and assemblers
KEY_MOMENTS = frozenset({"hook", "twist", "closing"})

# Fraction of scene duration for the first shot when a scene has two images
DUAL_SHOT_SPLIT = 0.5


def is_key_moment(value: Any) -> bool:
    return value in KEY_MOMENTS


def dual_shot_durations(total: float) -> tuple[float, float]:
    """Split a scene duration across two images."""
    first = total * DUAL_SHOT_SPLIT
    return first, total - first


@dataclass
class RunState:
    """
    Pipeline document: topic, title, scenes bag, and current step.

    Scenes remain list[dict] for JSON round-trip; this module owns field
    conventions, artifact paths, and between-stage checks.
    """

    topic: TopicBrief
    title: str
    scenes: list[dict[str, Any]] = field(default_factory=list)
    step: str = "script"
    audio_files: list[str] = field(default_factory=list)

    def topic_fields(self) -> dict[str, str]:
        fields = {
            "topic": self.topic.key,
            "topic_label": self.topic.label,
            "topic_brief": self.topic.brief,
        }
        if self.topic.source_path:
            fields["topic_file"] = str(self.topic.source_path)
        return fields

    def total_audio_seconds(self) -> float:
        total = 0.0
        for scene in self.scenes:
            dur = scene.get("audio_duration")
            if dur is not None:
                total += float(dur)
        return total

    def require_scenes(self) -> None:
        if not self.scenes:
            raise ValueError("RunState sin escenas")

    def require_image_paths(self) -> None:
        for i, scene in enumerate(self.scenes, start=1):
            paths = scene.get("image_paths") or []
            if not paths:
                raise ValueError(
                    f"Escena {i}: sin image_paths — ejecuta generate_images primero"
                )
            missing = [p for p in paths if not Path(p).exists()]
            if missing:
                raise FileNotFoundError(
                    f"Escena {i}: faltan imágenes: {missing}"
                )

    def bind_audio_paths(self, config: PipelineConfig) -> list[str]:
        """Resolve and verify scene_N.wav paths; store on self.audio_files."""
        n = len(self.scenes)
        audio_dir = config.TEMP_DIR / "audio"
        paths = [str(audio_dir / f"scene_{i}.wav") for i in range(1, n + 1)]
        missing = [p for p in paths if not Path(p).exists()]
        if missing:
            raise FileNotFoundError(
                f"Faltan audios en temp/audio ({len(missing)} archivos). "
                "Reanuda desde un paso anterior o regenera TTS."
            )
        self.audio_files = paths
        return paths

    def hydrate_audio_durations(self) -> float:
        """Fill missing audio_duration from wav files; return total seconds."""
        import soundfile as sf

        if len(self.audio_files) != len(self.scenes):
            raise ValueError(
                f"audio_files ({len(self.audio_files)}) != escenas ({len(self.scenes)})"
            )
        total = 0.0
        for scene, path in zip(self.scenes, self.audio_files):
            dur = float(scene.get("audio_duration") or sf.info(path).duration)
            scene["audio_duration"] = dur
            total += dur
        return total

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "topic": self.topic.key,
            "title": self.title,
            "scenes": self.scenes,
            "step": self.step,
            **{k: v for k, v in self.topic_fields().items() if k != "topic"},
        }
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, fallback_topic: str) -> RunState:
        topic = TopicBrief.from_saved(
            topic=payload.get("topic", fallback_topic),
            title=payload.get("title"),
            topic_label=payload.get("topic_label"),
            topic_brief=payload.get("topic_brief"),
            topic_file=payload.get("topic_file"),
        )
        return cls(
            topic=topic,
            title=str(payload.get("title") or topic.label),
            scenes=list(payload.get("scenes") or []),
            step=str(payload.get("step") or "script"),
        )


def state_path(config: PipelineConfig) -> Path:
    return config.TEMP_DIR / STATE_FILENAME


def save_run(config: PipelineConfig, run: RunState) -> None:
    """Persist RunState to temp/pipeline_state.json."""
    config.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    path = state_path(config)
    path.write_text(
        json.dumps(run.to_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.debug("Estado guardado: %s (paso %s)", path, run.step)


def load_run(config: PipelineConfig, *, fallback_topic: str) -> RunState:
    """Load RunState or raise if missing/empty."""
    path = state_path(config)
    if not path.exists():
        raise FileNotFoundError(
            f"No hay estado guardado en {config.TEMP_DIR}/{STATE_FILENAME}. "
            "Ejecuta un run completo primero o usa --keep-temp."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Estado corrupto en {path}: {exc}") from exc

    run = RunState.from_payload(payload, fallback_topic=fallback_topic)
    run.require_scenes()
    return run


# --- Back-compat thin wrappers (callers migrating off state.py) ---

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
    topic_brief_obj = TopicBrief.from_saved(
        topic=topic,
        title=title,
        topic_label=topic_label,
        topic_brief=topic_brief,
        topic_file=topic_file,
    )
    save_run(
        config,
        RunState(topic=topic_brief_obj, title=title, scenes=scenes, step=step),
    )


def load_state(config: PipelineConfig) -> dict[str, Any] | None:
    path = state_path(config)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.warning("Estado corrupto en %s: %s", path, exc)
        return None
