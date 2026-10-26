# Faceless Reel Engine

Pipeline de automatización en Python para generar videos verticales estilo true crime / misterio: imágenes SDXL + narración TTS + música de fondo.

**Documentación completa del flujo:** [PIPELINE.md](PIPELINE.md) · **Editar prompts:** [prompts/README.md](prompts/README.md)

## Prerequisitos

Antes de ejecutar el pipeline, asegúrate de tener corriendo localmente:

1. **Ollama** — `http://localhost:11434`
   ```bash
   ollama serve
   ollama pull qwen3.5:9b
   ```

2. **ComfyUI** — `http://127.0.0.1:8188`
   - Debe estar corriendo con un checkpoint SDXL fotorrealista instalado
   - Default: `realvisxlV50_v50Bakedvae.safetensors`

3. **espeak-ng** (requerido por Kokoro TTS)
   ```bash
   sudo apt install espeak-ng
   ```

4. **FFmpeg** (motor de video por defecto)
   ```bash
   sudo apt install ffmpeg
   ```

## Instalación

```bash
git clone https://github.com/suribe06/faceless-reel-engine.git
cd faceless-reel-engine
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Música royalty-free (Mixkit)
python scripts/download_music.py

# Logo de marca de agua (opcional)
# Coloca tu PNG en assets/logo/logo.png
```

## Música de fondo

Descarga las pistas con `python scripts/download_music.py` o coloca `.mp3` manualmente en `assets/music/`. El pipeline usa una pista por defecto (`mixkit_188_dark_ambient.mp3`) o elige al azar según `MUSIC_MODE` en `config.py`. Volumen: 15% por defecto. Sin música, el video se genera solo con narración.

## Temas / briefs

Crea un brief en `assets/topics/` usando `topic_template.txt` como guía. Luego pásalo al pipeline por slug:

```bash
# Lista briefs disponibles
python main.py --list-topics

# Usa un brief guardado (assets/topics/mi-caso.txt)
python main.py --topic mi-caso
```

También puedes pasar el tema como frase corta en `--topic` sin archivo previo.

## Uso

```bash
# Básico (frase corta)
python main.py --topic "El misterio del vuelo MH370"

# Con opciones
python main.py \
  --topic "El crimen del Palacio de Justicia" \
  --model qwen3.5:9b \
  --duration-min 180 \
  --duration-max 240 \
  --voice es \
  --checkpoint realvisxlV50_v50Bakedvae.safetensors

# Conservar archivos temporales para depuración
python main.py --topic "La bruja de Blair colombiana" --keep-temp
```

## Flujo del pipeline

1. **Guión** — Ollama genera escenas en JSON (narración ES, `hook_line`, `visual_anchor`, prompts EN)
2. **TTS** — Kokoro narra cada frase y guarda la duración real → `temp/audio/scene_N.wav`
3. **Imágenes** — ComfyUI genera SDXL y deja el checkpoint cargado entre tomas → `temp/images/scene_N.png`
4. **Video** — FFmpeg hace zoom/pan, quema subtítulos y la frase de apertura, mezcla la voz a −14 LUFS → `output/`

## Medir un video

Ollama tiene que estar arriba. ComfyUI arranca solo si no responde en el puerto 8188. Un video corto basta para ver el archivo y el reloj de pared; el default de 3–4 min genera muchas más imágenes.

```bash
time python main.py \
  --topic "El misterio del vuelo MH370" \
  --duration-min 45 \
  --duration-max 60
```

Usa el `python` que ya importa `kokoro`, `ollama` y `requests`. El `.venv` de esta carpeta no sirve: fue creado en otro proyecto y no tiene esas librerías.

Al terminar, el log imprime `Video final: ...`. El mp4 queda en `output/`. `time` muestra el tiempo real en la línea `real`. El detalle paso a paso está en `logs/run_*.log`.

`--keep-temp` conserva `temp/` por si hay que reanudar con `--resume-from tts|images|video` sin repetir lo que ya salió bien.

## Estructura

```
faceless-reel-engine/
├── main.py
├── config.py
├── pipeline/           # Módulos del pipeline
├── prompts/            # Prompts editables (.md)
├── scripts/            # Utilidades (descarga de música)
├── assets/
│   ├── music/          # .mp3 (no versionados; descargar con script)
│   ├── logo/           # Marca de agua (local)
│   └── topics/         # Briefs de temas (solo topic_template.txt en git)
├── output/             # Videos finales
├── temp/               # Archivos temporales (se limpia al final)
└── logs/               # Logs de ejecución
```

## Troubleshooting

| Problema | Solución |
|----------|----------|
| ComfyUI no responde | Verifica que corre en `http://127.0.0.1:8188` |
| Ollama timeout | Descarga el modelo: `ollama pull qwen3.5:9b` |
| VRAM insuficiente | Reduce `COMFYUI_IMAGE_WIDTH`/`HEIGHT` en `config.py` |
| Kokoro falla | Instala `espeak-ng`: `sudo apt install espeak-ng` |
| Checkpoint no encontrado | Ajusta `SDXL_CHECKPOINT` en `config.py` al nombre exacto en ComfyUI |
| Sin música | Ejecuta `python scripts/download_music.py` |

## Configuración

Edita `config.py` o usa flags CLI para ajustar modelo, voz, checkpoint, duración y rutas.

Voces Kokoro en español: `es` (default, ef_dora), `ef_dora`, `em_alex`, `em_santa`.
