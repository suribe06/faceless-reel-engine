"""ComfyUI adapter: process lifecycle + HTTP generate API."""

from __future__ import annotations

import gc
import logging
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from config import PipelineConfig

logger = logging.getLogger(__name__)

IMAGE_TIMEOUT_SECONDS = 120


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


def _format_comfyui_error(messages: Any) -> str:
    """Extract a readable error summary from ComfyUI status messages."""
    if not isinstance(messages, list):
        return str(messages)[:1000]

    for item in messages:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        event, payload = item[0], item[1]
        if event != "execution_error" or not isinstance(payload, dict):
            continue

        node_type = payload.get("node_type", "unknown")
        raw_message = payload.get("exception_message", "error desconocido")
        first_line = raw_message.strip().split("\n", maxsplit=1)[0]
        if "out of memory" in raw_message.lower():
            return (
                f"ComfyUI ({node_type}): {first_line}. "
                "Causa probable: Ollama u otra app usando la GPU. "
                "El pipeline intenta descargar Ollama antes de generar imágenes; "
                "cierra apps pesadas y reinicia ComfyUI con --lowvram."
            )
        return f"ComfyUI ({node_type}): {first_line}"

    return str(messages)[:1000]


def queue_prompt(base_url: str, workflow: dict[str, Any], client_id: str) -> str:
    """Submit workflow to ComfyUI and return prompt_id."""
    url = f"{base_url.rstrip('/')}/prompt"
    payload: dict[str, Any] = {"prompt": workflow, "client_id": client_id}

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
    except requests.ConnectionError as exc:
        raise ConnectionError(
            f"No se pudo conectar con ComfyUI en {base_url}. "
            "Verifica que ComfyUI esté corriendo en el puerto 8188."
        ) from exc
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"ComfyUI rechazó el workflow ({response.status_code}): {response.text[:500]}"
        ) from exc

    data = response.json()
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"ComfyUI no retornó prompt_id: {data}")
    return prompt_id


def wait_for_completion(
    base_url: str,
    prompt_id: str,
    timeout: int = IMAGE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Poll ComfyUI history until the prompt completes or times out."""
    url = f"{base_url.rstrip('/')}/history/{prompt_id}"
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                history = response.json()
                if prompt_id in history:
                    entry = history[prompt_id]
                    status = entry.get("status", {})
                    if status.get("completed"):
                        return entry
                    if status.get("status_str") == "error":
                        messages = status.get("messages", [])
                        summary = _format_comfyui_error(messages)
                        logger.error("ComfyUI detalle completo: %s", messages)
                        raise RuntimeError(summary)
        except requests.RequestException:
            pass
        time.sleep(1)

    raise TimeoutError(
        f"Timeout ({timeout}s) esperando imagen de ComfyUI (prompt_id={prompt_id})"
    )


def download_image(
    base_url: str,
    history_entry: dict[str, Any],
    dest_path: Path,
) -> None:
    """Download generated image from ComfyUI outputs."""
    outputs = history_entry.get("outputs", {})
    for node_output in outputs.values():
        images = node_output.get("images", [])
        if not images:
            continue

        image_info = images[0]
        params = {
            "filename": image_info["filename"],
            "subfolder": image_info.get("subfolder", ""),
            "type": image_info.get("type", "output"),
        }
        url = f"{base_url.rstrip('/')}/view"
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        dest_path.write_bytes(response.content)
        return

    raise RuntimeError("ComfyUI completó pero no se encontró imagen en outputs")


def free_vram(base_url: str) -> None:
    """Ask ComfyUI to unload models and free CUDA cache."""
    url = f"{base_url.rstrip('/')}/free"
    try:
        response = requests.post(
            url,
            json={"unload_models": True, "free_memory": True},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("No se pudo liberar VRAM en ComfyUI: %s", exc)


def release_comfyui_resources(config: PipelineConfig) -> None:
    """Unload all ComfyUI models from VRAM after the image phase."""
    free_vram(config.COMFYUI_BASE_URL)
    logger.info("Modelos ComfyUI descargados de VRAM")


def _gc_gpu() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            if hasattr(torch.cuda, "ipc_collect"):
                torch.cuda.ipc_collect()
    except ImportError:
        pass


def release_after_images(config: PipelineConfig) -> None:
    """Unload ComfyUI after image generation."""
    logger.info("--- Liberando recursos del paso 3 (ComfyUI) ---")
    release_comfyui_resources(config)
    _gc_gpu()
