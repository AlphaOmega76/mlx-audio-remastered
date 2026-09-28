// Settings shared by the popup, options page, background worker and player.

// Tried the 4-bit build (2026-09-28) to cut generation time (it is roughly 2x faster than
// bf16 here), but its output was unintelligible for the user, so back to bf16.
export const QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16"

// Same models and voices the MLX-Audio web app offers by default.
export const MODELS = [
  {
    id: QWEN3_MODEL,
    label: "Qwen3-TTS",
    supportsInstruction: true,
    boundedLength: true, // roughly 1 token per character; used to cap runaway generations
    voices: ["ryan", "serena", "vivian", "uncle_fu", "aiden", "ono_anna", "sohee", "eric", "dylan"],
  },
  {
    id: "mlx-community/Kokoro-82M-bf16",
    label: "Kokoro",
    supportsInstruction: false,
    voices: ["af_heart", "af_bella", "af_nicole", "af_sarah", "am_adam", "am_michael", "bf_emma", "bm_george"],
  },
]

// Kokoro sounded better and more consistent than Qwen3 to the user (2026-09-28), so it is
// the default for now. Qwen3 is still selectable from the options page.
export const DEFAULTS = {
  serverUrl: "http://localhost:8000",
  model: "mlx-community/Kokoro-82M-bf16",
  voice: "af_heart",
  instruction: "calm, measured narrator tone",
  speed: 1,
}

export async function getSettings() {
  const stored = await chrome.storage.local.get(DEFAULTS)
  const settings = { ...DEFAULTS, ...stored }
  settings.serverUrl = String(settings.serverUrl || DEFAULTS.serverUrl).replace(/\/+$/, "")
  const model = MODELS.find((m) => m.id === settings.model) || MODELS[0]
  if (!model.voices.includes(settings.voice)) settings.voice = model.voices[0]
  settings.model = model.id
  return settings
}

// Request body for POST /v1/audio/speech (WAV keeps chunk boundaries gapless).
// `chunk` = { pauseMs, narrationId }: the server trims silence, caps long pauses, levels
// the volume, matches the pace of the narration's first chunk and adds a fixed pause, so
// separately generated chunks sound like one narration.
export function buildSpeechBody(settings, input, chunk = {}) {
  const model = MODELS.find((m) => m.id === settings.model) || MODELS[0]
  return {
    model: model.id,
    input,
    voice: settings.voice,
    speed: Number(settings.speed) || 1,
    response_format: "wav",
    trim_silence: true,
    max_pause_ms: 500,
    loudness_db: -20,
    pause_ms: chunk.pauseMs || 0,
    ...(chunk.narrationId ? { narration_id: chunk.narrationId } : {}),
    // the model sometimes fails to stop; bound how long a chunk can run
    ...(model.boundedLength ? { max_tokens: Math.min(1200, Math.ceil(input.length * 1.6) + 40) } : {}),
    ...(model.supportsInstruction && settings.instruction ? { instruct: settings.instruction } : {}),
  }
}
