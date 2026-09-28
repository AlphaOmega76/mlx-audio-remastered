import { MODELS, DEFAULTS, getSettings } from "./settings.js"

const $ = (id) => document.getElementById(id)
let settings = { ...DEFAULTS }

const save = (patch) => {
  settings = { ...settings, ...patch }
  return chrome.storage.local.set(patch)
}

function fillVoices() {
  const model = MODELS.find((m) => m.id === settings.model) || MODELS[0]
  $("voice").innerHTML = model.voices.map((v) => `<option value="${v}">${v}</option>`).join("")
  if (!model.voices.includes(settings.voice)) settings.voice = model.voices[0]
  $("voice").value = settings.voice
  $("instructionRow").classList.toggle("hidden", !model.supportsInstruction)
}

async function init() {
  settings = await getSettings()
  $("model").innerHTML = MODELS.map((m) => `<option value="${m.id}">${m.label}</option>`).join("")
  $("model").value = settings.model
  $("serverUrl").value = settings.serverUrl
  $("instruction").value = settings.instruction
  $("speed").value = settings.speed
  $("speedValue").textContent = `${Number(settings.speed).toFixed(1)}x`
  fillVoices()
}

$("serverUrl").onchange = () => save({ serverUrl: $("serverUrl").value.trim().replace(/\/+$/, "") || DEFAULTS.serverUrl })
$("model").onchange = async () => {
  settings.model = $("model").value
  fillVoices()
  await save({ model: settings.model, voice: settings.voice })
}
$("voice").onchange = () => save({ voice: $("voice").value })
$("instruction").onchange = () => save({ instruction: $("instruction").value.trim() })
$("speed").oninput = () => {
  $("speedValue").textContent = `${Number($("speed").value).toFixed(1)}x`
}
$("speed").onchange = () => save({ speed: Number($("speed").value) })

$("test").onclick = async () => {
  const status = $("status")
  status.className = ""
  status.textContent = "Checking…"
  try {
    const res = await fetch(`${settings.serverUrl}/v1/models`, { signal: AbortSignal.timeout(4000) })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    status.className = "ok"
    status.textContent = "Connected to the MLX-Audio server."
  } catch {
    status.className = "bad"
    status.textContent = `Can't reach ${settings.serverUrl}. Is the MLX-Audio app running?`
  }
}

init()
