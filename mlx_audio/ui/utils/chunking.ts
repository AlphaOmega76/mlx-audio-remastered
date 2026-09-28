// Splits long text into the chunks that are sent to the speech model one at a time.
//
// Every chunk is a separate generation, so each boundary is a chance for the delivery
// (pace, tone, volume) to change. To keep that to a minimum:
//   * chunks are as large as the model handles reliably (CHUNK_MAX characters),
//   * the first chunks are smaller and grow (CHUNK_RAMP) so the first sound starts
//     quickly, since the server generates speech at roughly real-time speed,
//   * chunks end at paragraph boundaries where possible, where a change in delivery
//     is natural, and are followed by a longer pause than chunks that end mid-paragraph.

export type Chunk = { text: string; pauseMs: number }

export const CHUNK_RAMP = [220, 350, 500]
export const CHUNK_MAX = 650
export const PAUSE_PARAGRAPH_MS = 600
export const PAUSE_SENTENCE_MS = 200

type Sentence = { text: string; paraStart: boolean; paraEnd: boolean; paraLen: number }

const limitFor = (index: number) => CHUNK_RAMP[index] ?? CHUNK_MAX

// Paragraphs are separated by blank lines. Single newlines (e.g. line wraps in a PDF)
// count as spaces, and words hyphenated across a line break are rejoined.
function toSentences(raw: string): Sentence[] {
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

export function splitIntoChunks(raw: string): Chunk[] {
  const chunks: Chunk[] = []
  let cur = ""
  let endsParagraph = false

  const flush = () => {
    if (cur) chunks.push({ text: cur, pauseMs: endsParagraph ? PAUSE_PARAGRAPH_MS : PAUSE_SENTENCE_MS })
    cur = ""
    endsParagraph = false
  }

  for (const s of toSentences(raw)) {
    const limit = limitFor(chunks.length)
    if (cur && s.paraStart && cur.length + 1 + s.paraLen > limit && cur.length >= 0.4 * limit) {
      flush() // the next paragraph does not fit: break between paragraphs, not inside one
    } else if (cur && cur.length + 1 + s.text.length > limit) {
      flush()
    }
    cur = cur ? `${cur} ${s.text}` : s.text
    endsParagraph = s.paraEnd
  }
  flush()

  if (chunks.length) chunks[chunks.length - 1].pauseMs = 0 // nothing follows the last chunk
  return chunks
}
