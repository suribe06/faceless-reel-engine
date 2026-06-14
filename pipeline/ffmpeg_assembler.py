"""Fast video assembly via FFmpeg (Ken Burns, subs, logo, audio mix)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from config import PipelineConfig
from pipeline.subtitles import write_srt_for_scenes
from pipeline.video_assembler import _pick_background_music, _sanitize_title

logger = logging.getLogger(__name__)


def _pan_modes(config: PipelineConfig) -> tuple[str, ...]:
    modes = config.KEN_BURNS_PAN_MODES
    if not modes:
        return ("left_to_right", "right_to_left", "top_to_bottom")
    return tuple(modes)


def _ffmpeg_threads(config: PipelineConfig) -> list[str]:
    if config.FFMPEG_THREADS and config.FFMPEG_THREADS > 0:
        return ["-threads", str(config.FFMPEG_THREADS)]
    return []


def _run_ffmpeg(args: list[str], desc: str) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", *args]
    logger.info("[ffmpeg] %s", desc)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "error desconocido").strip()
        raise RuntimeError(f"FFmpeg falló ({desc}): {err[-2000:]}")


def _video_filter(duration: float, config: PipelineConfig, pan_mode: str) -> str:
    """Ken Burns: pan lineal sobre imagen oversize (igual que MoviePy, sin zoom animado)."""
    fps = config.VIDEO_FPS
    w, h = config.IMAGE_WIDTH, config.IMAGE_HEIGHT

    if not config.KEN_BURNS_ENABLED:
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},format=yuv420p"
        )

    zoom = config.KEN_BURNS_ZOOM
    zw = int(w * zoom)
    zh = int(h * zoom)
    dur = max(duration, 0.01)

    # MoviePy: imagen estática 1.12× y ventana 1080×1920 que se desplaza (sin zoom progresivo).
    if pan_mode == "left_to_right":
        x_expr = f"(iw-ow)*t/{dur:.4f}"
        y_expr = "(ih-oh)/2"
    elif pan_mode == "right_to_left":
        x_expr = f"(iw-ow)*(1-t/{dur:.4f})"
        y_expr = "(ih-oh)/2"
    elif pan_mode == "top_to_bottom":
        x_expr = "(iw-ow)/2"
        y_expr = f"(ih-oh)*t/{dur:.4f}"
    else:
        x_expr = "(iw-ow)/2"
        y_expr = "(ih-oh)/2"

    return (
        f"scale={zw}:{zh}:force_original_aspect_ratio=increase,"
        f"crop={zw}:{zh},"
        f"crop={w}:{h}:x='{x_expr}':y='{y_expr}',"
        f"fps={fps},format=yuv420p"
    )


def _render_image_clip(
    image_path: str,
    duration: float,
    output: Path,
    config: PipelineConfig,
    pan_mode: str,
) -> None:
    vf = _video_filter(duration, config, pan_mode)
    _run_ffmpeg(
        [
            "-loop",
            "1",
            "-i",
            image_path,
            "-vf",
            vf,
            "-t",
            f"{duration:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            config.FFMPEG_PRESET,
            "-crf",
            str(config.FFMPEG_CRF),
            "-pix_fmt",
            "yuv420p",
            *_ffmpeg_threads(config),
            str(output),
        ],
        f"clip {output.name} ({duration:.1f}s)",
    )


def _concat_videos(sources: list[Path], output: Path) -> None:
    if len(sources) == 1:
        shutil.copy2(sources[0], output)
        return

    list_file = output.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in sources),
        encoding="utf-8",
    )
    _run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output),
        ],
        f"concat → {output.name}",
    )
    list_file.unlink(missing_ok=True)


def _concat_narration(audio_files: list[str], output: Path) -> None:
    list_file = output.with_suffix(".txt")
    list_file.write_text(
        "\n".join(f"file '{Path(p).resolve()}'" for p in audio_files),
        encoding="utf-8",
    )
    _run_ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output),
        ],
        "concat narración",
    )
    list_file.unlink(missing_ok=True)


def _subtitle_filter(srt_path: Path, config: PipelineConfig) -> str:
    escaped = srt_path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
    margin_v = config.SUBTITLE_MARGIN_Y // 3
    style = (
        f"FontName=DejaVu Sans,FontSize=16,PrimaryColour=&HFFFFFF,"
        f"OutlineColour=&H000000,Outline=2,Shadow=0,"
        f"BackColour=&H80000000,BorderStyle=4,Alignment=2,MarginV={margin_v}"
    )
    return f"subtitles='{escaped}':force_style='{style}'"


def assemble_video_ffmpeg(
    scenes: list[dict[str, Any]],
    audio_files: list[str],
    config: PipelineConfig,
    *,
    title: str = "video",
    cleanup_temp: bool = True,
) -> str:
    """Assemble final MP4 using FFmpeg filters (much faster than MoviePy)."""
    work_dir = config.TEMP_DIR / "encode"
    work_dir.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    segment_paths: list[Path] = []
    pan_modes = _pan_modes(config)

    for idx, scene in enumerate(scenes, start=1):
        duration = float(scene.get("audio_duration", 0))
        if duration <= 0:
            raise ValueError(f"Escena {idx}: audio_duration inválido")

        image_paths = scene["image_paths"]
        pan_mode = pan_modes[(idx - 1) % len(pan_modes)]
        segment = work_dir / f"scene_{idx:02d}.mp4"

        if len(image_paths) == 1:
            _render_image_clip(image_paths[0], duration, segment, config, pan_mode)
        else:
            split = duration * 0.5
            parts: list[Path] = []
            for j, (img, part_dur) in enumerate(
                [(image_paths[0], split), (image_paths[1], duration - split)]
            ):
                part = work_dir / f"scene_{idx:02d}_{j}.mp4"
                mode = pan_modes[(idx + j) % len(pan_modes)]
                _render_image_clip(img, part_dur, part, config, mode)
                parts.append(part)
            _concat_videos(parts, segment)

        segment_paths.append(segment)
        logger.info("[ffmpeg] Escena %d/%d lista", idx, len(scenes))

    video_only = work_dir / "video_only.mp4"
    _concat_videos(segment_paths, video_only)

    narration_wav = work_dir / "narration.wav"
    _concat_narration(audio_files, narration_wav)

    srt_path = work_dir / "subs.srt"
    write_srt_for_scenes(scenes, srt_path, config)

    timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = config.OUTPUT_DIR / f"{_sanitize_title(title)}_{timestamp}.mp4"
    temp_mux = work_dir / "muxed.mp4"

    music_track = _pick_background_music(config)
    total_duration = sum(float(s.get("audio_duration", 0)) for s in scenes)
    fade = min(3.0, total_duration / 2)
    fade_start = max(0.0, total_duration - fade)

    if music_track:
        logger.info("Música de fondo: %s", music_track.name)
        _run_ffmpeg(
            [
                "-i",
                str(video_only),
                "-i",
                str(narration_wav),
                "-stream_loop",
                "-1",
                "-i",
                str(music_track),
                "-filter_complex",
                (
                    f"[1:a]volume=1[nar];"
                    f"[2:a]volume={config.MUSIC_VOLUME},afade=t=out:st={fade_start}:d={fade}[mus];"
                    f"[nar][mus]amix=inputs=2:duration=first:dropout_transition=2[aout]"
                ),
                "-map",
                "0:v",
                "-map",
                "[aout]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(temp_mux),
            ],
            "mux video + narración + música",
        )
    else:
        _run_ffmpeg(
            [
                "-i",
                str(video_only),
                "-i",
                str(narration_wav),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(temp_mux),
            ],
            "mux video + narración",
        )

    logo_path = config.LOGO_PATH
    has_subs = config.SUBTITLES_ENABLED and srt_path.stat().st_size > 0

    if logo_path.exists() and has_subs:
        sub = _subtitle_filter(srt_path, config)
        margin = config.LOGO_MARGIN
        filter_complex = (
            f"[0:v]{sub}[vsub];"
            f"[1:v]scale={config.LOGO_WIDTH}:-1,format=rgba,"
            f"colorchannelmixer=aa={config.LOGO_OPACITY}[logo];"
            f"[vsub][logo]overlay=W-w-{margin}:H-h-{margin}[vout]"
        )
        _run_ffmpeg(
            [
                "-i",
                str(temp_mux),
                "-i",
                str(logo_path),
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "0:a",
                "-c:v",
                "libx264",
                "-preset",
                config.FFMPEG_PRESET,
                "-crf",
                str(config.FFMPEG_CRF),
                *_ffmpeg_threads(config),
                "-c:a",
                "copy",
                str(output_path),
            ],
            "subtítulos + logo",
        )
    elif logo_path.exists():
        margin = config.LOGO_MARGIN
        _run_ffmpeg(
            [
                "-i",
                str(temp_mux),
                "-i",
                str(logo_path),
                "-filter_complex",
                (
                    f"[1:v]scale={config.LOGO_WIDTH}:-1,format=rgba,"
                    f"colorchannelmixer=aa={config.LOGO_OPACITY}[logo];"
                    f"[0:v][logo]overlay=W-w-{margin}:H-h-{margin}"
                ),
                "-c:v",
                "libx264",
                "-preset",
                config.FFMPEG_PRESET,
                "-crf",
                str(config.FFMPEG_CRF),
                *_ffmpeg_threads(config),
                "-c:a",
                "copy",
                str(output_path),
            ],
            "logo",
        )
    elif has_subs:
        sub = _subtitle_filter(srt_path, config)
        _run_ffmpeg(
            [
                "-i",
                str(temp_mux),
                "-vf",
                sub,
                "-c:v",
                "libx264",
                "-preset",
                config.FFMPEG_PRESET,
                "-crf",
                str(config.FFMPEG_CRF),
                *_ffmpeg_threads(config),
                "-c:a",
                "copy",
                str(output_path),
            ],
            "subtítulos",
        )
    else:
        output_path.write_bytes(temp_mux.read_bytes())

    if cleanup_temp:
        shutil.rmtree(config.TEMP_DIR, ignore_errors=True)
        logger.info("Directorio temporal limpiado")

    logger.info("Video final guardado: %s", output_path)
    return str(output_path)
