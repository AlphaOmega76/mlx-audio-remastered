// Finds where each spoken sentence sits on the PDF's pages, so the viewer can highlight it.
//
// The speech uses the server's cleaned text (paragraphs rebuilt, running headers and page numbers
// dropped, text drawn twice read once), while the pages are drawn from the PDF itself. The two
// differ in layout but not in words, so sentences are matched by their letters and digits only,
// in reading order. Sentences that cannot be found get no rectangles (reading carries on without a
// highlight for them).

/** A piece of text on a page, in the PDF's own units (origin bottom-left). */
export type TextItem = { str: string; x: number; y: number; w: number; h: number }
/** A rectangle on one page (page index from 0), in the PDF's own units. */
export type Rect = { page: number; x: number; y: number; w: number; h: number }

const keep = /[\p{L}\p{N}]/u

/** Lower-case letters and digits only (ligatures such as "fi" are expanded). */
export function normalize(text: string): string {
  let out = ""
  for (const ch of text.normalize("NFKC").toLowerCase()) if (keep.test(ch)) out += ch
  return out
}

type Piece = { page: number; item: TextItem; start: number; count: number }

export function alignSentences(sentences: string[], pages: TextItem[][]): Rect[][] {
  // One long string of the pages' letters, remembering which item each stretch came from.
  const pieces: Piece[] = []
  const parts: string[] = []
  let length = 0
  pages.forEach((items, page) => {
    const seen = new Set<string>() // some PDFs draw every line twice in the same place: use it once
    for (const item of items) {
      const key = `${item.str}|${Math.round(item.x)}|${Math.round(item.y)}`
      if (seen.has(key)) continue
      seen.add(key)
      const n = normalize(item.str)
      if (!n) continue
      pieces.push({ page, item, start: length, count: n.length })
      parts.push(n)
      length += n.length
    }
  })
  const stream = parts.join("")

  // The rectangles for stream[a, b): the covered part of each item it touches.
  const rectsFor = (a: number, b: number): Rect[] => {
    let lo = 0
    let hi = pieces.length - 1
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (pieces[mid].start + pieces[mid].count <= a) lo = mid + 1
      else hi = mid
    }
    const out: Rect[] = []
    for (let i = lo; i < pieces.length && pieces[i].start < b; i++) {
      const { page, item, start, count } = pieces[i]
      const from = Math.max(a, start) - start
      const to = Math.min(b, start + count) - start
      if (to <= from) continue
      out.push({ page, x: item.x + (item.w * from) / count, y: item.y, w: (item.w * (to - from)) / count, h: item.h })
    }
    return out
  }

  const MAX_GAP = 4000 // how far past the last match the next sentence may start
  let pos = 0
  return sentences.map((sentence) => {
    const n = normalize(sentence)
    if (!n) return []
    let range: [number, number] | null = null

    const exact = stream.indexOf(n, pos)
    if (exact >= 0 && (exact - pos <= MAX_GAP || n.length >= 60)) range = [exact, exact + n.length]

    if (!range && n.length >= 24) {
      // The cleaned text can differ from the page in a few characters (a hyphen, a stray mark):
      // match the sentence's beginning and its end instead.
      const k = Math.min(14, n.length >> 1)
      const a = stream.indexOf(n.slice(0, k), pos)
      const b = a >= 0 ? stream.indexOf(n.slice(-k), a) : -1
      if (a >= 0 && b >= 0 && b + k - a <= n.length * 2 + 100 && (a - pos <= MAX_GAP || n.length >= 60)) {
        range = [a, b + k]
      }
    }

    if (!range && n.length >= 40) {
      // Last resort for text that came out of order (columns): look from the start, without moving on.
      const back = stream.indexOf(n)
      return back >= 0 ? rectsFor(back, back + n.length) : []
    }
    if (!range) return []
    pos = range[1]
    return rectsFor(range[0], range[1])
  })
}
