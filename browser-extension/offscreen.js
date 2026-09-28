// Hidden page that owns the audio. It is kept alive by Chrome while audio plays,
// which lets narration continue after the popup closes or you switch tabs.
//
// It asks the MLX-Audio server for speech one chunk at a time, keeps a few chunks
// generated ahead of the playback position (so a 30-minute article does not get
// synthesized all at once), and plays them back to back.
import { buildSpeechBody } from "./settings.js"

const LOOKAHEAD = 2 // chunks to generate ahead of the one playing
const KEEP_BEHIND = 8 // chunks kept behind the playing one (for skipping back)

const audio = new Audio()
let token = 0 // bumps on every load/stop so stale async work can tell it is obsolete
let settings = null
let texts = []
let urls = [] // object URLs of generated audio, by chunk index
let cur = 0
let wantPlay = false // the user wants sound (false while paused)
let waiting = false // playback reached a chunk that is not generated yet
let pendingFrac = null // start this far into the chunk once it loads
let ctrl = null // aborts the in-flight request
let inflight = -1 // chunk index being generated right now
let wake = null
let lastReport = 0
let seq = 0 // echoed in progress reports so the coordinator can drop stale ones

const send = (msg) => chrome.runtime.sendMessage({ target: "background", ...msg }).catch(() => {})

function report(force = false) {
  const now = performance.now()
  if (!force && now - lastReport < 200) return
  lastReport = now
  send({
    type: "progress",
    seq,
    chunk: cur,
    // While waiting for the next chunk the <audio> element still holds the previous
    // chunk's end position, which would be a wrong place to resume from.
    time: waiting ? 0 : audio.currentTime || 0,
    duration: waiting ? 0 : Number.isFinite(audio.duration) ? audio.duration : 0,
    playing: !audio.paused && !audio.ended,
    buffering: waiting,
    generated: urls.filter(Boolean).length,
    total: texts.length,
  })
}

function nudge() {
  if (wake) {
    const w = wake
    wake = null
    w()
  }
}

function nextToGenerate() {
  for (let i = cur; i < texts.length && i <= cur + LOOKAHEAD; i++) if (!urls[i]) return i
  return -1
}

async function synth(text, signal) {
  const res = await fetch(`${settings.serverUrl}/v1/audio/speech`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildSpeechBody(settings, text)),
    signal,
  })
  if (!res.ok) {
    let detail = ""
    try {
      detail = (await res.json()).detail || ""
    } catch {}
    throw new Error(`Server error ${res.status}${detail ? `: ${detail}` : ""}`)
  }
  return res.blob()
}

async function pump(myToken) {
  while (myToken === token) {
    const i = nextToGenerate()
    if (i === -1) {
      await new Promise((resolve) => (wake = resolve))
      continue
    }
    ctrl = new AbortController()
    inflight = i
    try {
      const blob = await synth(texts[i], ctrl.signal)
      if (myToken !== token) return
      urls[i] = URL.createObjectURL(blob)
      inflight = -1
      if (waiting && i === cur) startCurrent()
      report(true)
    } catch (e) {
      inflight = -1
      if (myToken !== token) return
      if (e.name === "AbortError") continue // a seek changed what we need
      send({ type: "error", message: e.message === "Failed to fetch" ? "Cannot reach the MLX-Audio server." : e.message })
      return
    }
  }
}

// Load and (if wanted) play chunk `cur`, or wait for it to be generated.
function startCurrent() {
  const url = urls[cur]
  if (!url) {
    waiting = true
    audio.pause()
    report(true)
    nudge()
    return
  }
  waiting = false
  const frac = pendingFrac
  pendingFrac = null
  audio.src = url
  audio.onloadedmetadata = () => {
    if (frac && Number.isFinite(audio.duration)) audio.currentTime = frac * audio.duration
    if (wantPlay) audio.play().catch((e) => send({ type: "error", message: `Playback blocked: ${e.message}` }))
    report(true)
  }
  // free audio well behind the playhead
  for (let j = 0; j < cur - KEEP_BEHIND; j++) {
    if (urls[j]) {
      URL.revokeObjectURL(urls[j])
      urls[j] = undefined
    }
  }
  nudge()
}

audio.ontimeupdate = () => report()
audio.onpause = () => report(true)
audio.onplaying = () => report(true)
audio.onended = () => {
  if (cur + 1 < texts.length) {
    cur++
    pendingFrac = null
    startCurrent()
  } else {
    send({ type: "done" })
  }
}

function reset() {
  token++
  if (ctrl) ctrl.abort()
  ctrl = null
  inflight = -1
  audio.pause()
  audio.removeAttribute("src")
  audio.load()
  urls.forEach((u) => u && URL.revokeObjectURL(u))
  urls = []
  texts = []
  waiting = false
  pendingFrac = null
  nudge()
}

function load(msg) {
  reset()
  settings = msg.settings
  texts = msg.texts
  seq = msg.seq || 0
  cur = msg.startAt || 0 // a revived session resumes where it left off
  pendingFrac = msg.frac || 0
  wantPlay = true
  const myToken = token
  pump(myToken)
  startCurrent()
}

function seek(index, frac) {
  if (index < 0 || index >= texts.length) return
  // If the spot we jump to is not generated and something else is being made, drop it
  // and restart generation at the new spot.
  if (ctrl && !urls[index] && inflight !== index) ctrl.abort()
  cur = index
  pendingFrac = frac || 0
  wantPlay = true
  startCurrent()
}

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || msg.target !== "offscreen") return
  switch (msg.type) {
    case "load":
      load(msg)
      break
    case "pause":
      wantPlay = false
      audio.pause()
      break
    case "resume":
      wantPlay = true
      if (waiting) startCurrent()
      else audio.play().catch(() => {})
      break
    case "seek":
      seq = msg.seq || 0
      seek(msg.index, msg.frac)
      break
    case "stop":
      reset()
      break
  }
})
