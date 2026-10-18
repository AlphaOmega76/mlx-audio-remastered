import { getSettings } from "./settings.js"

const $ = (id) => document.getElementById(id)
const send = (msg) => chrome.runtime.sendMessage({ target: "background", ...msg })

let activeTab = null
let state = { status: "idle" }
let serverOk = true
let readable = true

const ACTIVE = ["loading", "playing", "paused", "buffering"]

function statusText(s) {
  const what = s.mode === "selection" ? "selection" : s.mode === "pdf" ? "PDF" : "article"
  switch (s.status) {
    case "loading": return s.note || "Preparing… the first part takes a few seconds"
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

function labelAsPdf() {
  $("read").textContent = "Open PDF reader"
  $("hint").textContent =
    "Opens the PDF's text in a reader tab. Click any sentence there to start reading from that spot."
}

async function labelReadButton() {
  if (!activeTab) return
  // On the extension's own PDF reader tab: reading from the top; sentences are chosen on the page.
  if ((activeTab.url || "").startsWith(chrome.runtime.getURL("reader.html"))) {
    $("read").textContent = "Read from the start"
    $("hint").textContent = "Or click any sentence on the page to start reading from there."
    return render()
  }
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: activeTab.id },
      func: () => [document.contentType, window.getSelection().toString().trim().length],
    })
    if (result[0] === "application/pdf") labelAsPdf()
    else $("read").textContent = result[1] > 0 ? "Read selection" : "Read this page"
  } catch {
    // Chrome refuses the probe on PDFs saved on this Mac unless file access is allowed: go by the address.
    let isPdf = false
    try {
      isPdf = /\.pdf$/i.test(new URL(activeTab.url).pathname)
    } catch {}
    if (isPdf) labelAsPdf()
    else {
      readable = false
      $("read").textContent = "Read this page"
      $("hint").textContent = "Chrome doesn't allow extensions to read this kind of page."
    }
  }
  render()
}

async function checkServer() {
  const settings = await getSettings()
  let up = false
  try {
    up = (await fetch(`${settings.serverUrl}/v1/models`, { signal: AbortSignal.timeout(2500) })).ok
  } catch {}
  // If the server is not running but the installed helper can start it, pressing Read is fine.
  const status = up ? null : await send({ type: "serverStatus" })
  const canStart = !!(status && status.canStart)
  serverOk = up || canStart
  const notice = $("server")
  notice.textContent = canStart
    ? "The MLX-Audio server isn't running yet. It will start when you press Read."
    : `Can't reach the MLX-Audio server at ${settings.serverUrl}. Open the MLX-Audio app first.`
  notice.classList.toggle("hidden", up)
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
$("speed").oninput = () => {
  $("speedValue").textContent = `${Number($("speed").value).toFixed(1)}x`
}
$("speed").onchange = () => send({ type: "setSpeed", value: Number($("speed").value) })
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
  const { speed } = await getSettings()
  $("speed").value = speed
  $("speedValue").textContent = `${Number(speed).toFixed(1)}x`
  render()
  labelReadButton()
  checkServer()
}
init()
