// Turns the raw text the server pulls out of a PDF into pages of paragraphs.
//
// PDF text comes out with a hard line break at the end of every visual line, no paragraph
// markers and often a page number in the middle of nowhere. This rebuilds paragraphs with a few
// simple rules (it cannot be perfect; a PDF has no real paragraphs):
//   * a blank line is a paragraph break
//   * a line that ends a sentence and is clearly shorter than the page's full lines ends its
//     paragraph (the last line of a paragraph is short)
//   * a short line without end punctuation, followed by a capitalised line, is a heading
//   * a word split by a hyphen at the end of a line is joined back together
//   * lines that are only a page number ("12", "Page 3 of 40") are dropped
//   * a running header or footer (the same line, apart from its numbers, at the top or bottom of
//     most pages) is dropped
//   * ligatures such as "ﬁ" are turned into plain letters, which the voice would stumble on

const SENTENCE_END = /[.!?:;…]["'”’)\]]*$/
const PAGE_NUMBER = /^(?:page\s+)?\d{1,4}(?:\s*(?:of|\/)\s*\d{1,4})?$/i

function percentile(values, p) {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))]
}

function join(prev, next) {
  if (/[A-Za-z]-$/.test(prev) && /^[a-z]/.test(next)) return prev.slice(0, -1) + next
  return prev + " " + next
}

const EDGE = 2 // lines at the top and bottom of a page that may be a running header or footer

const cleanLines = (text) =>
  String(text || "")
    .normalize("NFKC")
    .split(/\r?\n/)
    .map((l) => l.replace(/\s+/g, " ").trim())

// A line with its digits blanked, so "Report 2/6" and "Report 3/6" count as the same line.
const shape = (line) => line.replace(/\d+/g, "#")

// Lines to drop: ones that, ignoring digits, open or close at least half of the pages (3 or more).
function runningLines(pageTexts) {
  if (pageTexts.length < 3) return new Set()
  const counts = new Map()
  for (const text of pageTexts) {
    const lines = cleanLines(text).filter(Boolean)
    const edge = new Set([...lines.slice(0, EDGE), ...lines.slice(-EDGE)].map(shape))
    for (const e of edge) counts.set(e, (counts.get(e) || 0) + 1)
  }
  const need = Math.max(2, Math.ceil(pageTexts.length / 2))
  const out = new Set()
  for (const [line, n] of counts) if (n >= need && /[\p{L}]/u.test(line)) out.add(line)
  return out
}

// One page's text -> an array of paragraph strings. `drop` = running header/footer shapes to skip.
export function paragraphsOfPage(text, drop = new Set()) {
  let lines = cleanLines(text)
  if (drop.size) {
    // only the lines at the page's edges are candidates
    const idx = lines.map((l, i) => (l ? i : -1)).filter((i) => i >= 0)
    const edgeIdx = new Set([...idx.slice(0, EDGE), ...idx.slice(-EDGE)])
    lines = lines.map((l, i) => (edgeIdx.has(i) && drop.has(shape(l)) ? "" : l))
  }
  const full = percentile(lines.filter(Boolean).map((l) => l.length), 0.9)

  const out = []
  let cur = ""
  let lastLen = 0
  const flush = () => {
    if (cur) out.push(cur)
    cur = ""
    lastLen = 0
  }
  for (const line of lines) {
    if (!line) {
      flush()
      continue
    }
    if (PAGE_NUMBER.test(line)) continue
    if (cur) {
      const shortLine = lastLen < 0.75 * full
      const endsSentence = SENTENCE_END.test(cur)
      const heading = lastLen < 0.5 * full && lastLen < 70 && !endsSentence && /^[A-Z0-9]/.test(line)
      if ((endsSentence && shortLine) || heading) flush()
    }
    cur = cur ? join(cur, line) : line
    lastLen = line.length
  }
  flush()
  return out
}

// All pages -> [{ page: 1-based page number, paragraphs: [...] }], skipping pages with no text.
export function buildPages(pageTexts) {
  const pages = []
  const drop = runningLines(pageTexts)
  pageTexts.forEach((text, i) => {
    const paragraphs = paragraphsOfPage(text, drop)
    if (paragraphs.length) pages.push({ page: i + 1, paragraphs })
  })
  return pages
}
