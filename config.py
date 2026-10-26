"""Centralized configuration for the faceless video pipeline."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PipelineConfig:
    """All configurable parameters for the video generation pipeline."""

    OLLAMA_MODEL: str = "qwen3.5:9b"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    COMFYUI_BASE_URL: str = "http://127.0.0.1:8188"
    COMFYUI_DIR: Path | None = None  # default: ~/comfy/ComfyUI
    COMFYUI_AUTO_START: bool = True
    COMFYUI_LOW_VRAM: bool = True  # VRAM de GPU (8 GB), no RAM del sistema
    COMFYUI_STARTUP_TIMEOUT: int = 120
    SDXL_CHECKPOINT: str = "realvisxlV50_v50Bakedvae.safetensors"
    TTS_VOICE: str = "es"
    TTS_SPEED: float = 1.0
    TTS_CHARS_PER_SECOND: float = 18.0  # Kokoro ES habla ~17–19 chars/s (calibrado)
    TTS_CHUNK_SILENCE_MS: int = 80  # pausa entre fragmentos TTS largos
    MAX_DURATION_EXTENSIONS: int = 2  # reintentos Ollama si TTS queda corto
    TARGET_DURATION_MIN_SECONDS: int = 180  # 3 min — mínimo deseado del video
    TARGET_DURATION_MAX_SECONDS: int = 240  # 4 min — máximo deseado del video
    COMFYUI_IMAGE_WIDTH: int = 640   # resolución de generación (VRAM-friendly, 9:16)
    COMFYUI_IMAGE_HEIGHT: int = 1152
    COMFYUI_STEPS: int = 20  # RealVisXL full; un checkpoint *lightning*/*hyper* baja solo
    COMFYUI_CFG: float = 6.0
    COMFYUI_SAMPLER: str = "dpmpp_2m"
    COMFYUI_SCHEDULER: str = "karras"
    COMFYUI_SEED: int = -1  # <0 = una semilla base por corrida; los shots salen de esa base
    COMFYUI_IMAGE_RETRIES: int = 2
    IMAGE_ANCHOR: str = (
        "photorealistic cinematic still, consistent film look, "
        "moody low-key lighting, 35mm, no readable text"
    )
    IMAGE_WIDTH: int = 1080          # resolución del video final (FFmpeg escala desde 640×1152)
    IMAGE_HEIGHT: int = 1920
    MUSIC_VOLUME: float = 0.15
    MUSIC_MODE: str = "default"  # "default" | "random"
    DEFAULT_MUSIC_FILE: str = "mixkit_188_dark_ambient.mp3"
    MUSIC_MIN_TRACKS: int = 5
    SCENE_CROSSFADE_SECONDS: float = 0.0  # crossfade off by default (faster encode)
    SUBTITLES_ENABLED: bool = True  # subtítulos quemados desde las frases medidas en el TTS
    SUBTITLE_FONT_PATH: Path | None = None
    SUBTITLE_FONT_SIZE: int = 42
    SUBTITLE_MAX_CHARS: int = 38
    SUBTITLE_MARGIN_X: int = 48
    SUBTITLE_MARGIN_Y: int = 220
    SUBTITLE_BG_OPACITY: float = 0.72
    KEN_BURNS_ENABLED: bool = True
    KEN_BURNS_ZOOM: float = 1.12  # zoom final; el plano arranca en 1.0 y hace pan
    KEN_BURNS_PAN_MODES: tuple[str, ...] = field(
        default_factory=lambda: ("left_to_right", "right_to_left", "top_to_bottom")
    )
    HOOK_OVERLAY_ENABLED: bool = True
    HOOK_OVERLAY_SECONDS: float = 2.6
    HOOK_FONT_SIZE: int = 58
    VIDEO_FPS: int = 24
    FFMPEG_PRESET: str = "veryfast"
    FFMPEG_CRF: int = 23
    FFMPEG_THREADS: int = 0  # 0 = auto (todos los cores)
    LOGO_PATH: Path = field(default_factory=lambda: Path("assets/logo/logo.png"))
    LOGO_WIDTH: int = 140
    LOGO_OPACITY: float = 0.55
    LOGO_MARGIN: int = 28
    OUTPUT_DIR: Path = field(default_factory=lambda: Path("output"))
    TEMP_DIR: Path = field(default_factory=lambda: Path("temp"))
    ASSETS_MUSIC_DIR: Path = field(default_factory=lambda: Path("assets/music"))
    TOPICS_DIR: Path = field(default_factory=lambda: Path("assets/topics"))
    LOG_DIR: Path = field(default_factory=lambda: Path("logs"))
    PROMPTS_DIR: Path = field(default_factory=lambda: Path("prompts"))

    def target_duration_mid(self) -> int:
        """Midpoint of the target video duration range."""
        return (self.TARGET_DURATION_MIN_SECONDS + self.TARGET_DURATION_MAX_SECONDS) // 2

    def scene_duration_bounds(self) -> tuple[int, int]:
        """Min/max seconds per scene — shorter cuts for better retention."""
        mid = self.target_duration_mid()
        if mid <= 90:
            return 5, 8
        if mid <= 180:
            return 6, 10
        return 8, 12

    def scene_count_range(self) -> tuple[int, int]:
        """Estimate min/max scene count from target duration."""
        scene_min, scene_max = self.scene_duration_bounds()
        min_scenes = max(6, (self.TARGET_DURATION_MIN_SECONDS + scene_max - 1) // scene_max)
        max_scenes = max(min_scenes + 2, self.TARGET_DURATION_MAX_SECONDS // scene_min)
        return min_scenes, max_scenes

    def avg_scene_duration_seconds(self) -> int:
        """Average scene length derived from target duration and scene count."""
        min_scenes, max_scenes = self.scene_count_range()
        expected_scenes = max(1, (min_scenes + max_scenes) // 2)
        scene_min, _scene_max = self.scene_duration_bounds()
        return max(scene_min, self.target_duration_mid() // expected_scenes)

    def narration_char_bounds(self) -> tuple[int, int]:
        """Min/max narration length in chars, calibrated to Kokoro TTS speed."""
        min_scenes, max_scenes = self.scene_count_range()
        expected_scenes = max(1, (min_scenes + max_scenes) // 2)
        secs_per_scene = self.TARGET_DURATION_MIN_SECONDS / expected_scenes
        cps = self.TTS_CHARS_PER_SECOND
        char_min = max(90, int(secs_per_scene * cps * 0.95))
        char_max = max(char_min + 20, int(secs_per_scene * cps * 1.15))
        return char_min, char_max

    def resolve_paths(self, base_dir: Path | None = None) -> None:
        """Resolve relative paths against the project root."""
        root = base_dir or Path(__file__).resolve().parent
        if not self.OUTPUT_DIR.is_absolute():
            self.OUTPUT_DIR = root / self.OUTPUT_DIR
        if not self.TEMP_DIR.is_absolute():
            self.TEMP_DIR = root / self.TEMP_DIR
        if not self.ASSETS_MUSIC_DIR.is_absolute():
            self.ASSETS_MUSIC_DIR = root / self.ASSETS_MUSIC_DIR
        if not self.TOPICS_DIR.is_absolute():
            self.TOPICS_DIR = root / self.TOPICS_DIR
        if not self.LOG_DIR.is_absolute():
            self.LOG_DIR = root / self.LOG_DIR
        if not self.PROMPTS_DIR.is_absolute():
            self.PROMPTS_DIR = root / self.PROMPTS_DIR
        if not self.LOGO_PATH.is_absolute():
            self.LOGO_PATH = root / self.LOGO_PATH

    def ensure_directories(self) -> None:
        """Create output, temp, assets, and logs directories if missing."""
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        (self.TEMP_DIR / "audio").mkdir(parents=True, exist_ok=True)
        (self.TEMP_DIR / "images").mkdir(parents=True, exist_ok=True)
        self.ASSETS_MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        self.TOPICS_DIR.mkdir(parents=True, exist_ok=True)
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.LOGO_PATH.parent.mkdir(parents=True, exist_ok=True)
