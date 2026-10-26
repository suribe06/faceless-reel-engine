"""Pure-core checks for deepened pipeline modules (stdlib unittest)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from config import PipelineConfig
from pipeline.assembly_common import (
    ass_font_size,
    sanitize_title,
    scene_image_part_durations,
)
from pipeline.duration_policy import (
    AUDIO_MIN_FACTOR,
    estimate_bounds,
    min_audio_seconds,
    needs_extension,
    validate_before_images,
    validate_estimated_duration,
)
from pipeline.run_state import (
    KEY_MOMENTS,
    RunState,
    dual_shot_durations,
    is_key_moment,
    load_run,
    save_run,
)
from pipeline.ffmpeg_assembler import ken_burns_filter, narration_mix_filter
from pipeline.image_generator import sampling_params, shot_seed
from pipeline.script_generator import (
    apply_script_visuals,
    normalize_script_scenes,
    short_hook_line,
)
from pipeline.subtitles import (
    build_subtitle_cues,
    cues_from_spoken_durations,
    cues_in_window,
    scene_cues,
    split_narration_lines,
    split_spoken_sentences,
)
from pipeline.topic_expander import needs_brief, parse_generated_brief
from pipeline.topic_loader import TopicBrief


class DurationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = PipelineConfig()
        self.cfg.TARGET_DURATION_MIN_SECONDS = 180
        self.cfg.TARGET_DURATION_MAX_SECONDS = 240

    def test_min_audio_uses_shared_factor(self) -> None:
        self.assertAlmostEqual(min_audio_seconds(self.cfg), 180 * AUDIO_MIN_FACTOR)

    def test_needs_extension(self) -> None:
        self.assertTrue(needs_extension(100.0, self.cfg))
        self.assertFalse(needs_extension(180 * AUDIO_MIN_FACTOR, self.cfg))

    def test_estimate_bounds(self) -> None:
        lo, hi = estimate_bounds(self.cfg)
        validate_estimated_duration((lo + hi) // 2, self.cfg)
        with self.assertRaises(ValueError):
            validate_estimated_duration(lo - 1, self.cfg)

    def test_validate_before_images_blocks_short_audio(self) -> None:
        scenes = [{"narration": "x" * 200, "scene_number": 1}]
        with self.assertRaises(ValueError):
            validate_before_images(scenes, self.cfg, 10.0)

    def test_validate_before_images_ok(self) -> None:
        scenes = [{"narration": "x" * 200, "scene_number": 1}]
        validate_before_images(scenes, self.cfg, min_audio_seconds(self.cfg))


class RunStateTests(unittest.TestCase):
    def test_key_moments(self) -> None:
        self.assertTrue(is_key_moment("hook"))
        self.assertFalse(is_key_moment(None))
        self.assertEqual(KEY_MOMENTS, frozenset({"hook", "twist", "closing"}))

    def test_dual_shot_split(self) -> None:
        a, b = dual_shot_durations(10.0)
        self.assertAlmostEqual(a + b, 10.0)
        self.assertAlmostEqual(a, 5.0)

    def test_roundtrip_save_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = PipelineConfig()
            cfg.TEMP_DIR = Path(tmp)
            topic = TopicBrief.from_inline("Caso de prueba")
            run = RunState(
                topic=topic,
                title="Titulo",
                scenes=[{"scene_number": 1, "narration": "hola", "image_prompt": "dark alley"}],
                step="script",
            )
            save_run(cfg, run)
            loaded = load_run(cfg, fallback_topic="caso-de-prueba")
            self.assertEqual(loaded.title, "Titulo")
            self.assertEqual(len(loaded.scenes), 1)
            self.assertEqual(loaded.step, "script")


class ScriptNormalizeTests(unittest.TestCase):
    def test_assigns_key_moments_and_prompts(self) -> None:
        cfg = PipelineConfig()
        scenes = [
            {"narration": "a" * 100, "image_prompt": "wide street at night"},
            {"narration": "b" * 100, "image_prompt": "office interior"},
            {"narration": "c" * 100, "image_prompt": "rainy rooftop"},
            {"narration": "d" * 100, "image_prompt": "courtroom empty"},
        ]
        normalize_script_scenes(scenes, cfg)
        self.assertEqual(scenes[0]["key_moment"], "hook")
        self.assertEqual(scenes[-1]["key_moment"], "closing")
        self.assertIn("image_prompts", scenes[0])
        self.assertEqual(len(scenes[0]["image_prompts"]), 2)


class AssemblyCommonTests(unittest.TestCase):
    def test_sanitize_title(self) -> None:
        self.assertEqual(sanitize_title("Hola Mundo!"), "hola-mundo")

    def test_ass_font_tracks_config(self) -> None:
        cfg = PipelineConfig()
        cfg.SUBTITLE_FONT_SIZE = 42
        self.assertEqual(ass_font_size(cfg), 16)  # int(42 * 0.4)

    def test_scene_part_durations(self) -> None:
        self.assertEqual(scene_image_part_durations(1, 8.0), [8.0])
        parts = scene_image_part_durations(2, 10.0)
        self.assertEqual(len(parts), 2)
        self.assertAlmostEqual(sum(parts), 10.0)


class PipelineQualityTests(unittest.TestCase):
    def test_missing_prompt_stays_english(self) -> None:
        cfg = PipelineConfig()
        scenes = [{"narration": "En Bogotá nadie vio el cuerpo aquella noche."}]
        normalize_script_scenes(scenes, cfg)
        prompt = scenes[0]["image_prompt"]
        self.assertNotIn("Bogotá", prompt)
        self.assertNotIn("nadie", prompt)
        self.assertIn("photorealistic", prompt)

    def test_anchor_is_shared_and_hook_fits(self) -> None:
        cfg = PipelineConfig()
        data = {
            "title": "Caso",
            "visual_anchor": "1985 Medellin rainy night, 35mm",
            "hook_line": "Nadie denunció el segundo disparo en la escalera del palacio",
            "scenes": [
                {"narration": "Texto.", "image_prompt": "empty hallway"},
                {"narration": "Otro.", "image_prompt": "courtyard"},
                {"narration": "Cierre.", "image_prompt": "door"},
                {"narration": "Fin.", "image_prompt": "street"},
            ],
        }
        normalize_script_scenes(data["scenes"], cfg)
        apply_script_visuals(data, cfg)
        self.assertTrue(data["scenes"][0]["image_prompt"].startswith("1985 Medellin"))
        self.assertTrue(data["scenes"][-1]["image_prompt"].startswith("1985 Medellin"))
        self.assertLessEqual(len(data["hook_line"]), 42)
        self.assertNotIn("palacio", data["hook_line"])

    def test_sampling_and_seed(self) -> None:
        full = PipelineConfig()
        self.assertEqual(sampling_params(full)[:2], (20, 6.0))
        fast = PipelineConfig()
        fast.SDXL_CHECKPOINT = "RealVisXL_lightning.safetensors"
        self.assertEqual(sampling_params(fast), (6, 1.5, "euler", "sgm_uniform"))
        self.assertEqual(shot_seed(10, 1, 0), shot_seed(10, 1, 0))
        self.assertNotEqual(shot_seed(10, 1, 0), shot_seed(10, 2, 0))

    def test_spoken_cues_track_each_sentence(self) -> None:
        cfg = PipelineConfig()
        sentences = split_spoken_sentences("Primera frase larga de prueba. Segunda frase corta.")
        self.assertEqual(len(sentences), 2)
        cues = cues_from_spoken_durations(sentences, [1.0, 2.0], cfg, 0.08)
        self.assertAlmostEqual(cues[0][0], 0.0)
        self.assertGreaterEqual(cues[-1][0], 1.08)
        self.assertAlmostEqual(cues[-1][1], 3.08)
        scene = {
            "narration": "ignorame",
            "audio_duration": 9,
            "subtitle_cues": [{"start": 0.0, "end": 1.2, "text": "medido"}],
        }
        self.assertEqual(scene_cues(scene, cfg), [(0.0, 1.2, "medido")])
        window = cues_in_window([(0.0, 1.0, "a"), (1.0, 3.0, "b")], 1.0, 2.0)
        self.assertEqual(window[0][2], "b")
        self.assertAlmostEqual(window[0][1], 1.0)

    def test_filters_and_a_short_clip(self) -> None:
        cfg = PipelineConfig()
        graph = ken_burns_filter(2.0, cfg, "left_to_right")
        self.assertIn("zoompan", graph)
        music = narration_mix_filter(cfg, 10, has_music=True)
        self.assertIn("sidechaincompress", music)
        self.assertIn("asplit", music)
        self.assertIn("loudnorm", narration_mix_filter(cfg, 10, has_music=False))
        self.assertLessEqual(len(short_hook_line("uno dos tres cuatro cinco", 12)), 12)

        import shutil
        import subprocess
        import tempfile

        from PIL import Image

        from pipeline.ffmpeg_assembler import _render_image_clip

        if shutil.which("ffmpeg") is None:
            self.skipTest("ffmpeg")

        cfg.IMAGE_WIDTH = 320
        cfg.IMAGE_HEIGHT = 568
        cfg.VIDEO_FPS = 12
        cfg.FFMPEG_PRESET = "ultrafast"
        cfg.LOGO_PATH = Path("/tmp/logo-que-no-existe.png")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            img = folder / "still.png"
            Image.new("RGB", (160, 284), (20, 24, 48)).save(img)
            out = folder / "clip.mp4"
            srt = folder / "c.srt"
            srt.write_text(
                "1\n00:00:00,000 --> 00:00:00,400\nhola\n",
                encoding="utf-8",
            )
            _render_image_clip(
                str(img),
                0.4,
                out,
                cfg,
                "left_to_right",
                srt_path=srt,
                hook_text="Nadie vio",
            )
            self.assertGreater(out.stat().st_size, 500)

            wav = folder / "voice.wav"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=0.4",
                    str(wav),
                ],
                check=True,
            )
            mixed = folder / "mixed.mp4"
            mix = narration_mix_filter(cfg, 0.4, has_music=True)
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(out),
                    "-i", str(wav),
                    "-f", "lavfi", "-i", "sine=frequency=80:duration=0.4",
                    "-filter_complex", mix,
                    "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac",
                    str(mixed),
                ],
                check=True,
            )
            self.assertGreater(mixed.stat().st_size, 500)


class TopicBriefTests(unittest.TestCase):
    def test_one_line_needs_research(self) -> None:
        inline = TopicBrief.from_inline("El misterio del vuelo MH370")
        self.assertTrue(needs_brief(inline))
        saved = TopicBrief(
            key="caso",
            label="Caso",
            brief="TITLE ya no importa",
            source_path=Path("assets/topics/caso.txt"),
        )
        self.assertFalse(needs_brief(saved))

    def test_parse_brief_starts_at_title(self) -> None:
        raw = """Notas previas que no se guardan.
TITLE: La toma del Palacio

Resumen para el guión:
El 6 de noviembre de 1985 el M-19 tomó el Palacio de Justicia en Bogotá.

Hechos clave a incluir (con contexto, no solo mencionar):
- Entraron disfrazados y el edificio ardió durante la retoma del Ejército.
- Magistrados y visitantes quedaron atrapados; hay desaparecidos.
- El archivo de la Corte se quemó y varias versiones oficiales no cierran.
- El cierre tiene que tratar las teorías como preguntas, no como hechos.
"""
        label, body = parse_generated_brief(raw)
        self.assertEqual(label, "La toma del Palacio")
        self.assertTrue(body.startswith("Resumen"))
        self.assertNotIn("Notas previas", body)

    def test_parse_brief_rejects_empty_shell(self) -> None:
        with self.assertRaises(ValueError):
            parse_generated_brief("TITLE: Solo un titulo\n\nResumen corto.")


class SubtitlesTests(unittest.TestCase):
    def test_split_and_cues(self) -> None:
        cfg = PipelineConfig()
        lines = split_narration_lines("Uno. Dos tres cuatro cinco seis.", max_chars=20)
        self.assertTrue(lines)
        cues = build_subtitle_cues("Narración de prueba con varias palabras aquí.", 4.0, cfg)
        self.assertTrue(cues)
        self.assertAlmostEqual(cues[-1][1], 4.0)


if __name__ == "__main__":
    unittest.main()
