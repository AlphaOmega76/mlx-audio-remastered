// Splits long text into the chunks that are sent to the speech model one at a time.
//
// Every chunk is a separate generation, so each boundary is a chance for the delivery
// (pace, tone, volume) to change. To keep that to a minimum:
//   * chunks are as large as the model handles reliably (CHUNK_MAX characters),
//   * the first chunks are smaller and grow (CHUNK_RAMP) so the first sound starts
//     quickly, since the server generates speech at roughly real-time speed,
//   * chunks end at paragraph boundaries where possible, where a change in delivery
//     is natural, and are followed by a longer pause than chunks that end mid-paragraph.

// `first` and `last` are the numbers (in `splitSentences` order) of the first and last sentence the
// chunk speaks, so a viewer can show which sentence is being read.
export type Chunk = { text: string; pauseMs: number; first: number; last: number }

export const CHUNK_RAMP = [220, 350, 500]
export const CHUNK_MAX = 650
export const PAUSE_PARAGRAPH_MS = 600
export const PAUSE_SENTENCE_MS = 200

export type Sentence = { text: string; paraStart: boolean; paraEnd: boolean; paraLen: number }

const limitFor = (index: number) => CHUNK_RAMP[index] ?? CHUNK_MAX

// Paragraphs are separated by blank lines. Single newlines (e.g. line wraps in a PDF)
// count as spaces, and words hyphenated across a line break are rejoined.
export function toSentences(raw: string): Sentence[] {
  const out: Sentence[] = []
  const paragraphs = raw
    .replace(/\r/g, "")
    .replace(/([A-Za-z])-\n(?=[a-z])/g, "$1")
    .split(/\n\s*\n/)

  for (const para of paragraphs) {
    const clean = para.replace(/\s*\n\s*/g, " ").replace(/\s+/g, " ").trim()
    if (!clean) continue
    const raws = (clean.match(/[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g) ?? [clean]).map((x) => x.trim()).filter(Boolean)

    // A single very long sentence is split at word boundaries.
    const pieces: string[] = []
    for (const sentence of raws) {
      if (sentence.length <= CHUNK_MAX) {
        pieces.push(sentence)
        continue
      }
      let piece = ""
      for (const word of sentence.split(" ")) {
        if (piece && piece.length + word.length + 1 > CHUNK_MAX) {
          pieces.push(piece)
          piece = word
        } else {
          piece = piece ? `${piece} ${word}` : word
        }
      }
      if (piece) pieces.push(piece)
    }

    pieces.forEach((text, i) =>
      out.push({ text, paraStart: i === 0, paraEnd: i === pieces.length - 1, paraLen: clean.length }),
    )
  }
  return out
}

/** The sentences of `raw`, in the order the chunks speak them. */
export const splitSentences = (raw: string): string[] => toSentences(raw).map((s) => s.text)

/** `fromSentence` skips the sentences before it (reading from a sentence the user clicked). */
export function splitIntoChunks(raw: string, fromSentence = 0): Chunk[] {
  const chunks: Chunk[] = []
  let cur = ""
  let endsParagraph = false
  let first = 0
  let last = 0

  const flush = () => {
    if (cur) chunks.push({ text: cur, pauseMs: endsParagraph ? PAUSE_PARAGRAPH_MS : PAUSE_SENTENCE_MS, first, last })
    cur = ""
    endsParagraph = false
  }

  const all = toSentences(raw)
  for (let n = Math.max(0, fromSentence); n < all.length; n++) {
    const s = all[n]
    const limit = limitFor(chunks.length)
    if (cur && s.paraStart && cur.length + 1 + s.paraLen > limit && cur.length >= 0.4 * limit) {
      flush() // the next paragraph does not fit: break between paragraphs, not inside one
    } else if (cur && cur.length + 1 + s.text.length > limit) {
      flush()
    }
    if (!cur) first = n
    cur = cur ? `${cur} ${s.text}` : s.text
    last = n
    endsParagraph = s.paraEnd
  }
  flush()

  if (chunks.length) chunks[chunks.length - 1].pauseMs = 0 // nothing follows the last chunk
  return chunks
}

/**
 * Where reading should begin when the user puts the cursor at `pos`: the start of the sentence the
 * cursor is in, so speech never starts in the middle of a word or sentence. Looks back at most 2000
 * characters; a "sentence" that long without punctuation starts exactly at the cursor instead.
 */
export function sentenceStart(text: string, pos: number): number {
  const end = Math.max(0, Math.min(pos, text.length))
  const from = Math.max(0, end - 2000)
  let start = -1
  for (const m of text.slice(from, end).matchAll(/(?:[.!?\u2026]["'\u201d\u2019)\]]*\s+|\n+)/g)) {
    start = from + (m.index ?? 0) + m[0].length
  }
  if (start >= 0) return start
  return from === 0 ? 0 : end
}
