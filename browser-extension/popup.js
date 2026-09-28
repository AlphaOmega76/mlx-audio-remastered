import { getSettings } from "./settings.js"

const $ = (id) => document.getElementById(id)
const send = (msg) => chrome.runtime.sendMessage({ target: "background", ...msg })

let activeTab = null
let state = { status: "idle" }
let serverOk = true
let readable = true

const ACTIVE = ["loading", "playing", "paused", "buffering"]

function statusText(s) {
  const what = s.mode === "selection" ? "selection" : "article"
  switch (s.status) {
    case "loading": return "Preparing… the first part takes a few seconds"
    case "buffering": return "Generating the next part…"
    case "paused": return `Paused · part ${s.cur + 1} of ${s.chunkCount}`
    case "playing": return `Reading the ${what} · part ${s.cur + 1} of ${s.chunkCount}`
    default: return ""
  }
}

function render() {
  const active = ACTIVE.includes(state.status)
  const sameTab = activeTab && state.tabId === activeTab.id

  $("player").classList.toggle("hidden", !active)
  $("idle").classList.toggle("hidden", active)
  $("restart").classList.toggle("hidden", !(active && !sameTab))

  if (active) {
    $("page-title").textContent = state.title || "Reading…"
    $("status").textContent = statusText(state)
    $("bar-fill").style.width = `${Math.round((state.progress || 0) * 100)}%`
    const paused = state.status === "paused"
    $("toggle").innerHTML = paused ? "&#9654;" : "&#10074;&#10074;"
    $("toggle").title = $("toggle").ariaLabel = paused ? "Resume" : "Pause"
  }

  const error = state.status === "error" ? state.error : ""
  $("error").textContent = error
  $("error").classList.toggle("hidden", !error)

  if (state.status === "done") $("hint").textContent = "Finished reading. Click to read the page again."
  $("read").disabled = !serverOk || !readable
}

async function labelReadButton() {
  if (!activeTab) return
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: activeTab.id },
      func: () => window.getSelection().toString().trim().length,
    })
    $("read").textContent = result > 0 ? "Read selection" : "Read this page"
  } catch {
    readable = false
    $("read").textContent = "Read this page"
    $("hint").textContent = "Chrome doesn't allow extensions to read this kind of page."
  }
  render()
}

async function checkServer() {
  const settings = await getSettings()
  try {
    const res = await fetch(`${settings.serverUrl}/v1/models`, { signal: AbortSignal.timeout(2500) })
    serverOk = res.ok
  } catch {
    serverOk = false
  }
  const notice = $("server")
  notice.textContent = `Can't reach the MLX-Audio server at ${settings.serverUrl}. Open the MLX-Audio app first.`
  notice.classList.toggle("hidden", serverOk)
  render()
}

$("read").onclick = async () => {
  if (!activeTab) return
  state = { status: "loading", tabId: activeTab.id }
  render()
  state = (await send({ type: "start", tabId: activeTab.id })) || state
  render()
}
$("restart").onclick = () => $("read").onclick()
$("toggle").onclick = async () => (state = await send({ type: "togglePause" }), render())
$("stop").onclick = async () => (state = await send({ type: "stop" }), render())
$("prev").onclick = () => send({ type: "skip", dir: -1 })
$("next").onclick = () => send({ type: "skip", dir: 1 })
$("settings").onclick = () => chrome.runtime.openOptionsPage()

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.target === "popup" && msg.type === "state") {
    state = msg.state
    render()
  }
})

async function init() {
  // ?tabId=N lets the popup page be opened in a normal tab (used by the automated tests).
  const override = new URLSearchParams(location.search).get("tabId")
  activeTab = override ? await chrome.tabs.get(Number(override)) : (await chrome.tabs.query({ active: true, currentWindow: true }))[0]
  state = (await send({ type: "getState" })) || state
  render()
  labelReadButton()
  checkServer()
}
init()
