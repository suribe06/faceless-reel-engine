Genera un guión para un video de true crime / misterio.

TEMA (título corto): {topic_label}

CONTEXTO Y BRIEF — usa TODO este material para el guión (hechos, cronología, ángulos, tono, enfoque narrativo):
{topic_brief}

El JSON debe tener exactamente esta estructura:
{{
  "title": "Título del video",
  "scenes": [
    {{
      "scene_number": 1,
      "narration": "Texto corto narrado en español colombiano...",
      "image_prompt": "English SDXL prompt, photorealistic, cinematic mood...",
      "duration_hint": {avg_scene_duration}
    }},
    {{
      "scene_number": 2,
      "narration": "Texto corto...",
      "image_prompt": "English SDXL prompt, photorealistic...",
      "duration_hint": {avg_scene_duration}
    }}
  ],
  "total_estimated_duration": {target_duration_mid}
}}

Requisitos de duración y ritmo (CRÍTICO — retención en redes):
- Duración total objetivo: entre {target_min} y {target_max} segundos ({target_min_minutes:.1f}–{target_max_minutes:.1f} minutos)
- Entre {min_scenes} y {max_scenes} escenas (cortas, dinámicas)
- Cada narration debe durar ~{avg_scene_duration}s al narrarse (~{narration_chars_min}–{narration_chars_max} caracteres por escena)
- IMPORTANTE: la duración REAL la marca el TTS — respeta el mínimo de caracteres por escena
- Narraciones punchy pero con suficiente texto para alcanzar la duración objetivo
- La suma de duration_hint es orientativa; prioriza longitud de narration
- Basa el guión en el brief de arriba: incluye contexto histórico, detalles concretos y tensión narrativa

Requisitos de imagen (IMPORTANTE):
- TODAS las escenas llevan exactamente un campo "image_prompt" (string en inglés)
- NO uses "image_prompts" ni arrays — el pipeline genera los dobles shots automáticamente
- Cada image_prompt debe ser fotorrealista, con iluminación, mood y detalle visual claro

Otros requisitos:
- Cada narration en español colombiano fluido para TTS
- Desarrolla la historia con contexto, tensión y teorías cuando el brief lo permita
- No incluyas key_moment — el pipeline lo asigna solo
