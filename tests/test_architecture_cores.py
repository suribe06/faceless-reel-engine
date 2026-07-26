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
from pipeline.script_generator import normalize_script_scenes
from pipeline.subtitles import build_subtitle_cues, split_narration_lines
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
