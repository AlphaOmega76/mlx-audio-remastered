// The PDF reader page. The PDF's text is shown here (Chrome's own PDF viewer does not let
// extensions mark or click into it), and clicking a sentence starts reading from that sentence.
//
// The page works with the same background coordinator as normal web pages: content.js (loaded
// by reader.html) finds the sentences in <main> and highlights them, and the toolbar popup's
// controls keep working.
import { buildPages } from "./pdftext.js"

const $ = (id) => document.getElementById(id)
const send = (msg) => chrome.runtime.sendMessage({ target: "background", ...msg })

let myTabId = null
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
  let text = "Click any sentence to start reading from there."
  if (mine) {
    if (state.status === "loading") text = state.note || "Preparing… the first part takes a few seconds"
    else if (state.status === "buffering") text = "Generating the next part…"
    else if (state.status === "paused") text = `Paused · part ${state.cur + 1} of ${state.chunkCount}`
    else if (state.status === "playing") text = `Reading · part ${state.cur + 1} of ${state.chunkCount}. Click another sentence to jump there.`
    else if (state.status === "done") text = "Finished reading. Click a sentence to read again."
  }
  $("status").textContent = text
  const error = mine && state.status === "error" ? state.error : ""
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

async function init() {
  myTabId = (await chrome.tabs.getCurrent())?.id ?? null
  const id = new URLSearchParams(location.search).get("id")
  const key = `pdf:${id}`
  const doc = id ? (await chrome.storage.session.get(key))[key] : null
  if (!doc) {
    $("doc").innerHTML = ""
    const p = document.createElement("div")
    p.className = "empty"
    p.textContent = "This reader page has expired. Go back to the PDF and press Read again."
    $("doc").append(p)
    return
  }
  show(doc)
  state = (await send({ type: "getState" })) || state
  render()
}
init()
