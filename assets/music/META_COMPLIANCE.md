# Música de fondo — licencia y Meta (FB / IG)

## Licencia Mixkit (Stock Music Free License)

Pistas descargadas desde [Mixkit](https://mixkit.co/free-stock-music/) bajo la licencia **Stock Music Free License** ([texto oficial](https://mixkit.co/license/#musicFree)).

**Permitido (según Mixkit):**
- Uso comercial y personal
- YouTube, Facebook, Instagram y otras redes sociales
- Anuncios online, podcasts, videos con monetización externa
- **No exige atribución** (aunque se agradece)

**Prohibido (según Mixkit):**
- CDs, DVDs, videojuegos, emisiones de TV o radio
- Revender o redistribuir el MP3 tal cual
- Registrar la pista en servicios de gestión de derechos como si fuera tuya
- Remixear y reclamar autoría

| Archivo | Título | Fuente |
|---------|--------|--------|
| `mixkit_671_piano_horror.mp3` | Piano Horror | Mixkit |
| `mixkit_64_dark_shadows.mp3` | Dark Shadows | Mixkit |
| `mixkit_625_fragments_of_bangkok.mp3` | Fragments Of Bangkok | Mixkit |
| `mixkit_188_dark_ambient.mp3` | Dark Ambient | Mixkit |
| `mixkit_565_mystery_ambient.mp3` | Mystery Ambient | Mixkit |
| `mixkit_615_suspense_background.mp3` | Suspense Background | Mixkit |
| `mixkit_538_cinematic_tension.mp3` | Cinematic Tension | Mixkit |
| `mixkit_658_horror_drone.mp3` | Horror Drone | Mixkit |
| `mixkit_890_dark_cinematic.mp3` | Dark Cinematic | Mixkit |
| `mixkit_404_investigation_mood.mp3` | Investigation Mood | Mixkit |
| `mixkit_283_eerie_piano.mp3` | Eerie Piano | Mixkit |
| `mixkit_564_night_mystery.mp3` | Night Mystery | Mixkit |
| `mixkit_892_ominous_strings.mp3` | Ominous Strings | Mixkit |
| `mixkit_141_dark_documentary.mp3` | Dark Documentary | Mixkit |
| `mixkit_165_crime_scene.mp3` | Crime Scene | Mixkit |
| `mixkit_140_deep_suspense.mp3` | Deep Suspense | Mixkit |
| `mixkit_303_shadow_walk.mp3` | Shadow Walk | Mixkit |
| `mixkit_370_cold_case.mp3` | Cold Case | Mixkit |
| `mixkit_420_unsolved.mp3` | Unsolved | Mixkit |
| `mixkit_605_final_revelation.mp3` | Final Revelation | Mixkit |

## Meta (Facebook + Instagram) — qué debes saber

### Tu caso: música **incrustada en el video** (export del pipeline)

El pipeline mezcla la pista en el MP4 final. **No** usas el sticker de música de Instagram ni la biblioteca licenciada de Meta dentro de la app. Eso cambia las reglas:

| Fuente | Uso en cuenta business / monetización |
|--------|----------------------------------------|
| Biblioteca musical **dentro** de IG/FB (canciones populares) | Pensada para uso **personal, no comercial** — riesgo en cuentas business y Reels monetizados |
| [Meta Sound Collection](https://www.facebook.com/sound/collection/) | Royalty-free **dentro del ecosistema Meta** — la opción más segura si editas en Meta |
| **Mixkit** (licencia Free, uso comercial explícito en redes) | **Legalmente permitido** por la licencia del proveedor; Meta no “certifica” terceros como certifica Sound Collection |

### Riesgo real de demonetización / mute

1. **Legal (licencia):** Mixkit Free License cubre publicación comercial en redes, incluido FB/IG, si respetas sus restricciones.
2. **Técnico (Meta):** El sistema puede escanear audio. Pistas royalty-free de terceros a veces generan **falsos positivos** (menos frecuente en Meta que en YouTube, pero posible).
3. **Monetización Meta (Reels Play, etc.):** Las reglas del programa exigen cumplir políticas de contenido y derechos. Audio con licencia comercial clara ayuda; **no sustituye** leer las condiciones actuales de tu programa de monetización.

### Recomendaciones prácticas

1. **Guarda prueba:** conserva este `ATTRIBUTION.md`, `tracks.json` y la URL de cada pista en Mixkit.
2. **Volumen bajo** (`MUSIC_VOLUME = 0.15`): la narración manda; menos conflicto con detección de audio.
3. **Cuenta business:** evita añadir *otra* música con el sticker de IG encima del video ya exportado.
4. **Si Meta mutea o limita un video:** revisa el panel de derechos; puedes apelar con enlace a [Mixkit License](https://mixkit.co/license/) y al track original.
5. **Máxima seguridad solo-Meta:** a largo plazo, considera pistas de **Meta Sound Collection** para campañas pagadas o monetización agresiva — requiere otro flujo de edición.

### Pista default del pipeline

Config actual: `mixkit_188_dark_ambient.mp3` (Dark Ambient) — ambiente discreto, no compite con la voz.

Alternativas recomendadas (mismo nicho, también discretas):

- `mixkit_615_suspense_background.mp3` — diseñada como fondo de suspense
- `mixkit_565_mystery_ambient.mp3` — similar a Dark Ambient, un poco más “misterio”
- `mixkit_141_dark_documentary.mp3` — tono documental true crime
- `mixkit_404_investigation_mood.mp3` — mood investigación, muy temático

Para cambiar: `DEFAULT_MUSIC_FILE` en `config.py`. Para volver a aleatorio: `MUSIC_MODE = "random"`.

**Disclaimer:** esto no es asesoría legal. Para decisiones de monetización a gran escala, consulta un abogado de propiedad intelectual o usa exclusivamente Meta Sound Collection.
