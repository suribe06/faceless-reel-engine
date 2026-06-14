# Pipeline de video faceless — Guía completa

Generador automatizado de videos verticales estilo true crime / misterio para redes sociales: guión (Ollama) → narración (Kokoro TTS) → imágenes (ComfyUI SDXL) → video (MoviePy).

## Flujo secuencial

El pipeline es **estrictamente secuencial**. Cada fase usa la GPU/RAM de forma exclusiva y **libera recursos al terminar** antes de pasar a la siguiente.

```
┌─────────────────────────────────────────────────────────────────┐
│  CLI: python main.py --topic "..." [--duration-min] [--duration-max] │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASO 1 — Guión (Ollama)                                        │
│  • Lee prompts desde prompts/script_*.md                        │
│  • Genera JSON: título + 6–20 escenas (según duración objetivo) │
│  • narration (ES) corta + image_prompt(s) (EN) por escena       │
│  → release_after_script(): descarga modelo Ollama de VRAM       │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASO 2 — Audio (Kokoro TTS)                                    │
│  • Narra cada scene.narration → temp/audio/scene_N.wav          │
│  • Calcula duración real por escena (audio_duration)            │
│  → release_after_tts(): libera pipeline Kokoro de memoria       │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASO 3 — Imágenes (ComfyUI + SDXL)                             │
│  • Auto-arranca ComfyUI si no está corriendo (--lowvram)        │
│  • Negative prompt: prompts/image_negative.md                   │
│  • Sufijo visual: prompts/image_style_suffix.md                 │
│  • 1 imagen por escena; 2 en hook / twist / cierre (ComfyUI)  │
│  • Genera 640×1152 → temp/images/scene_N.png (o _a/_b)         │
│  → release_after_images(): descarga modelos SDXL de VRAM        │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASO 4 — Video (MoviePy + FFmpeg)                            │
│  • Ken Burns, crossfade entre escenas, subtítulos del guión   │
│  • Marca de agua + música aleatoria de assets/music/          │
│  • Limpia temp/ al finalizar (salvo --keep-temp)                │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
                    output/{titulo}_{timestamp}.mp4
```

## Requisitos previos

| Servicio | Puerto | Notas |
|----------|--------|-------|
| Ollama | 11434 | Modelo default: `qwen3.5:9b` |
| ComfyUI | 8188 | Auto-arranque activado por defecto |
| espeak-ng | — | Requerido por Kokoro |
| FFmpeg | — | Requerido por MoviePy |

Checkpoint SDXL en `~/comfy/ComfyUI/models/checkpoints/` (default: `realvisxlV50_v50Bakedvae.safetensors`).

## Comando básico

```bash
cd faceless-reel-engine
source .venv/bin/activate

python main.py \
  --topic "El misterio de la bruja de Blair colombiana" \
  --duration-min 180 \
  --duration-max 240
```

### Flags útiles

| Flag | Descripción |
|------|-------------|
| `--topic` | Tema del video (obligatorio) |
| `--duration-min` / `--duration-max` | Rango de duración objetivo en segundos |
| `--model` | Modelo Ollama |
| `--voice` | Voz Kokoro (`es`, `ef_dora`, `em_alex`, …) |
| `--checkpoint` | Checkpoint SDXL en ComfyUI |
| `--keep-temp` | Conservar `temp/` para depuración |
| `--resume-from` | `tts` \| `images` \| `video` — reanuda desde `temp/pipeline_state.json` |
| `--no-subtitles` | Desactiva subtítulos quemados desde el guión |

### Música de fondo

Descarga 20 pistas royalty-free (Mixkit, mood true crime/misterio):

```bash
python scripts/download_music.py
```

El pipeline elige la pista **default** (`mixkit_188_dark_ambient.mp3`). Cambiar en `config.py` → `DEFAULT_MUSIC_FILE`. Aleatorio: `MUSIC_MODE = "random"`.

Ver `assets/music/META_COMPLIANCE.md` para licencia Mixkit y publicación en Facebook/Instagram.

### Subtítulos

No hace falta Whisper: el guión ya tiene el texto exacto por escena. MoviePy quema subtítulos sincronizados con `audio_duration`, dividiendo cada `narration` en líneas legibles. Desactivar: `--no-subtitles` o `SUBTITLES_ENABLED = False`.

## Configuración (`config.py`)

Parámetros principales sin tocar código de lógica:

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| `TARGET_DURATION_MIN_SECONDS` | 180 | Duración mínima objetivo |
| `TARGET_DURATION_MAX_SECONDS` | 240 | Duración máxima objetivo |
| `OLLAMA_MODEL` | qwen3.5:9b | Modelo de guión |
| `TTS_VOICE` | es | Voz Kokoro |
| `COMFYUI_IMAGE_WIDTH/HEIGHT` | 640×1152 | Resolución de generación |
| `IMAGE_WIDTH/HEIGHT` | 1080×1920 | Resolución del video final |
| `TTS_CHARS_PER_SECOND` | 18 | Calibración duración real Kokoro (ES) |
| `COMFYUI_AUTO_START` | True | Arranca ComfyUI si no responde |
| `COMFYUI_LOW_VRAM` | True | Modo VRAM GPU (`--lowvram`); no reduce calidad |
| `KEN_BURNS_ENABLED` | True | Zoom + pan suave en cada imagen |
| `KEN_BURNS_ZOOM` | 1.12 | Factor de zoom Ken Burns |
| `LOGO_PATH` | assets/logo/logo.png | Marca de agua (PNG con alpha ideal) |
| `LOGO_WIDTH` | 140 | Ancho del logo en px (video 1080×1920) |
| `LOGO_OPACITY` | 0.55 | Opacidad de la marca de agua |
| `LOGO_MARGIN` | 28 | Margen desde esquina inferior derecha |
| `MUSIC_VOLUME` | 0.15 | Volumen música de fondo |
| `MUSIC_MODE` | default | `default` (fija) o `random` |
| `DEFAULT_MUSIC_FILE` | mixkit_188_dark_ambient.mp3 | Pista por defecto |
| `PROMPTS_DIR` | prompts/ | Carpeta de prompts editables |

La cantidad de escenas y duración media por escena se **calculan automáticamente** desde el rango de duración (no hay constantes fijas).

## Prompts editables (`prompts/`)

**Recomendación:** mantener prompts en `.md` separados del código. Ventajas:

- Iteras tono, estilo y restricciones sin riesgo de romper Python
- Puedes versionar cambios de prompt en git de forma legible
- Placeholders dinámicos (`{topic}`, `{min_scenes}`, …) siguen funcionando

Ver [`prompts/README.md`](prompts/README.md) para la lista completa y placeholders.

Tras editar un prompt, **reinicia el pipeline** para recargar (se cachean en memoria durante la ejecución).

### Qué va en cada archivo

| Archivo | Quién lo consume |
|---------|------------------|
| `script_system.md` | Ollama — personalidad del guionista |
| `script_user.md` | Ollama — estructura JSON + requisitos de duración |
| `script_correction.md` | Ollama — mensaje de reintento |
| `image_negative.md` | ComfyUI — negative prompt SDXL |
| `image_style_suffix.md` | ComfyUI — sufijo añadido a cada imagen |

**TTS no tiene prompt de texto:** Kokoro lee directamente el campo `narration` de cada escena del JSON. Para cambiar voz/velocidad usa `config.py` o `--voice`.

## Estructura de carpetas

```
faceless-reel-engine/
├── main.py                 # Orquestador CLI
├── config.py               # Parámetros centralizados
├── PIPELINE.md             # Esta guía
├── prompts/                # Prompts editables (.md)
├── pipeline/
│   ├── script_generator.py # Paso 1 — Ollama
│   ├── tts_generator.py    # Paso 2 — Kokoro
│   ├── image_generator.py  # Paso 3 — ComfyUI
│   ├── video_assembler.py  # Paso 4 — MoviePy
│   ├── subtitles.py        # Subtítulos desde narration
│   ├── preflight.py        # Checks al inicio
│   ├── script_validator.py # Validación pre-ComfyUI
│   ├── state.py            # Resume temp/pipeline_state.json
│   ├── resources.py        # Liberación secuencial de VRAM/RAM
│   ├── ollama_client.py    # Descarga modelo Ollama
│   ├── comfyui_client.py   # Auto-arranque ComfyUI
│   └── prompt_loader.py    # Carga prompts/*.md
├── assets/
│   ├── logo/logo.png       # Marca de agua (requerido para branding)
│   └── music/              # Música de fondo (.mp3)
├── output/                 # Videos finales
├── temp/                   # Audio + imágenes temporales
└── logs/                   # run_*.log, latest_error.log, comfyui_server.log
```

## Formato del guión (JSON)

Ollama produce un JSON con esta estructura:

```json
{
  "title": "Título del video",
  "scenes": [
    {
      "scene_number": 1,
      "key_moment": "hook",
      "narration": "Texto corto en español colombiano...",
      "image_prompts": [
        "Wide establishing shot, english SDXL prompt...",
        "Close-up detail, different angle, english SDXL prompt..."
      ],
      "duration_hint": 8
    },
    {
      "scene_number": 2,
      "key_moment": null,
      "narration": "Otra narración corta...",
      "image_prompt": "Single english SDXL prompt...",
      "duration_hint": 8
    }
  ],
  "total_estimated_duration": 210
}
```

Escenas con **doble shot** (2 imágenes ComfyUI, audio partido en MoviePy):
- Escena 1 → `key_moment: "hook"`
- Escena central → `"twist"`
- Última escena → `"closing"`

El pipeline reasigna `key_moment` automáticamente si el LLM se equivoca de índice.

La **duración real del video** la marca el TTS (`audio_duration` por escena), no el `duration_hint` del guión. Si el audio queda bajo `--duration-min`, el pipeline intenta añadir escenas extra automáticamente.

## Gestión de memoria (8 GB VRAM)

En laptops con 8 GB, **Ollama y ComfyUI no pueden coexistir en GPU**:

1. Ollama genera el guión (~6 GB VRAM)
2. Se descarga Ollama antes del paso 3
3. ComfyUI genera imágenes en modo `--lowvram`
4. Se descargan modelos SDXL antes del encode de video

Si falla por OOM, revisa `logs/latest_error.log` y cierra apps que usen GPU.

## Logs y depuración

| Archivo | Contenido |
|---------|-----------|
| `logs/run_YYYYMMDD_HHMMSS.log` | Log completo de cada ejecución |
| `logs/latest_error.log` | Último error (traceback resumido) |
| `logs/comfyui_server.log` | Salida del servidor ComfyUI |

El paso 4 (MoviePy/FFmpeg) puede tardar **3–5 minutos** en un video de ~2 min sin escribir logs intermedios — es normal.

## Tiempos estimados (RTX 4060 8 GB)

| Duración objetivo | Escenas | Tiempo total aprox. |
|-------------------|---------|---------------------|
| 1–2 min | 6–12 | 15–25 min |
| 3–4 min | 15–20 | 45–90 min |
| 5–6 min | 20–30 | 1.5–2.5 h |

La mayor parte del tiempo está en ComfyUI (~15–20 s por imagen; +3 imágenes extra en escenas clave) y en el encode final de FFmpeg.

## Troubleshooting rápido

| Problema | Solución |
|----------|----------|
| OOM en ComfyUI | Verificar que Ollama se descargó (log paso 1); ComfyUI con `--lowvram` |
| ComfyUI no responde | `COMFYUI_AUTO_START=True` o arrancar manualmente |
| JSON inválido de Ollama | Ajustar `prompts/script_system.md`; usar `qwen3.5:9b` con `think: false` |
| Sin música | Añadir `.mp3` a `assets/music/` |
| Sin marca de agua | Colocar `assets/logo/logo.png` (PNG transparente recomendado) |
| Pipeline “congelado” en paso 4 | FFmpeg codificando — esperar o revisar `output/*.mp4` creciendo |

## Próximos pasos sugeridos

- Añadir música de fondo en `assets/music/`
- Ajustar tono narrativo en `prompts/script_system.md`
- Probar `--duration-min 180 --duration-max 240` para monetización en plataformas que premian videos largos
