# Pipeline de video faceless — Guía completa

Generador automatizado de videos verticales estilo true crime / misterio para redes sociales: guión (Ollama) → narración (Kokoro TTS) → imágenes (ComfyUI SDXL) → video (FFmpeg).

## Flujo secuencial

El pipeline es **estrictamente secuencial**. Cada fase usa la GPU/RAM de forma exclusiva y **libera recursos al terminar** antes de pasar a la siguiente.

Si `--topic` es una frase y no hay `assets/topics/<slug>.txt`, Ollama escribe ese brief y el video sigue solo. Un archivo que ya existe no se regenera.

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
│  • Narra cada frase y mide su duración → temp/audio/scene_N.wav │
│  • Esas duraciones alimentan los subtítulos                     │
│  → release_after_tts(): libera pipeline Kokoro de memoria       │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASO 3 — Imágenes (ComfyUI + SDXL)                             │
│  • Auto-arranca ComfyUI si no está corriendo (--lowvram)        │
│  • El checkpoint se queda en VRAM entre tomas                   │
│  • 20 steps, dpmpp_2m, CFG 6 (lightning/hyper/turbo: 6 steps)   │
│  • 1 imagen por escena; 2 en hook / twist / cierre              │
│  • visual_anchor en inglés se antepone a cada prompt           │
│  → release_after_images(): descarga modelos SDXL de VRAM        │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│  PASO 4 — Video (FFmpeg)                                        │
│  • Zoom + pan, subtítulos por frase, hook_line los primeros s  │
│  • Logo en cada clip; la mezcla de audio es una sola pasada    │
│  • Voz cerca de −14 LUFS; la música cede mientras hay narración │
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
| FFmpeg | — | Ensambla el video |

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

No hace falta Whisper. Kokoro narra frase por frase y FFmpeg quema esas líneas con la duración medida. Dentro de una frase larga el corte sigue el largo del texto. Los primeros 2.6 s muestran `hook_line` arriba. Desactivar subtítulos: `--no-subtitles` o `SUBTITLES_ENABLED = False`. El hook se apaga con `HOOK_OVERLAY_ENABLED = False`.

## Configuración (`config.py`)

Parámetros principales sin tocar código de lógica:

| Parámetro | Default | Descripción |
|-----------|---------|-------------|
| `TARGET_DURATION_MIN_SECONDS` | 180 | Duración mínima objetivo |
| `TARGET_DURATION_MAX_SECONDS` | 240 | Duración máxima objetivo |
| `OLLAMA_MODEL` | qwen3.5:9b | Modelo de guión |
| `TTS_VOICE` | es | Voz Kokoro |
| `COMFYUI_IMAGE_WIDTH/HEIGHT` | 640×1152 | Resolución de generación |
| `COMFYUI_STEPS` / `COMFYUI_CFG` | 20 / 6.0 | RealVisXL full. Un checkpoint con lightning, hyper o turbo en el nombre usa 6 steps y CFG 1.5 |
| `COMFYUI_SAMPLER` | dpmpp_2m | Sampler de ComfyUI |
| `COMFYUI_SEED` | -1 | Semilla base de la corrida. Un número ≥ 0 repite el mismo look |
| `IMAGE_WIDTH/HEIGHT` | 1080×1920 | Resolución del video final |
| `TTS_CHARS_PER_SECOND` | 18 | Calibración duración real Kokoro (ES) |
| `COMFYUI_AUTO_START` | True | Arranca ComfyUI si no responde |
| `COMFYUI_LOW_VRAM` | True | Modo VRAM GPU (`--lowvram`); no reduce calidad |
| `KEN_BURNS_ENABLED` | True | Zoom + pan suave en cada imagen |
| `KEN_BURNS_ZOOM` | 1.12 | Zoom final; el plano arranca en 1.0 |
| `HOOK_OVERLAY_SECONDS` | 2.6 | Segundos de la frase grande al inicio |
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
├── main.py                 # CLI (thin)
├── config.py               # Parámetros centralizados
├── CONTEXT.md              # Glosario de dominio
├── PIPELINE.md             # Esta guía
├── prompts/                # Prompts editables (.md)
├── tests/                  # Checks de núcleos puros
├── pipeline/
│   ├── orchestrator.py     # Orden de pasos, resume, extensiones
│   ├── run_state.py        # Documento RunState (scenes + artifacts)
│   ├── duration_policy.py  # Umbrales de duración (único dueño)
│   ├── script_generator.py # Paso 1 — dominio guión (Ollama via adapter)
│   ├── tts_generator.py    # Paso 2 — Kokoro
│   ├── image_generator.py  # Paso 3 — dominio imágenes (ComfyUI via adapter)
│   ├── video_assembler.py  # Paso 4 — validación y llamada a FFmpeg
│   ├── ffmpeg_assembler.py # Paso 4 — Ken Burns, subs, hook, audio
│   ├── assembly_common.py  # Planner helpers compartidos
│   ├── subtitles.py        # Subtítulos desde narration
│   ├── preflight.py        # Checks al inicio
│   ├── script_validator.py # Re-export validate_before_images
│   ├── state.py            # Persistencia (re-export run_state)
│   ├── ollama_client.py    # Adapter: chat + unload VRAM
│   ├── comfyui_client.py   # Adapter: lifecycle + HTTP generate
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
  "hook_line": "Nadie denunció el disparo",
  "visual_anchor": "1990s Bogotá rainy night, 35mm, low-key light",
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

Escenas con **doble shot** (2 imágenes ComfyUI, el audio de la escena se parte entre las dos):
- Escena 1 → `key_moment: "hook"`
- Escena central → `"twist"`
- Última escena → `"closing"`

El pipeline reasigna `key_moment` automáticamente si el LLM se equivoca de índice.

La **duración real del video** la marca el TTS (`audio_duration` por escena), no el `duration_hint` del guión. Si el audio queda bajo `--duration-min`, el pipeline intenta añadir escenas extra automáticamente.

## Gestión de memoria (8 GB VRAM)

En laptops con 8 GB, **Ollama y ComfyUI no pueden coexistir en GPU**:

1. Ollama genera el guión (~6 GB VRAM)
2. Se descarga Ollama antes del paso 3
3. ComfyUI genera todas las imágenes en `--lowvram` sin descargar el checkpoint entre tomas
4. Se descargan los modelos SDXL antes del encode de video

Si falla por OOM, revisa `logs/latest_error.log` y cierra apps que usen GPU.

## Logs y depuración

| Archivo | Contenido |
|---------|-----------|
| `logs/run_YYYYMMDD_HHMMSS.log` | Log completo de cada ejecución |
| `logs/latest_error.log` | Último error (traceback resumido) |
| `logs/comfyui_server.log` | Salida del servidor ComfyUI |

El paso 4 escribe un log por clip (`[ffmpeg] Escena N/M lista`). El cierre solo mezcla el audio; no vuelve a comprimir el video.

## Cuánto tarda

No hay una tabla medida en esta máquina. El reloj es el comando `time` del README. Casi todo el tiempo sigue estando en ComfyUI: una imagen por escena, dos en hook, twist y cierre. El checkpoint ya no se recarga en cada toma, y el video no se codifica dos veces.

## Troubleshooting rápido

| Problema | Solución |
|----------|----------|
| OOM en ComfyUI | Verificar que Ollama se descargó (log paso 1); ComfyUI con `--lowvram` |
| ComfyUI no responde | `COMFYUI_AUTO_START=True` o arrancar manualmente |
| JSON inválido de Ollama | Ajustar `prompts/script_system.md`; usar `qwen3.5:9b` con `think: false` |
| Sin música | Añadir `.mp3` a `assets/music/` |
| Sin marca de agua | Colocar `assets/logo/logo.png` (PNG transparente recomendado) |
| El paso 4 parece quieto | Mira `logs/run_*.log`: cada clip deja una línea `[ffmpeg]` |

## Próximos pasos sugeridos

- Añadir música de fondo en `assets/music/`
- Ajustar tono narrativo en `prompts/script_system.md`
- Probar `--duration-min 180 --duration-max 240` para monetización en plataformas que premian videos largos
