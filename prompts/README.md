# Prompts del pipeline

Edita estos archivos para cambiar el comportamiento del LLM y de ComfyUI **sin tocar código Python**.

Tras editar, reinicia el pipeline (`python main.py ...`) para que cargue los cambios.

## Archivos

| Archivo | Uso |
|---------|-----|
| `script_system.md` | System prompt de Ollama (personalidad del guionista) |
| `script_user.md` | User prompt con el tema y requisitos del JSON |
| `script_correction.md` | Mensaje de reintento si el JSON falla |
| `image_negative.md` | Negative prompt SDXL (ComfyUI) |
| `image_style_suffix.md` | Sufijo añadido a cada `image_prompt` del guión |

## Placeholders en `script_user.md`

Estos valores los calcula el pipeline automáticamente desde `config.py` y los flags `--duration-min` / `--duration-max`:

- `{topic_label}` — título corto del brief
- `{topic_brief}` — texto completo del brief
- `{target_min}`, `{target_max}` — duración objetivo en segundos
- `{target_min_minutes}`, `{target_max_minutes}` — mismo rango en minutos
- `{target_duration_mid}` — punto medio del rango
- `{min_scenes}`, `{max_scenes}` — cantidad de escenas esperada
- `{avg_scene_duration}` — segundos promedio por escena
- `{narration_chars_min}`, `{narration_chars_max}` — longitud de texto por escena

En `script_correction.md` usa `{error}`, `{min_scenes}` y `{max_scenes}`.

## TTS

Kokoro no usa prompts de texto: narra el campo `narration` de cada escena del JSON, frase por frase.
El JSON también pide `hook_line` (frase corta en pantalla) y `visual_anchor` (look en inglés que se antepone a cada imagen).
La voz y velocidad se configuran en `config.py` (`TTS_VOICE`, `TTS_SPEED`) o con `--voice`.

## Tips

- En `script_user.md`, las llaves dobles `{{` `}}` en el ejemplo JSON son literales (escapadas para Python `.format()`).
- `image_style_suffix.md` es opcional: déjalo vacío o borra el contenido para desactivarlo.
- Mantén `script_system.md` enfatizando "solo JSON" — modelos como qwen3.5 tienden a añadir texto extra.
