#!/usr/bin/env python3
"""Download royalty-free background music for true crime / mystery videos."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MUSIC_DIR = PROJECT_ROOT / "assets" / "music"
MANIFEST_PATH = MUSIC_DIR / "tracks.json"

# Mixkit License — free for commercial use: https://mixkit.co/license/
MIXKIT_TRACKS: list[dict[str, str]] = [
    {"id": "671", "title": "Piano Horror", "source": "Mixkit"},
    {"id": "64", "title": "Dark Shadows", "source": "Mixkit"},
    {"id": "625", "title": "Fragments Of Bangkok", "source": "Mixkit"},
    {"id": "188", "title": "Dark Ambient", "source": "Mixkit"},
    {"id": "565", "title": "Mystery Ambient", "source": "Mixkit"},
    {"id": "615", "title": "Suspense Background", "source": "Mixkit"},
    {"id": "538", "title": "Cinematic Tension", "source": "Mixkit"},
    {"id": "658", "title": "Horror Drone", "source": "Mixkit"},
    {"id": "890", "title": "Dark Cinematic", "source": "Mixkit"},
    {"id": "404", "title": "Investigation Mood", "source": "Mixkit"},
    {"id": "283", "title": "Eerie Piano", "source": "Mixkit"},
    {"id": "564", "title": "Night Mystery", "source": "Mixkit"},
    {"id": "892", "title": "Ominous Strings", "source": "Mixkit"},
    {"id": "141", "title": "Dark Documentary", "source": "Mixkit"},
    {"id": "165", "title": "Crime Scene", "source": "Mixkit"},
    {"id": "140", "title": "Deep Suspense", "source": "Mixkit"},
    {"id": "303", "title": "Shadow Walk", "source": "Mixkit"},
    {"id": "370", "title": "Cold Case", "source": "Mixkit"},
    {"id": "420", "title": "Unsolved", "source": "Mixkit"},
    {"id": "605", "title": "Final Revelation", "source": "Mixkit"},
]


def _download(url: str, dest: Path, timeout: int = 120) -> None:
    response = requests.get(url, timeout=timeout, stream=True)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                handle.write(chunk)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("download_music")

    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, str]] = []
    failed: list[str] = []

    for track in MIXKIT_TRACKS:
        track_id = track["id"]
        title = track["title"]
        slug = title.lower().replace(" ", "_")
        filename = f"mixkit_{track_id}_{slug}.mp3"
        dest = MUSIC_DIR / filename
        url = f"https://assets.mixkit.co/music/{track_id}/{track_id}.mp3"

        if dest.exists() and dest.stat().st_size > 10_000:
            logger.info("✓ Ya existe: %s", filename)
            downloaded.append({**track, "file": filename, "url": url})
            continue

        try:
            logger.info("↓ Descargando: %s", title)
            _download(url, dest)
            if dest.stat().st_size < 10_000:
                raise RuntimeError("archivo demasiado pequeño")
            downloaded.append({**track, "file": filename, "url": url})
        except Exception as exc:
            logger.error("✗ Falló %s: %s", title, exc)
            failed.append(title)
            if dest.exists():
                dest.unlink(missing_ok=True)

    MANIFEST_PATH.write_text(
        json.dumps(downloaded, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    attribution = MUSIC_DIR / "ATTRIBUTION.md"
    attribution.write_text(
        "# Música de fondo\n\n"
        "Pistas descargadas desde [Mixkit](https://mixkit.co/free-stock-music/) "
        "bajo [Mixkit License](https://mixkit.co/license/) — uso gratuito en "
        "proyectos comerciales y no comerciales.\n\n"
        "| Archivo | Título | Fuente |\n"
        "|---------|--------|--------|\n"
        + "\n".join(
            f"| `{t['file']}` | {t['title']} | Mixkit |" for t in downloaded
        )
        + "\n",
        encoding="utf-8",
    )

    logger.info("\nDescargadas: %d | Fallidas: %d | Carpeta: %s", len(downloaded), len(failed), MUSIC_DIR)
    return 0 if len(downloaded) >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
