"""Module 2: Narration generation via Kokoro TTS."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from config import PipelineConfig
from pipeline.subtitles import cues_from_spoken_durations, split_spoken_sentences

logger = logging.getLogger(__name__)

KOKORO_SAMPLE_RATE = 24000
MAX_CHUNK_CHARS = 300

# Map config voice shorthand to Kokoro lang_code + voice id
VOICE_MAP: dict[str, tuple[str, str]] = {
    "es": ("e", "ef_dora"),
    "ef_dora": ("e", "ef_dora"),
    "em_alex": ("e", "em_alex"),
    "em_santa": ("e", "em_santa"),
}


def _resolve_voice(voice_setting: str) -> tuple[str, str]:
    """Return (lang_code, voice_id) for Kokoro from config TTS_VOICE."""
    key = voice_setting.strip().lower()
    if key in VOICE_MAP:
        return VOICE_MAP[key]
    if "_" in voice_setting:
        return ("e", voice_setting)
    return VOICE_MAP["es"]


def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split narration into chunks at sentence boundaries."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""

    for part in text.replace("\n", " ").split(". "):
        sentence = part.strip()
        if not sentence:
            continue
        if not sentence.endswith("."):
            sentence += "."

        if len(sentence) > max_chars:
            words = sentence.split()
            sub = ""
            for word in words:
                candidate = f"{sub} {word}".strip()
                if len(candidate) > max_chars and sub:
                    chunks.append(sub)
                    sub = word
                else:
                    sub = candidate
            if sub:
                current = f"{current} {sub}".strip() if current else sub
                if len(current) >= max_chars:
                    chunks.append(current)
                    current = ""
            continue

        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > max_chars:
            if current:
                chunks.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks or [text[:max_chars]]


def _get_pipeline(lang_code: str):
    """Lazy-load Kokoro pipeline."""
    from kokoro import KPipeline

    return KPipeline(lang_code=lang_code)


_tts_pipeline = None


def release_tts_resources() -> None:
    """Drop cached Kokoro pipeline and free associated memory."""
    global _tts_pipeline
    _tts_pipeline = None
    logger.info("Recursos Kokoro TTS liberados de memoria")


def release_after_tts() -> None:
    """Release Kokoro after audio generation (incl. GPU/Python GC)."""
    import gc

    logger.info("--- Liberando recursos del paso 2 (Kokoro TTS) ---")
    release_tts_resources()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except ImportError:
        pass


def _gap_seconds(config: PipelineConfig) -> float:
    samples = int(KOKORO_SAMPLE_RATE * config.TTS_CHUNK_SILENCE_MS / 1000)
    return samples / KOKORO_SAMPLE_RATE


def _concat_audio_chunks(chunks: list[np.ndarray], config: PipelineConfig) -> np.ndarray:
    """Join TTS segments with short silence and peak normalization."""
    if len(chunks) == 1:
        combined = chunks[0]
    else:
        silence_ms = config.TTS_CHUNK_SILENCE_MS
        silence = np.zeros(
            int(KOKORO_SAMPLE_RATE * silence_ms / 1000),
            dtype=np.float32,
        )
        parts: list[np.ndarray] = []
        for i, chunk in enumerate(chunks):
            parts.append(chunk)
            if i < len(chunks) - 1:
                parts.append(silence)
        combined = np.concatenate(parts)

    peak = float(np.max(np.abs(combined))) if combined.size else 0.0
    if peak > 0.98:
        combined = combined * (0.95 / peak)
    return combined


def _synthesize_text(
    pipeline,
    text: str,
    voice: str,
    speed: float,
) -> np.ndarray:
    """Generate audio array for a text segment."""
    segments: list[np.ndarray] = []

    generator = pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+")
    for _gs, _ps, audio in generator:
        segments.append(np.asarray(audio, dtype=np.float32))

    if not segments:
        raise RuntimeError(f"Kokoro no generó audio para: {text[:80]}...")

    return np.concatenate(segments)


def _wav_duration(path: Path) -> float:
    """Return duration of a WAV file in seconds."""
    info = sf.info(str(path))
    return info.duration


def generate_audio(
    scenes: list[dict[str, Any]],
    config: PipelineConfig,
) -> tuple[list[str], list[float]]:
    """
    Generate TTS audio for each scene.

    Returns (list of wav paths, list of durations in seconds).
    Also sets scene['audio_duration'] on each scene dict.
    """
    audio_dir = config.TEMP_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    lang_code, voice_id = _resolve_voice(config.TTS_VOICE)
    total = len(scenes)

    global _tts_pipeline
    try:
        if _tts_pipeline is None:
            _tts_pipeline = _get_pipeline(lang_code)
        pipeline = _tts_pipeline
    except Exception as exc:
        raise RuntimeError(
            "No se pudo inicializar Kokoro TTS. "
            "Verifica que kokoro esté instalado y que espeak-ng esté disponible "
            "(sudo apt install espeak-ng)."
        ) from exc

    audio_files: list[str] = []
    durations: list[float] = []

    for idx, scene in enumerate(scenes, start=1):
        narration = scene.get("narration", "").strip()
        if not narration:
            raise ValueError(f"Escena {idx}: narración vacía")

        sentences = split_spoken_sentences(narration)
        sentence_audio: list[np.ndarray] = []
        sentence_durs: list[float] = []
        for sentence in sentences:
            chunks = _split_text(sentence)
            audio = _concat_audio_chunks(
                [_synthesize_text(pipeline, chunk, voice_id, config.TTS_SPEED) for chunk in chunks],
                config,
            )
            sentence_audio.append(audio)
            sentence_durs.append(len(audio) / KOKORO_SAMPLE_RATE)

        gap = _gap_seconds(config) if len(sentence_audio) > 1 else 0.0
        if len(sentence_audio) == 1:
            combined = sentence_audio[0]
        else:
            silence = np.zeros(
                int(KOKORO_SAMPLE_RATE * config.TTS_CHUNK_SILENCE_MS / 1000),
                dtype=np.float32,
            )
            parts: list[np.ndarray] = []
            for i, audio in enumerate(sentence_audio):
                parts.append(audio)
                if i < len(sentence_audio) - 1:
                    parts.append(silence)
            combined = np.concatenate(parts)

        scene["subtitle_cues"] = [
            {"start": round(start, 3), "end": round(end, 3), "text": text}
            for start, end, text in cues_from_spoken_durations(
                sentences, sentence_durs, config, gap
            )
        ]

        output_path = audio_dir / f"scene_{idx}.wav"
        sf.write(str(output_path), combined, KOKORO_SAMPLE_RATE)

        duration = _wav_duration(output_path)
        scene["audio_duration"] = duration
        audio_files.append(str(output_path))
        durations.append(duration)

        logger.info("[TTS] Escena %d/%d generada (%.1fs)", idx, total, duration)

    return audio_files, durations


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cfg = PipelineConfig()
    cfg.resolve_paths()
    cfg.ensure_directories()

    sample_scenes = [
        {
            "scene_number": 1,
            "narration": "En una noche oscura de Bogotá, algo extraño ocurrió que nadie supo explicar.",
            "image_prompt": "dark bogota street at night, photorealistic",
            "duration_hint": 5,
        }
    ]
    paths, durs = generate_audio(sample_scenes, cfg)
    print(f"Generado: {paths[0]} ({durs[0]:.1f}s)")
