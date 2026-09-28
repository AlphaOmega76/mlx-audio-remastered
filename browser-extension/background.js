// Coordinates a narration: pulls text out of the tab, chunks it, hands the chunks to
// the offscreen player, and turns playback progress into "which sentence is being
// spoken" so the page can highlight it.
import { getSettings } from "./settings.js"

const SESSION_KEY = "session"
const OFFSCREEN_URL = "offscreen.html"
// Every chunk boundary is a chance for the voice's pace and tone to change, so chunks are
// as large as the model handles reliably and end at paragraph boundaries where possible.
// The server generates speech close to (but not much faster than) real-time, so the first
// chunks are smaller and grow, which lets sound start quickly with the next chunk ready
// before this one ends. CHUNK_MAX is capped at the same size as the last ramp step (rather
// than growing further) so no single chunk's generation time gets long enough to depend on
// the lookahead buffer already having a lead, which is what caused long waits between chunks.
const RAMP = [200, 320, 450]
const CHUNK_MAX = 450
const PAUSE_PARAGRAPH_MS = 600 // pause after a chunk that ends a paragraph
const PAUSE_SENTENCE_MS = 200 // pause after a chunk that ends mid-paragraph
const limitFor = (i) => RAMP[i] ?? CHUNK_MAX

let session = null

// ---- session state (kept in storage.session so it survives the worker sleeping) ----

async function loadSession() {
  if (!session) session = (await chrome.storage.session.get(SESSION_KEY))[SESSION_KEY] || null
  return session
}

async function saveSession() {
  await chrome.storage.session.set({ [SESSION_KEY]: session })
}

function publicState() {
  if (!session) return { status: "idle" }
  const { tabId, title, url, mode, status, error, cur, chunkCount, generated, curSentence, sentenceCount, time, duration } = session
  const frac = duration > 0 ? Math.min(1, time / duration) : 0
  return {
    status, error, tabId, title, url, mode, cur, chunkCount, generated, curSentence, sentenceCount,
    progress: chunkCount ? (cur + frac) / chunkCount : 0,
  }
}

async function broadcast() {
  chrome.runtime.sendMessage({ target: "popup", type: "state", state: publicState() }).catch(() => {})
  const s = session
  if (!s || s.status === "idle" || s.status === "done") chrome.action.setBadgeText({ text: "" })
  else if (s.status === "error") {
    chrome.action.setBadgeBackgroundColor({ color: "#dc2626" })
    chrome.action.setBadgeText({ text: "!" })
  } else {
    chrome.action.setBadgeBackgroundColor({ color: "#0ea5e9" })
    chrome.action.setBadgeText({ text: s.status === "paused" ? "II" : "▶" })
  }
}

// ---- chunking ----

// Groups consecutive sentences into chunks. Each sentence keeps the slice of its chunk it
// occupies (start/end as a fraction of the chunk's text), which is used to estimate which
// sentence is being spoken at a given moment.
function buildChunks(sentences) {
  const blockLen = {}
  for (const s of sentences) blockLen[s.block] = (blockLen[s.block] || 0) + s.text.length + 1

  const chunks = []
  let c = null
  sentences.forEach((s, k) => {
    const paraStart = k === 0 || sentences[k - 1].block !== s.block
    const limit = limitFor(chunks.length)
    if (c) {
      const doesNotFit = c.text.length + s.text.length + 1 > limit
      const paragraphDoesNotFit = paraStart && c.text.length + blockLen[s.block] > limit && c.text.length >= 0.4 * limit
      if (paragraphDoesNotFit || doesNotFit) {
        chunks.push(c)
        c = null
      }
    }
    if (!c) c = { text: "", sentences: [], pauseMs: PAUSE_SENTENCE_MS }
    c.sentences.push({ id: s.id, block: s.block, weight: s.text.length + (c.text ? 1 : 0) })
    c.text += (c.text ? " " : "") + s.text
    const paraEnd = k === sentences.length - 1 || sentences[k + 1].block !== s.block
    c.pauseMs = paraEnd ? PAUSE_PARAGRAPH_MS : PAUSE_SENTENCE_MS
  })
  if (c) chunks.push(c)
  if (chunks.length) chunks[chunks.length - 1].pauseMs = 0 // nothing follows the last chunk
  for (const ch of chunks) {
    const total = ch.sentences.reduce((n, x) => n + x.weight, 0)
    let acc = 0
    for (const x of ch.sentences) {
      x.start = acc / total
      acc += x.weight
      x.end = acc / total
    }
  }
  return chunks
}

// ---- offscreen player ----

async function ensureOffscreen() {
  const existing = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] })
  if (existing.length) return
  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ["AUDIO_PLAYBACK"],
    justification: "Play the narration of the page being read aloud.",
  })
}

async function hasOffscreen() {
  return (await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] })).length > 0
}

// Chrome closes the hidden player page after 30 seconds without audible sound (for
// example a long pause), and everything it held is lost. If that happened, mark the
// session paused at the saved position so pressing Play can rebuild the player.
async function reconcile() {
  const s = session
  if (!s || !s.texts || !["playing", "buffering", "paused"].includes(s.status)) return
  if (await hasOffscreen()) return
  s.status = "paused"
  s.userPaused = true
  await saveSession()
}

// Recreate the player and continue from chunk `index`, `frac` of the way through it.
async function revive(index, frac) {
  const settings = await getSettings()
  session.seq += 1
  await ensureOffscreen()
  toPlayer({
    type: "load", texts: session.texts, pauses: session.pauses, narrationId: session.narrationId,
    settings, seq: session.seq, startAt: index, frac,
  })
}

const toPlayer = (msg) => chrome.runtime.sendMessage({ target: "offscreen", ...msg }).catch(() => {})

async function closeOffscreen() {
  try {
    await chrome.offscreen.closeDocument()
  } catch {}
}

// ---- tab helpers ----

const toTab = (tabId, msg) => chrome.tabs.sendMessage(tabId, msg).catch(() => {})

async function fail(message) {
  toPlayer({ type: "stop" })
  await closeOffscreen()
  if (session && session.tabId) await toTab(session.tabId, { type: "mlxa-clear" })
  session = { ...(session || {}), status: "error", error: message }
  await saveSession()
  await broadcast()
}

// ---- commands ----

async function start(tabId) {
  await loadSession()
  if (session && session.tabId && session.tabId !== tabId) await toTab(session.tabId, { type: "mlxa-clear" })
  await closeOffscreen()
  session = { tabId, status: "loading", cur: 0, chunkCount: 0, generated: 0, time: 0, duration: 0 }
  await broadcast()

  let result
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["vendor/Readability.js", "content.js"] })
    ;[{ result }] = await chrome.scripting.executeScript({ target: { tabId }, func: () => window.__mlxa.extract() })
  } catch (e) {
    return fail("This page can't be read (Chrome blocks extensions on it).")
  }
  if (!result || !result.ok) return fail((result && result.error) || "No readable text found on this page.")

  const chunks = buildChunks(result.sentences)
  const sentenceInfo = []
  chunks.forEach((c, ci) => c.sentences.forEach((x) => (sentenceInfo[x.id] = { chunk: ci, start: x.start, end: x.end, block: x.block })))

  const settings = await getSettings()
  session = {
    tabId, title: result.title, url: result.url, mode: result.mode,
    status: "loading", error: null,
    texts: chunks.map((c) => c.text),
    pauses: chunks.map((c) => c.pauseMs),
    narrationId: crypto.randomUUID(),
    chunks: chunks.map((c) => ({ sentences: c.sentences.map((x) => ({ id: x.id, start: x.start, end: x.end })) })),
    sentenceInfo, sentenceCount: result.sentences.length, chunkCount: chunks.length,
    cur: 0, curSentence: -1, generated: 0, time: 0, duration: 0, userPaused: false, seq: 0,
  }
  await saveSession()
  await broadcast()

  await ensureOffscreen()
  toPlayer({ type: "load", texts: session.texts, pauses: session.pauses, narrationId: session.narrationId, settings, seq: 0 })
}

async function stop() {
  await loadSession()
  if (session && session.tabId) await toTab(session.tabId, { type: "mlxa-clear" })
  toPlayer({ type: "stop" })
  await closeOffscreen()
  session = null
  await chrome.storage.session.remove(SESSION_KEY)
  await broadcast()
}

async function togglePause() {
  await loadSession()
  if (!session || !session.chunks) return
  await reconcile()
  if (session.status === "paused") {
    session.userPaused = false
    session.status = "playing"
    if (await hasOffscreen()) toPlayer({ type: "resume" })
    else await revive(session.cur, session.duration > 0 ? session.time / session.duration : 0)
  } else if (session.status === "playing" || session.status === "buffering" || session.status === "loading") {
    session.userPaused = true
    session.status = "paused"
    toPlayer({ type: "pause" })
  }
  await saveSession()
  await broadcast()
}

// Skip to the next/previous paragraph (dir = +1 / -1).
async function skip(dir) {
  await loadSession()
  if (!session || !session.sentenceInfo || session.curSentence < 0) return
  const info = session.sentenceInfo
  const curBlock = info[session.curSentence].block
  const firstOf = (block) => info.findIndex((x) => x.block === block)
  let target
  if (dir > 0) {
    target = info.findIndex((x) => x.block > curBlock)
    if (target === -1) return stop()
  } else {
    const start = firstOf(curBlock)
    if (session.curSentence > start) target = start
    else {
      const prev = curBlock > 0 ? info[start - 1]?.block : -1
      target = prev >= 0 ? firstOf(prev) : 0
    }
  }
  const t = info[target]
  session.userPaused = false
  if (session.status === "paused") session.status = "playing"
  if (await hasOffscreen()) {
    session.seq += 1 // progress reports from before the seek are now stale
    await saveSession()
    toPlayer({ type: "seek", index: t.chunk, frac: t.start, seq: session.seq })
  } else {
    await revive(t.chunk, t.start)
  }
  await highlight(target)
}

async function highlight(id) {
  if (session.curSentence === id) return
  session.curSentence = id
  await toTab(session.tabId, { type: "mlxa-highlight", id })
}

// ---- progress from the player ----

async function onProgress(msg) {
  await loadSession()
  if (!session || !session.chunks || session.status === "done" || session.status === "error") return
  if (msg.seq !== session.seq) return // from before the latest skip
  session.cur = msg.chunk
  session.time = msg.time
  session.duration = msg.duration
  session.generated = msg.generated
  if (session.userPaused) session.status = "paused"
  else if (msg.buffering) session.status = msg.generated === 0 ? "loading" : "buffering"
  else session.status = "playing"

  const chunk = session.chunks[msg.chunk]
  if (chunk && !msg.buffering && msg.duration > 0) {
    // the server appends a fixed pause of silence; sentence timing only covers the speech
    const speechSeconds = Math.max(0.1, msg.duration - (session.pauses?.[msg.chunk] || 0) / 1000)
    const f = Math.min(0.9999, msg.time / speechSeconds)
    const s = chunk.sentences.find((x) => f >= x.start && f < x.end) || chunk.sentences[chunk.sentences.length - 1]
    await highlight(s.id)
  }
  await saveSession()
  await broadcast()
}

// ---- wiring ----

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.target !== "background") return
  ;(async () => {
    switch (msg.type) {
      case "start": await start(msg.tabId); break
      case "togglePause": await togglePause(); break
      case "stop": await stop(); break
      case "skip": await skip(msg.dir); break
      case "progress": await onProgress(msg); break
      case "done":
        await loadSession()
        if (session && session.tabId) await toTab(session.tabId, { type: "mlxa-clear" })
        await closeOffscreen()
        if (session) session.status = "done"
        await saveSession()
        await broadcast()
        break
      case "error": await fail(msg.message); break
      case "getState": await loadSession(); await reconcile(); break
    }
    sendResponse(publicState())
  })()
  return true // async response
})

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "mlxa-read",
    title: "Read aloud with MLX-Audio",
    contexts: ["selection", "page"],
  })
})

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "mlxa-read" && tab && tab.id != null) start(tab.id)
})

// Stop when the narrated tab is closed or navigates somewhere else.
chrome.tabs.onRemoved.addListener(async (tabId) => {
  await loadSession()
  if (session && session.tabId === tabId) stop()
})
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo) => {
  if (changeInfo.status !== "loading" || !changeInfo.url) return
  await loadSession()
  if (session && session.tabId === tabId && session.url && changeInfo.url.split("#")[0] !== session.url.split("#")[0]) stop()
})
