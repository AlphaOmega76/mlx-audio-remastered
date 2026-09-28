// Injected into the page on demand (after vendor/Readability.js).
//
// extract()   finds the text to read (the selection, else the main article) and
//             splits it into sentences.
// highlight() marks one of those sentences on the page while it is spoken, using
//             the CSS Custom Highlight API so the page's own DOM is never changed.
;(() => {
  if (window.__mlxa && window.__mlxa.dispose) window.__mlxa.dispose()

  const HL_NAME = "mlxa-current"
  const MAX_SENTENCE = 700 // longer sentences are split at word boundaries
  const PIECE = 450

  let store = [] // store[id] = { run, start, end }: where a sentence lives on the page
  let styleEl = null

  const SKIP_TAGS = new Set([
    "SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "CANVAS", "VIDEO", "AUDIO", "IFRAME",
    "OBJECT", "EMBED", "SELECT", "TEXTAREA", "INPUT", "BUTTON", "HEAD", "MATH",
  ])
  const SKIP_SELECTOR = ".mw-editsection, .reference, .noprint, .sr-only, .visually-hidden, .screen-reader-text"
  const CHROME_SELECTOR =
    "nav, header, footer, aside, form, [role=navigation], [role=banner], [role=contentinfo], [role=complementary], [role=search], [role=dialog]"

  function shouldSkip(el, strict) {
    if (SKIP_TAGS.has(el.tagName.toUpperCase())) return true
    if (el.getAttribute("aria-hidden") === "true" || el.hidden) return true
    const cs = getComputedStyle(el)
    if (cs.display === "none" || cs.visibility === "hidden") return true
    if (el.tagName === "SUP" && /^\[?\w{1,3}\]?$/.test(el.textContent.trim())) return true
    if (el.matches(SKIP_SELECTOR)) return true
    if (strict && el.matches(CHROME_SELECTOR)) return true
    return false
  }

  const isBlock = (cs) => !cs.display.startsWith("inline") && cs.display !== "contents"

  // Walks the DOM in reading order and groups text into "runs": one run per visual
  // block (paragraph, heading, list item, ...). opts: { strict, allow, range }
  function collectRuns(roots, opts) {
    const runs = []
    let run = null
    const flush = () => {
      if (run && run.text.trim()) runs.push(run)
      run = null
    }
    const walk = (node) => {
      if (node.nodeType === 3) {
        let from = 0
        let to = node.nodeValue.length
        if (opts.range) {
          if (!opts.range.intersectsNode(node)) return
          if (node === opts.range.startContainer) from = opts.range.startOffset
          if (node === opts.range.endContainer) to = opts.range.endOffset
        }
        if (to <= from) return
        if (!run) run = { nodes: [], text: "" }
        run.nodes.push({ node, start: run.text.length, from, to })
        run.text += node.nodeValue.slice(from, to)
        return
      }
      if (node.nodeType !== 1) return
      if (opts.allow && !opts.allow.has(node)) return
      if (opts.range && !opts.range.intersectsNode(node)) return
      if (shouldSkip(node, opts.strict)) return
      if (node.tagName === "BR") {
        flush()
        return
      }
      const block = isBlock(getComputedStyle(node))
      if (block) flush()
      for (let c = node.firstChild; c; c = c.nextSibling) walk(c)
      if (block) flush()
    }
    roots.forEach(walk)
    flush()
    return runs
  }

  // Text as it will be spoken: no citations, no URLs, and it always ends in
  // punctuation so the voice pauses between headings and paragraphs.
  function toSpeech(raw) {
    let t = raw.replace(/\s+/g, " ").trim()
    t = t.replace(/\[(?:\d+|[a-z]|citation needed|edit)\]/gi, "")
    t = t.replace(/\b(?:https?:\/\/|www\.)\S+/gi, "")
    t = t.replace(/\s+/g, " ").trim()
    if (!/[\p{L}\p{N}]/u.test(t)) return ""
    if (!/[.!?…]["'”’)\]]*$/.test(t)) t += "."
    return t
  }

  // Sentence spans [start, end) within a run's raw text.
  function splitSentences(text) {
    const spans = []
    const re = /.*?(?:[.!?…]+["'”’)\]]*(?=\s|$)|$)\s*/gs
    for (const m of text.matchAll(re)) {
      if (!m[0]) continue
      let start = m.index
      let end = m.index + m[0].length
      while (start < end && /\s/.test(text[start])) start++
      while (end > start && /\s/.test(text[end - 1])) end--
      if (end <= start) continue
      if (end - start <= MAX_SENTENCE) {
        spans.push({ start, end })
        continue
      }
      // A very long sentence: break it at word boundaries.
      let pieceStart = start
      let lastEnd = start
      for (const w of text.slice(start, end).matchAll(/\S+/g)) {
        const wStart = start + w.index
        const wEnd = wStart + w[0].length
        if (wEnd - pieceStart > PIECE && lastEnd > pieceStart) {
          spans.push({ start: pieceStart, end: lastEnd })
          pieceStart = wStart
        }
        lastEnd = wEnd
      }
      if (lastEnd > pieceStart) spans.push({ start: pieceStart, end: lastEnd })
    }
    return spans
  }

  // Uses Mozilla Readability to decide which parts of the page are the article.
  // Readability works on a clone, so clone elements are tagged with their index and
  // mapped back to the live page (the clone and the page have identical structure).
  function articleRuns() {
    try {
      const liveEls = document.querySelectorAll("*")
      const clone = document.cloneNode(true)
      const cloneEls = clone.querySelectorAll("*")
      if (cloneEls.length !== liveEls.length) return null
      cloneEls.forEach((el, i) => el.setAttribute("data-mlxa-i", String(i)))
      const article = new Readability(clone, { serializer: (el) => el, charThreshold: 200 }).parse()
      if (!article || !article.content) return null
      const allow = new Set()
      article.content.querySelectorAll("[data-mlxa-i]").forEach((el) => {
        allow.add(liveEls[Number(el.getAttribute("data-mlxa-i"))])
      })
      if (allow.size === 0) return null
      const roots = [...allow].filter((el) => !allow.has(el.parentElement))
      return { runs: collectRuns(roots, { strict: false, allow }), title: article.title }
    } catch (e) {
      return null
    }
  }

  // Readability removes a headline that repeats the page title. A listener still wants
  // to hear it, so put the page's own <h1> back at the start if it is missing.
  function withHeadline(runs) {
    const h1 = document.querySelector("article h1, main h1, [role=main] h1")
    if (!h1) return runs
    const text = h1.textContent.replace(/\s+/g, " ").trim()
    if (text.length < 3 || text.length > 200) return runs
    if (runs.some((r) => r.text.replace(/\s+/g, " ").trim() === text)) return runs
    const headline = collectRuns([h1], { strict: false })
    return headline.length ? [...headline, ...runs] : runs
  }

  const totalChars = (runs) => runs.reduce((n, r) => n + r.text.trim().length, 0)

  function extract() {
    clearHighlight()
    store = []
    let mode = ""
    let runs = []
    let title = document.title

    const sel = window.getSelection()
    if (sel && !sel.isCollapsed && sel.toString().trim()) {
      const range = sel.getRangeAt(0)
      const root = range.commonAncestorContainer.nodeType === 1 ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement
      runs = collectRuns([root], { strict: false, range })
      mode = "selection"
    }
    if (!runs.length) {
      const art = articleRuns()
      if (art && totalChars(art.runs) >= 200) {
        runs = withHeadline(art.runs)
        mode = "article"
        if (art.title) title = art.title
      }
    }
    if (!runs.length) {
      const root = document.querySelector("main, article, [role=main]") || document.body
      runs = collectRuns([root], { strict: true })
      mode = "page"
    }

    const sentences = []
    runs.forEach((run, block) => {
      for (const span of splitSentences(run.text)) {
        const text = toSpeech(run.text.slice(span.start, span.end))
        if (!text) continue
        store.push({ run, start: span.start, end: span.end })
        sentences.push({ id: sentences.length, block, text })
      }
    })

    if (!sentences.length) return { ok: false, error: "No readable text found on this page." }
    return { ok: true, mode, title, url: location.href, sentences }
  }

  // ---- highlighting -------------------------------------------------------

  function locate(run, offset, isEnd) {
    for (const e of run.nodes) {
      const len = e.to - e.from
      const inside = isEnd ? offset <= e.start + len : offset < e.start + len
      if (inside) return [e.node, e.from + Math.max(0, offset - e.start)]
    }
    const last = run.nodes[run.nodes.length - 1]
    return [last.node, last.to]
  }

  function ensureStyle() {
    if (styleEl && styleEl.isConnected) return
    styleEl = document.createElement("style")
    styleEl.textContent = `::highlight(${HL_NAME}) { background-color: rgba(250, 204, 21, 0.6); color: inherit; }`
    document.documentElement.appendChild(styleEl)
  }

  function highlight(id) {
    const s = store[id]
    if (!s || !window.CSS || !CSS.highlights) return
    try {
      const range = document.createRange()
      const [sn, so] = locate(s.run, s.start, false)
      const [en, eo] = locate(s.run, s.end, true)
      range.setStart(sn, so)
      range.setEnd(en, eo)
      ensureStyle()
      CSS.highlights.set(HL_NAME, new Highlight(range))
      const r = range.getBoundingClientRect()
      if (r.height && (r.top < 80 || r.bottom > window.innerHeight - 80)) {
        window.scrollBy({ top: r.top + r.height / 2 - window.innerHeight / 2, behavior: "smooth" })
      }
    } catch (e) {
      // The page changed under us; skip this highlight.
    }
  }

  function clearHighlight() {
    if (window.CSS && CSS.highlights) CSS.highlights.delete(HL_NAME)
  }

  const onMessage = (msg) => {
    if (!msg) return
    if (msg.type === "mlxa-highlight") highlight(msg.id)
    else if (msg.type === "mlxa-clear") clearHighlight()
  }
  chrome.runtime.onMessage.addListener(onMessage)

  window.__mlxa = {
    extract,
    highlight,
    clear: clearHighlight,
    dispose() {
      chrome.runtime.onMessage.removeListener(onMessage)
      clearHighlight()
      if (styleEl) styleEl.remove()
    },
  }
})()
