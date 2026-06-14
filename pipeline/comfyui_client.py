"""ComfyUI server lifecycle helpers."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from config import PipelineConfig

logger = logging.getLogger(__name__)


def _comfyui_port(base_url: str) -> int:
    parsed = urlparse(base_url)
    return parsed.port or 8188


def is_comfyui_running(config: PipelineConfig) -> bool:
    """Return True if ComfyUI responds on the configured base URL."""
    url = f"{config.COMFYUI_BASE_URL.rstrip('/')}/system_stats"
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _resolve_comfyui_dir(config: PipelineConfig) -> Path:
    """Resolve ComfyUI installation directory."""
    if config.COMFYUI_DIR is not None:
        return Path(config.COMFYUI_DIR).expanduser()
    return Path.home() / "comfy" / "ComfyUI"


def _start_comfyui_process(config: PipelineConfig) -> None:
    """Launch ComfyUI in the background with low VRAM mode."""
    comfy_dir = _resolve_comfyui_dir(config)
    main_py = comfy_dir / "main.py"
    venv_python = comfy_dir / ".venv" / "bin" / "python"

    if not main_py.exists():
        raise FileNotFoundError(
            f"No se encontró ComfyUI en {comfy_dir}. "
            "Instálalo o define COMFYUI_DIR en config.py."
        )

    python_bin = venv_python if venv_python.exists() else "python3"
    port = _comfyui_port(config.COMFYUI_BASE_URL)
    log_path = config.LOG_DIR / "comfyui_server.log"

    cmd = [
        str(python_bin),
        str(main_py),
        "--port",
        str(port),
    ]
    if config.COMFYUI_LOW_VRAM:
        cmd.append("--lowvram")
        logger.info("ComfyUI en modo --lowvram (VRAM GPU, no afecta calidad de imagen)")
    else:
        logger.info("ComfyUI sin --lowvram (más VRAM GPU requerida)")

    logger.info("Iniciando ComfyUI: %s", " ".join(cmd))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(log_path, "a", encoding="utf-8")
    log_handle.write(f"\n--- ComfyUI start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_handle.flush()

    subprocess.Popen(
        cmd,
        cwd=str(comfy_dir),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def wait_for_comfyui(config: PipelineConfig, timeout: int | None = None) -> None:
    """Block until ComfyUI is reachable or raise TimeoutError."""
    deadline = time.time() + (timeout or config.COMFYUI_STARTUP_TIMEOUT)
    while time.time() < deadline:
        if is_comfyui_running(config):
            logger.info("ComfyUI listo en %s", config.COMFYUI_BASE_URL)
            return
        time.sleep(2)

    log_hint = config.LOG_DIR / "comfyui_server.log"
    raise TimeoutError(
        f"ComfyUI no respondió en {config.COMFYUI_STARTUP_TIMEOUT}s. "
        f"Revisa el log: {log_hint}"
    )


def ensure_comfyui_running(config: PipelineConfig) -> None:
    """Ensure ComfyUI is running; auto-start if configured and not reachable."""
    if is_comfyui_running(config):
        logger.info("ComfyUI ya está corriendo en %s", config.COMFYUI_BASE_URL)
        return

    if not config.COMFYUI_AUTO_START:
        raise ConnectionError(
            f"ComfyUI no responde en {config.COMFYUI_BASE_URL}. "
            "Inícialo manualmente o activa COMFYUI_AUTO_START en config.py."
        )

    logger.info("ComfyUI no detectado — arrancando servidor...")
    _start_comfyui_process(config)
    wait_for_comfyui(config)


def stop_comfyui(config: PipelineConfig) -> None:
    """Best-effort stop via comfy-cli, falling back to process kill on port."""
    port = _comfyui_port(config.COMFYUI_BASE_URL)

    try:
        subprocess.run(
            ["uvx", "--from", "comfy-cli", "comfy", "stop"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    if is_comfyui_running(config):
        logger.warning(
            "ComfyUI sigue activo en puerto %d. Detén el proceso manualmente si hace falta.",
            port,
        )
    else:
        logger.info("ComfyUI detenido")
