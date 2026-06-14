"""Module 4: Final video assembly with MoviePy."""

from __future__ import annotations

import logging
import random
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from config import PipelineConfig
from pipeline.subtitles import overlay_subtitles_on_clip

logger = logging.getLogger(__name__)


def _sanitize_title(title: str) -> str:
    """Convert title to a safe lowercase filename slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "video"


def _pick_background_music(config: PipelineConfig) -> Path | None:
    """Pick background music — default track or random from assets/music."""
    music_dir = config.ASSETS_MUSIC_DIR
    if not music_dir.exists():
        return None

    if config.MUSIC_MODE == "random":
        tracks = list(music_dir.glob("*.mp3")) + list(music_dir.glob("*.MP3"))
        return random.choice(tracks) if tracks else None

    default_path = music_dir / config.DEFAULT_MUSIC_FILE
    if default_path.exists():
        return default_path

    logger.warning(
        "Pista default no encontrada (%s) — usando primera MP3 disponible",
        default_path.name,
    )
    tracks = sorted(music_dir.glob("*.mp3"))
    return tracks[0] if tracks else None


def _concatenate_scenes(clips, config: PipelineConfig, mpy_version: str, mp: dict):
    """Concatenate scene clips with optional crossfade."""
    concatenate_videoclips = mp["concatenate_videoclips"]
    fade = config.SCENE_CROSSFADE_SECONDS

    if fade <= 0 or len(clips) <= 1:
        return concatenate_videoclips(clips, method="compose")

    if mpy_version == "v2":
        try:
            from moviepy import vfx

            faded = [clips[0]]
            for clip in clips[1:]:
                faded.append(clip.with_effects([vfx.CrossFadeIn(fade)]))
            return concatenate_videoclips(faded, method="compose", padding=-fade)
        except Exception:
            logger.debug("Crossfade v2 no disponible — concat directo")

    faded = [clips[0]]
    for clip in clips[1:]:
        faded.append(clip.crossfadein(fade))
    return concatenate_videoclips(faded, method="compose", padding=-fade)


def _cleanup_temp(temp_dir: Path) -> None:
    """Remove temporary working files."""
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        logger.info("Directorio temporal limpiado: %s", temp_dir)


def _import_moviepy():
    """Import MoviePy components (v1.x or v2.x)."""
    try:
        from moviepy.editor import (  # type: ignore[import-untyped]
            AudioFileClip,
            CompositeAudioClip,
            CompositeVideoClip,
            ImageClip,
            concatenate_audioclips,
            concatenate_videoclips,
        )

        return "v1", {
            "AudioFileClip": AudioFileClip,
            "CompositeAudioClip": CompositeAudioClip,
            "CompositeVideoClip": CompositeVideoClip,
            "ImageClip": ImageClip,
            "concatenate_audioclips": concatenate_audioclips,
            "concatenate_videoclips": concatenate_videoclips,
        }
    except ImportError:
        from moviepy import (  # type: ignore[import-untyped]
            AudioFileClip,
            CompositeAudioClip,
            CompositeVideoClip,
            ImageClip,
            afx,
            concatenate_audioclips,
            concatenate_videoclips,
        )

        return "v2", {
            "AudioFileClip": AudioFileClip,
            "CompositeAudioClip": CompositeAudioClip,
            "CompositeVideoClip": CompositeVideoClip,
            "ImageClip": ImageClip,
            "concatenate_audioclips": concatenate_audioclips,
            "concatenate_videoclips": concatenate_videoclips,
            "afx": afx,
        }


def _loop_music(mpy_version: str, mp: dict, music_clip, target_duration: float):
    """Loop background music to cover the full video duration."""
    loops = int(target_duration / music_clip.duration) + 1
    looped = mp["concatenate_audioclips"]([music_clip] * loops)

    if mpy_version == "v2":
        return looped.subclipped(0, target_duration)
    return looped.subclip(0, target_duration)



def _make_image_clip(
    image_path: str,
    duration: float,
    config: PipelineConfig,
    mpy_version: str,
    mp: dict,
):
    """Create a sized image clip, optionally with Ken Burns motion."""
    ImageClip = mp["ImageClip"]
    CompositeVideoClip = mp["CompositeVideoClip"]
    width, height = config.IMAGE_WIDTH, config.IMAGE_HEIGHT

    if not config.KEN_BURNS_ENABLED:
        if mpy_version == "v2":
            return ImageClip(image_path).with_duration(duration).resized((width, height))
        return ImageClip(image_path).set_duration(duration).resize((width, height))

    zoom = config.KEN_BURNS_ZOOM
    base = ImageClip(image_path)
    if mpy_version == "v2":
        base = base.resized(height=int(height * zoom))
        if base.w < width:
            base = base.resized(width=int(width * zoom))
        base = base.with_duration(duration)
    else:
        base = base.resize(height=int(height * zoom))
        if base.w < width:
            base = base.resize(width=int(width * zoom))
        base = base.set_duration(duration)

    pan_mode = random.choice(config.KEN_BURNS_PAN_MODES or ("left_to_right", "right_to_left", "top_to_bottom"))

    def position(t: float) -> tuple[int, int]:
        progress = t / max(duration, 0.01)
        if pan_mode == "left_to_right":
            x = -(base.w - width) * progress
            y = -(base.h - height) / 2
        elif pan_mode == "right_to_left":
            x = -(base.w - width) * (1 - progress)
            y = -(base.h - height) / 2
        else:
            x = -(base.w - width) / 2
            y = -(base.h - height) * progress
        return (int(x), int(y))

    if mpy_version == "v2":
        moving = base.with_position(position)
        return CompositeVideoClip([moving], size=(width, height)).with_duration(duration)

    moving = base.set_position(position)
    return CompositeVideoClip([moving], size=(width, height)).set_duration(duration)


def _build_scene_clip(
    scene: dict[str, Any],
    audio_clip,
    image_paths: list[str],
    config: PipelineConfig,
    mpy_version: str,
    mp: dict,
):
    """Build one scene clip — single or dual image with split narration."""
    concatenate_videoclips = mp["concatenate_videoclips"]
    duration = _get_audio_duration_from_clip(audio_clip, scene)

    if len(image_paths) == 1:
        visual = _make_image_clip(image_paths[0], duration, config, mpy_version, mp)
    else:
        split = duration * 0.5
        parts = []
        part_durations = [split, duration - split]
        for img_path, part_dur in zip(image_paths, part_durations):
            parts.append(_make_image_clip(img_path, part_dur, config, mpy_version, mp))
        visual = concatenate_videoclips(parts, method="compose")

    visual = overlay_subtitles_on_clip(
        visual, scene, duration, config, mpy_version, mp
    )

    if mpy_version == "v2":
        return visual.with_audio(audio_clip)
    return visual.set_audio(audio_clip)


def _get_audio_duration_from_clip(audio_clip, scene: dict[str, Any]) -> float:
    if "audio_duration" in scene:
        return float(scene["audio_duration"])
    return float(audio_clip.duration)


def _apply_watermark(video, config: PipelineConfig, mpy_version: str, mp: dict):
    """Overlay brand logo on bottom-right if logo file exists."""
    logo_path = config.LOGO_PATH
    if not logo_path.exists():
        logger.warning("Logo no encontrado en %s — video sin marca de agua", logo_path)
        return video

    CompositeVideoClip = mp["CompositeVideoClip"]
    ImageClip = mp["ImageClip"]
    margin = config.LOGO_MARGIN

    logo = ImageClip(str(logo_path))
    if mpy_version == "v2":
        logo = logo.resized(width=config.LOGO_WIDTH)
        logo = logo.with_duration(video.duration)
        logo = logo.with_opacity(config.LOGO_OPACITY)
        logo = logo.with_position(
            (video.w - logo.w - margin, video.h - logo.h - margin)
        )
        return CompositeVideoClip([video, logo])

    logo = logo.resize(width=config.LOGO_WIDTH)
    logo = logo.set_duration(video.duration)
    logo = logo.set_opacity(config.LOGO_OPACITY)
    logo = logo.set_position((video.w - logo.w - margin, video.h - logo.h - margin))
    return CompositeVideoClip([video, logo])


def assemble_video(
    scenes: list[dict[str, Any]],
    audio_files: list[str],
    config: PipelineConfig,
    *,
    title: str = "video",
    cleanup_temp: bool = True,
) -> str:
    """
    Assemble scene images and narration into a vertical MP4.

    Each scene dict must include image_paths (list of 1 or 2 image files).
    """
    if len(scenes) != len(audio_files):
        raise ValueError(
            f"Cantidad inconsistente: {len(scenes)} escenas, {len(audio_files)} audios"
        )

    for i, scene in enumerate(scenes, start=1):
        if not scene.get("image_paths"):
            raise ValueError(f"Escena {i}: sin image_paths — ejecuta generate_images primero")

    if config.VIDEO_ENGINE == "ffmpeg":
        from pipeline.ffmpeg_assembler import assemble_video_ffmpeg

        logger.info(
            "Motor FFmpeg (preset=%s, fps=%d) — mucho más rápido que MoviePy",
            config.FFMPEG_PRESET,
            config.VIDEO_FPS,
        )
        return assemble_video_ffmpeg(
            scenes,
            audio_files,
            config,
            title=title,
            cleanup_temp=cleanup_temp,
        )

    mpy_version, mp = _import_moviepy()
    CompositeAudioClip = mp["CompositeAudioClip"]
    concatenate_videoclips = mp["concatenate_videoclips"]

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    clips = []
    narration_clips = []

    for scene, audio_path in zip(scenes, audio_files):
        image_paths = scene["image_paths"]
        audio_clip = mp["AudioFileClip"](audio_path)
        narration_clips.append(audio_clip)
        scene_clip = _build_scene_clip(
            scene, audio_clip, image_paths, config, mpy_version, mp
        )
        clips.append(scene_clip)

    video = _concatenate_scenes(clips, config, mpy_version, mp)
    video = _apply_watermark(video, config, mpy_version, mp)

    music_track = _pick_background_music(config)
    if music_track:
        logger.info("Música de fondo: %s", music_track.name)
        bg_music = mp["AudioFileClip"](str(music_track))

        if mpy_version == "v2":
            bg_music = bg_music.with_volume_scaled(config.MUSIC_VOLUME)
        else:
            bg_music = bg_music.volumex(config.MUSIC_VOLUME)

        if bg_music.duration < video.duration:
            bg_music = _loop_music(mpy_version, mp, bg_music, video.duration)
        elif mpy_version == "v2":
            bg_music = bg_music.subclipped(0, video.duration)
        else:
            bg_music = bg_music.subclip(0, video.duration)

        fade_duration = min(3.0, video.duration / 2)
        if mpy_version == "v2":
            bg_music = bg_music.with_effects([mp["afx"].AudioFadeOut(fade_duration)])
        else:
            bg_music = bg_music.audio_fadeout(fade_duration)

        mixed = CompositeAudioClip([video.audio, bg_music])
        if mpy_version == "v2":
            video = video.with_audio(mixed)
        else:
            video = video.set_audio(mixed)
    else:
        logger.warning("No hay música en %s — video solo con narración", config.ASSETS_MUSIC_DIR)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{_sanitize_title(title)}_{timestamp}.mp4"
    output_path = config.OUTPUT_DIR / filename

    logger.info("Codificando video final (MoviePy)...")
    video.write_videofile(
        str(output_path),
        fps=30,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        threads=4,
        logger=None,
    )

    for clip in clips:
        clip.close()
    for clip in narration_clips:
        clip.close()
    video.close()

    if cleanup_temp:
        _cleanup_temp(config.TEMP_DIR)

    logger.info("Video final guardado: %s", output_path)
    return str(output_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(
        "Ejecuta main.py para ensamblar un video completo. "
        "Este módulo requiere archivos generados por TTS e imágenes."
    )
