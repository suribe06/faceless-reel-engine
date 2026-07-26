# Domain glossary — faceless-reel-engine

Terms used across the pipeline. Architecture reviews should use these names.

## Core flow

| Term | Meaning |
|------|---------|
| **Topic brief** | Short label + detailed brief that seeds script generation (`TopicBrief`). |
| **Script** | LLM-produced document: title, scenes, estimated duration. |
| **Scene** | One narrative beat: narration, image prompt(s), optional key moment, later audio/image artifacts. |
| **Key moment** | Strategic scene tagged `hook`, `twist`, or `closing` — gets dual image shots. |
| **Narration** | Spoken Spanish text for a scene (TTS input). |
| **Image prompt** | English SDXL prompt for a scene (and `image_prompts` for dual shots). |
| **RunState** | Owned pipeline document: topic, title, scenes bag, step, artifact paths. |
| **DurationPolicy** | Single owner of “long enough?” — estimate gates, TTS thresholds, extension decisions. |
| **TTS** | Kokoro text-to-speech producing per-scene wavs and measured `audio_duration`. |
| **ComfyUI images** | SDXL generation via the ComfyUI adapter (lifecycle + HTTP). |
| **Video assembly** | Planner + encode adapters (ffmpeg default, moviepy legacy) into a vertical MP4. |
| **Resume** | Continue from a saved RunState step (`tts` \| `images` \| `video`). |

## Adapters (external systems)

| Term | Meaning |
|------|---------|
| **Ollama adapter** | Chat + model unload (`pipeline/ollama_client.py`). |
| **ComfyUI adapter** | Process lifecycle + queue/poll/download/free (`pipeline/comfyui_client.py`). |

## Orchestration

| Term | Meaning |
|------|---------|
| **RunOrchestrator** | Stage order, resume, duration extension, resource release (`pipeline/orchestrator.py`). |
| **Preflight** | Checks that local tools/services are available before a run. |
