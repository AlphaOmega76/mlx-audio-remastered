// The PDF reader page. The PDF's text is shown here (Chrome's own PDF viewer does not let
// extensions mark or click into it), and clicking a sentence starts reading from that sentence.
//
// The page works with the same background coordinator as normal web pages: content.js (loaded
// by reader.html) finds the sentences in <main> and highlights them, and the toolbar popup's
// controls keep working.
import { buildPages } from "./pdftext.js"
import { getSettings } from "./settings.js"

const $ = (id) => document.getElementById(id)
const send = (msg) => chrome.runtime.sendMessage({ target: "background", ...msg })

let myTabId = null
let note = "" // what the page is doing before reading starts (downloading the PDF, ...)
let loadError = "" // why the PDF could not be shown
let state = { status: "idle" }
const ACTIVE = ["loading", "playing", "paused", "buffering"]

function render() {
  const mine = state.tabId === myTabId
  const active = mine && ACTIVE.includes(state.status)
  $("controls").classList.toggle("hidden", !active)
  if (active) {
    const paused = state.status === "paused"
    $("toggle").innerHTML = paused ? "&#9654;" : "&#10074;&#10074;"
    $("toggle").title = $("toggle").ariaLabel = paused ? "Resume" : "Pause"
  }
  let text = note || "Click any sentence to start reading from there."
  if (mine) {
    if (state.status === "loading") text = state.note || "Preparing… the first part takes a few seconds"
    else if (state.status === "buffering") text = "Generating the next part…"
    else if (state.status === "paused") text = `Paused · part ${state.cur + 1} of ${state.chunkCount}`
    else if (state.status === "playing") text = `Reading · part ${state.cur + 1} of ${state.chunkCount}. Click another sentence to jump there.`
    else if (state.status === "done") text = "Finished reading. Click a sentence to read again."
  }
  $("status").textContent = text
  const error = loadError || (mine && state.status === "error" ? state.error : "")
  $("error").textContent = error
  $("error").classList.toggle("hidden", !error)
}

// The text node and offset the click landed on.
function caretAt(x, y) {
  if (document.caretPositionFromPoint) {
    const p = document.caretPositionFromPoint(x, y)
    if (p) return { node: p.offsetNode, offset: p.offset }
  }
  if (document.caretRangeFromPoint) {
    const r = document.caretRangeFromPoint(x, y)
    if (r) return { node: r.startContainer, offset: r.startOffset }
  }
  return null
}

async function startFrom(from) {
  window.getSelection().removeAllRanges() // a selection would make it read only the selection
  window.__mlxaFrom = from // content.js reads this to find the first sentence
  state = { status: "loading", tabId: myTabId }
  render()
  state = (await send({ type: "start", tabId: myTabId })) || state
  window.__mlxaFrom = null
  render()
}

function show(doc) {
  const main = $("doc")
  main.textContent = ""
  document.title = `${doc.title} · MLX-Audio Reader`
  $("title").textContent = doc.title
  const pages = buildPages(doc.pages)
  if (!pages.length) {
    const p = document.createElement("div")
    p.className = "empty"
    p.textContent = "No text found in this PDF."
    main.append(p)
    return
  }
  const jump = $("jump")
  jump.textContent = ""
  const first = document.createElement("option")
  first.textContent = "Jump to page…"
  first.value = ""
  jump.append(first)
  for (const pg of pages) {
    const div = document.createElement("div")
    div.className = "page"
    div.id = `page-${pg.page}`
    div.dataset.label = `Page ${pg.page}`
    for (const text of pg.paragraphs) {
      const p = document.createElement("p")
      p.textContent = text
      div.append(p)
    }
    main.append(div)
    const opt = document.createElement("option")
    opt.value = String(pg.page)
    opt.textContent = `Page ${pg.page}`
    jump.append(opt)
  }
  jump.classList.toggle("hidden", pages.length < 2)
}

$("doc").addEventListener("click", (e) => {
  const sel = window.getSelection()
  if (sel && !sel.isCollapsed) return // the user is selecting text, not choosing a start point
  if (!e.target.closest("p")) return
  const at = caretAt(e.clientX, e.clientY)
  if (!at || at.node.nodeType !== 3) return
  startFrom(at)
})
$("top").onclick = () => startFrom(null)
$("jump").onchange = (e) => {
  const n = e.target.value
  if (n) document.getElementById(`page-${n}`)?.scrollIntoView({ behavior: "smooth", block: "start" })
  e.target.value = ""
}
$("speed").oninput = () => {
  $("speedValue").textContent = `${Number($("speed").value).toFixed(1)}x`
}
$("speed").onchange = () => send({ type: "setSpeed", value: Number($("speed").value) })
$("toggle").onclick = async () => (state = await send({ type: "togglePause" }), render())
$("stop").onclick = async () => (state = await send({ type: "stop" }), render())
$("prev").onclick = () => send({ type: "skip", dir: -1 })
$("next").onclick = () => send({ type: "skip", dir: 1 })

chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.target === "popup" && msg.type === "state") {
    state = msg.state
    render()
  }
})

// ---- getting the PDF's text ----

function fail(message, canPick = true) {
  note = ""
  loadError = message
  $("pickrow").classList.toggle("hidden", !canPick)
  render()
}

// Sends the PDF to the server, which extracts its text, and shows the result.
async function openBytes(bytes, name, title) {
  loadError = ""
  $("pickrow").classList.add("hidden")
  if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-") return fail("This does not look like a PDF file.")

  note = "Starting the MLX-Audio server… the very first time can take a few minutes."
  render()
  const server = await send({ type: "ensureServer" })
  if (!server || !server.ok) return fail((server && server.error) || "Cannot reach the MLX-Audio server.", false)

  note = "Extracting the text…"
  render()
  try {
    const settings = await getSettings()
    const form = new FormData()
    form.append("file", new Blob([bytes], { type: "application/pdf" }), name)
    const res = await fetch(`${settings.serverUrl}/v1/documents/extract-text`, { method: "POST", body: form })
    if (!res.ok) {
      let detail = ""
      try { detail = (await res.json()).detail } catch {}
      return fail(detail || `The server could not read this PDF (error ${res.status}).`, res.status !== 422)
    }
    const data = await res.json()
    note = ""
    show({ title: title || name.replace(/\.pdf$/i, "") || "PDF", pages: data.page_texts || [data.text] })
    render()
  } catch (e) {
    fail("Could not reach the MLX-Audio server to read this PDF.", false)
  }
}

async function loadFromAddress(src, title) {
  const name = decodeURIComponent(new URL(src).pathname.split("/").pop() || "document.pdf") || "document.pdf"
  note = "Downloading the PDF…"
  render()
  let bytes
  try {
    const res = await fetch(src, { credentials: "include" })
    if (!res.ok) return fail(`Could not download the PDF (error ${res.status}). You can choose the file instead.`)
    bytes = await res.arrayBuffer()
  } catch {
    const local = src.startsWith("file:")
    const blocked = local && !(await chrome.extension.isAllowedFileSchemeAccess())
    return fail(
      blocked
        ? "Chrome has not allowed this extension to open files on your Mac. Open chrome://extensions, choose MLX-Audio Reader, Details, and turn on \u201cAllow access to file URLs\u201d, then reload this page. Or choose the file below."
        : "Could not download the PDF. You can choose the file instead."
    )
  }
  await openBytes(bytes, name, title)
}

async function loadFromFile(file) {
  if (!file) return
  await openBytes(await file.arrayBuffer(), file.name, file.name.replace(/\.pdf$/i, ""))
}

$("pick").onclick = () => $("file").click()
$("file").onchange = (e) => loadFromFile(e.target.files[0])
document.addEventListener("dragover", (e) => e.preventDefault())
document.addEventListener("drop", (e) => {
  e.preventDefault()
  loadFromFile(e.dataTransfer.files[0])
})

async function init() {
  myTabId = (await chrome.tabs.getCurrent())?.id ?? null
  const params = new URLSearchParams(location.search)
  const src = params.get("src")
  $("title").textContent = params.get("title") || "PDF reader"
  const { speed } = await getSettings()
  $("speed").value = speed
  $("speedValue").textContent = `${Number(speed).toFixed(1)}x`
  state = (await send({ type: "getState" })) || state
  render()
  if (!src) return fail("Open a PDF in Chrome and press Read to see its text here, or choose a PDF file.")
  await loadFromAddress(src, params.get("title") || "")
}
init()
