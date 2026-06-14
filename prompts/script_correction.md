Tu respuesta anterior no fue JSON válido o no cumple el schema requerido.
Error: {error}

Corrige y responde ÚNICAMENTE con JSON válido, sin markdown ni texto extra.

Checklist obligatorio:
- Cada escena debe tener: scene_number, narration, image_prompt, duration_hint
- image_prompt es SIEMPRE un string en inglés (nunca null, nunca vacío)
- NO uses image_prompts — solo image_prompt por escena
- narration nunca vacía
- total_estimated_duration dentro del rango pedido
- Entre {min_scenes} y {max_scenes} escenas
