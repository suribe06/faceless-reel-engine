"""Fast video assembly via FFmpeg (Ken Burns, subs, logo, audio mix)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from config import PipelineConfig
from pipeline.assembly_common import (
    ass_font_size,
    pick_background_music,
    sanitize_title,
    scene_image_part_durations,
    cleanup_temp as remove_temp_dir,
)
from pipeline.subtitles import cues_in_window, scene_cues, write_srt_cues
from pipeline.subtitles import resolve_font

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


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def ken_burns_filter(duration: float, config: PipelineConfig, pan_mode: str) -> str:
    """Slow zoom plus pan. zoompan z=1 shows the whole pre-scaled frame."""
    fps = config.VIDEO_FPS
    w, h = config.IMAGE_WIDTH, config.IMAGE_HEIGHT
    frames = max(1, int(round(max(duration, 0.01) * fps)))

    if not config.KEN_BURNS_ENABLED or config.KEN_BURNS_ZOOM <= 1.001:
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={fps},setsar=1"
        )

    zoom = config.KEN_BURNS_ZOOM
    zw = _even(max(w + 2, int(w * zoom)))
    zh = _even(max(h + 2, int(h * zoom)))
    progress = f"on/{frames}"

    if pan_mode == "left_to_right":
        x_expr = f"(iw-iw/zoom)*{progress}"
        y_expr = "(ih-ih/zoom)/2"
    elif pan_mode == "right_to_left":
        x_expr = f"(iw-iw/zoom)*(1-{progress})"
        y_expr = "(ih-ih/zoom)/2"
    elif pan_mode == "top_to_bottom":
        x_expr = "(iw-iw/zoom)/2"
        y_expr = f"(ih-ih/zoom)*{progress}"
    else:
        x_expr = "(iw-iw/zoom)/2"
        y_expr = "(ih-ih/zoom)/2"

    z_expr = f"1+({zoom:.4f}-1)*{progress}"
    return (
        f"scale={zw}:{zh}:force_original_aspect_ratio=increase,"
        f"crop={zw}:{zh},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d={frames}:s={w}x{h}:fps={fps},"
        f"setsar=1"
    )


def narration_mix_filter(config: PipelineConfig, total_duration: float, *, has_music: bool) -> str:
    """Voice at -14 LUFS. Music ducks while someone is speaking."""
    if not has_music:
        return "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"

    fade = min(3.0, total_duration / 2)
    fade_start = max(0.0, total_duration - fade)
    return (
        f"[1:a]asplit=2[nar][nar_sc];"
        f"[2:a]volume={config.MUSIC_VOLUME},afade=t=out:st={fade_start:.3f}:d={fade:.3f}[mus];"
        f"[mus][nar_sc]sidechaincompress=threshold=0.03:ratio=6:attack=80:release=500[musduck];"
        f"[nar][musduck]amix=inputs=2:duration=first:dropout_transition=2,"
        f"loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
    )


def _escape_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")


def _drawtext_filter(text_path: Path, font_path: str, config: PipelineConfig) -> str:
    text = _escape_filter_path(text_path)
    font = _escape_filter_path(Path(font_path))
    seconds = config.HOOK_OVERLAY_SECONDS
    return (
        f"drawtext=fontfile='{font}':textfile='{text}':fontsize={config.HOOK_FONT_SIZE}:"
        f"fontcolor=white:borderw=3:bordercolor=black:"
        f"box=1:boxcolor=black@0.55:boxborderw=18:"
        f"x=(w-text_w)/2:y=h*0.16:enable='lt(t,{seconds:.2f})'"
    )


def _render_image_clip(
    image_path: str,
    duration: float,
    output: Path,
    config: PipelineConfig,
    pan_mode: str,
    *,
    srt_path: Path | None = None,
    hook_text: str | None = None,
) -> None:
    frames = max(1, int(round(max(duration, 0.01) * config.VIDEO_FPS)))
    chain = ken_burns_filter(duration, config, pan_mode)
    if srt_path is not None and srt_path.stat().st_size > 0:
        chain = f"{chain},{_subtitle_filter(srt_path, config)}"

    hook_file: Path | None = None
    if hook_text and config.HOOK_OVERLAY_ENABLED:
        hook_file = output.with_suffix(".hook.txt")
        hook_file.write_text(hook_text.strip() + "\n", encoding="utf-8")
        chain = f"{chain},{_drawtext_filter(hook_file, resolve_font(config), config)}"

    logo = config.LOGO_PATH if config.LOGO_PATH.exists() else None
    encode = [
        "-frames:v",
        str(frames),
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
    ]
    if logo is None:
        _run_ffmpeg(
            ["-i", image_path, "-vf", f"{chain},format=yuv420p", *encode],
            f"clip {output.name} ({duration:.1f}s)",
        )
    else:
        margin = config.LOGO_MARGIN
        _run_ffmpeg(
            [
                "-i",
                image_path,
                "-i",
                str(logo),
                "-filter_complex",
                (
                    f"[0:v]{chain}[vbase];"
                    f"[1:v]scale={config.LOGO_WIDTH}:-1,format=rgba,"
                    f"colorchannelmixer=aa={config.LOGO_OPACITY}[logo];"
                    f"[vbase][logo]overlay=W-w-{margin}:H-h-{margin},format=yuv420p[vout]"
                ),
                "-map",
                "[vout]",
                *encode,
            ],
            f"clip {output.name} ({duration:.1f}s)",
        )
    if hook_file is not None:
        hook_file.unlink(missing_ok=True)


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
            "-fflags",
            "+genpts",
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
    escaped = _escape_filter_path(srt_path)
    margin_v = config.SUBTITLE_MARGIN_Y // 3
    font_size = ass_font_size(config)
    style = (
        f"FontName=DejaVu Sans,FontSize={font_size},PrimaryColour=&HFFFFFF,"
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
    """Assemble the final MP4 with FFmpeg."""
    work_dir = config.TEMP_DIR / "encode"
    work_dir.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    segment_paths: list[Path] = []
    pan_modes = _pan_modes(config)
    hook_line = ""
    if config.HOOK_OVERLAY_ENABLED and scenes:
        hook_line = str(scenes[0].get("hook_line") or "").strip()

    for idx, scene in enumerate(scenes, start=1):
        duration = float(scene.get("audio_duration", 0))
        if duration <= 0:
            raise ValueError(f"Escena {idx}: audio_duration inválido")

        image_paths = scene["image_paths"]
        pan_mode = pan_modes[(idx - 1) % len(pan_modes)]
        segment = work_dir / f"scene_{idx:02d}.mp4"
        cues = scene_cues(scene, config) if config.SUBTITLES_ENABLED else []

        def render_part(
            image: str,
            part_dur: float,
            dest: Path,
            mode: str,
            window_start: float,
            *,
            with_hook: bool,
        ) -> None:
            part_cues = cues_in_window(cues, window_start, window_start + part_dur)
            srt = dest.with_suffix(".srt")
            write_srt_cues(part_cues, srt)
            _render_image_clip(
                image,
                part_dur,
                dest,
                config,
                mode,
                srt_path=srt if part_cues else None,
                hook_text=hook_line if with_hook else None,
            )

        if len(image_paths) == 1:
            render_part(
                image_paths[0],
                duration,
                segment,
                pan_mode,
                0.0,
                with_hook=idx == 1 and bool(hook_line),
            )
        else:
            part_durs = scene_image_part_durations(len(image_paths), duration)
            parts: list[Path] = []
            cursor = 0.0
            for j, (img, part_dur) in enumerate(zip(image_paths, part_durs)):
                part = work_dir / f"scene_{idx:02d}_{j}.mp4"
                mode = pan_modes[(idx + j) % len(pan_modes)]
                render_part(
                    img,
                    part_dur,
                    part,
                    mode,
                    cursor,
                    with_hook=idx == 1 and j == 0 and bool(hook_line),
                )
                parts.append(part)
                cursor += part_dur
            _concat_videos(parts, segment)

        segment_paths.append(segment)
        logger.info("[ffmpeg] Escena %d/%d lista", idx, len(scenes))

    video_only = work_dir / "video_only.mp4"
    _concat_videos(segment_paths, video_only)

    narration_wav = work_dir / "narration.wav"
    _concat_narration(audio_files, narration_wav)

    timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = config.OUTPUT_DIR / f"{sanitize_title(title)}_{timestamp}.mp4"

    music_track = pick_background_music(config)
    total_duration = sum(float(s.get("audio_duration", 0)) for s in scenes)
    if music_track:
        logger.info("Música de fondo: %s", music_track.name)

    mix = narration_mix_filter(config, total_duration, has_music=music_track is not None)
    mux_inputs = ["-i", str(video_only), "-i", str(narration_wav)]
    if music_track:
        mux_inputs.extend(["-stream_loop", "-1", "-i", str(music_track)])
    _run_ffmpeg(
        [
            *mux_inputs,
            "-filter_complex",
            mix,
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
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        "mux narración + música",
    )

    if cleanup_temp:
        remove_temp_dir(config.TEMP_DIR)

    logger.info("Video final guardado: %s", output_path)
    return str(output_path)
