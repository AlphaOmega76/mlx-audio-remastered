// Settings shared by the popup, options page, background worker and player.

export const QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16"

// Same models and voices the MLX-Audio web app offers by default.
export const MODELS = [
  {
    id: QWEN3_MODEL,
    label: "Qwen3-TTS",
    supportsInstruction: true,
    voices: ["ryan", "serena", "vivian", "uncle_fu", "aiden", "ono_anna", "sohee", "eric", "dylan"],
  },
  {
    id: "mlx-community/Kokoro-82M-bf16",
    label: "Kokoro",
    supportsInstruction: false,
    voices: ["af_heart", "af_bella", "af_nicole", "af_sarah", "am_adam", "am_michael", "bf_emma", "bm_george"],
  },
]

export const DEFAULTS = {
  serverUrl: "http://localhost:8000",
  model: QWEN3_MODEL,
  voice: "ryan",
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
export function buildSpeechBody(settings, input) {
  const model = MODELS.find((m) => m.id === settings.model) || MODELS[0]
  return {
    model: model.id,
    input,
    voice: settings.voice,
    speed: Number(settings.speed) || 1,
    response_format: "wav",
    ...(model.supportsInstruction && settings.instruction ? { instruct: settings.instruction } : {}),
  }
}
