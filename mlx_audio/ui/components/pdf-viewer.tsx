"use client"

// Shows a PDF as its real pages and highlights the sentence that is being read.
//
// The pages are drawn with PDF.js (bundled with the app, nothing is fetched from the internet).
// Only the pages near the screen are drawn, so a book of hundreds of pages stays light. While the
// pages show, the PDF's text positions are read in the background and matched to the spoken
// sentences (utils/pdf-align.ts); clicking a sentence starts reading from there.

import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { alignSentences, type Rect, type TextItem } from "@/utils/pdf-align"

type PdfDoc = import("pdfjs-dist").PDFDocumentProxy

type Props = {
  file: File
  sentences: string[]
  /** Number (in `sentences`) of the sentence being read; -1 for none. */
  active: number
  onSentenceClick: (index: number) => void
  onError?: (message: string) => void
}

const MAX_WIDTH = 900
const DEFAULT_SIZE: [number, number] = [612, 792]

async function loadPdfjs() {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs")
  pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/legacy/build/pdf.worker.min.mjs", import.meta.url).toString()
  return pdfjs
}

export function PdfViewer({ file, sentences, active, onSentenceClick, onError }: Props) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const pageRefs = useRef<(HTMLDivElement | null)[]>([])
  const [doc, setDoc] = useState<PdfDoc | null>(null)
  const [sizes, setSizes] = useState<[number, number][]>([])
  const [items, setItems] = useState<TextItem[][] | null>(null)
  const [progress, setProgress] = useState(0)
  const [width, setWidth] = useState(MAX_WIDTH)
  const [rects, setRects] = useState<Rect[][]>([])

  // Open the file
  useEffect(() => {
    let cancelled = false
    let opened: PdfDoc | null = null
    const url = URL.createObjectURL(file)
    setDoc(null)
    setSizes([])
    setItems(null)
    setProgress(0)
    ;(async () => {
      try {
        const pdfjs = await loadPdfjs()
        opened = await pdfjs.getDocument({ url }).promise
        if (cancelled) return
        setDoc(opened)
      } catch (e) {
        if (!cancelled) onError?.(`Could not show the PDF pages: ${(e as Error).message}`)
      }
    })()
    return () => {
      cancelled = true
      opened?.destroy()
      URL.revokeObjectURL(url)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file])

  // Read every page's size and text positions in the background
  useEffect(() => {
    if (!doc) return
    let cancelled = false
    ;(async () => {
      const allItems: TextItem[][] = []
      const allSizes: [number, number][] = []
      for (let i = 1; i <= doc.numPages; i++) {
        if (cancelled) return
        const page = await doc.getPage(i)
        const vp = page.getViewport({ scale: 1 })
        allSizes.push([vp.width, vp.height])
        const content = await page.getTextContent()
        const pageItems: TextItem[] = []
        for (const it of content.items) {
          if (!("str" in it) || !it.str.trim()) continue
          pageItems.push({
            str: it.str,
            x: it.transform[4],
            y: it.transform[5],
            w: it.width,
            h: it.height || Math.abs(it.transform[3]),
          })
        }
        allItems.push(pageItems)
        page.cleanup()
        if (i % 8 === 0 || i === doc.numPages) {
          setProgress(i)
          setSizes([...allSizes])
          await new Promise((r) => setTimeout(r, 0)) // let the page breathe
        }
      }
      if (!cancelled) setItems(allItems)
    })().catch((e) => !cancelled && onError?.(`Could not read the PDF's text positions: ${(e as Error).message}`))
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc])

  // Match the sentences to places on the pages (once both are ready)
  useEffect(() => {
    if (!items || sentences.length === 0) {
      setRects([])
      return
    }
    const t = setTimeout(() => setRects(alignSentences(sentences, items)), 0)
    return () => clearTimeout(t)
  }, [items, sentences])

  // Page width follows the window
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const update = () => setWidth(Math.max(280, Math.min(MAX_WIDTH, el.clientWidth - 32)))
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Sentences per page, for drawing
  const byPage = useMemo(() => {
    const map = new Map<number, { sentence: number; rect: Rect }[]>()
    rects.forEach((list, sentence) =>
      list.forEach((rect) => {
        const arr = map.get(rect.page) ?? []
        arr.push({ sentence, rect })
        map.set(rect.page, arr)
      }),
    )
    return map
  }, [rects])

  const sizeOf = (i: number) => sizes[i] ?? sizes[0] ?? DEFAULT_SIZE
  const boxFor = (i: number, r: Rect) => {
    const [w0, h0] = sizeOf(i)
    const s = width / w0
    return { left: r.x * s, top: (h0 - r.y - r.h * 0.95) * s, width: Math.max(2, r.w * s), height: r.h * 1.2 * s }
  }

  // Keep the sentence being read in view
  useEffect(() => {
    const first = rects[active]?.[0]
    const box = scrollRef.current
    const pageEl = first ? pageRefs.current[first.page] : null
    if (!first || !box || !pageEl) return
    const top = pageEl.offsetTop + boxFor(first.page, first).top
    const bottom = top + 24
    if (top < box.scrollTop + 40 || bottom > box.scrollTop + box.clientHeight - 80) {
      box.scrollTo({ top: Math.max(0, top - box.clientHeight / 3), behavior: "smooth" })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, rects])

  // Stable functions, so unchanged pages are not redrawn each time the highlight moves
  const setPageRef = useCallback((index: number, el: HTMLDivElement | null) => {
    pageRefs.current[index] = el
  }, [])
  const clickRef = useRef(onSentenceClick)
  clickRef.current = onSentenceClick
  const handleClick = useCallback((index: number) => clickRef.current(index), [])

  const total = doc?.numPages ?? 0
  return (
    <div ref={scrollRef} className="h-full min-h-[300px] overflow-auto rounded-md border border-gray-200 bg-gray-100 p-4 dark:border-gray-700 dark:bg-gray-800" data-testid="pdf-viewer">
      <div className="mb-2 text-center text-xs text-gray-500 dark:text-gray-400" data-testid="pdf-status">
        {!doc
          ? "Opening the PDF…"
          : !items
            ? `Preparing highlights… ${progress}/${total}`
            : rects.some((r) => r.length > 0)
              ? "Click a sentence to read from there."
              : "Highlighting is not available for this PDF; the speech works as usual."}
      </div>
      <div className="flex flex-col items-center gap-4">
        {Array.from({ length: total }, (_, i) => (
          <PdfPage
            key={i}
            doc={doc!}
            index={i}
            width={width}
            size={sizeOf(i)}
            scroller={scrollRef}
            setRef={setPageRef}
            overlays={byPage.get(i) ?? NO_OVERLAYS}
            active={(byPage.get(i) ?? NO_OVERLAYS).some((o) => o.sentence === active) ? active : -1}
            onSentenceClick={handleClick}
          />
        ))}
      </div>
    </div>
  )
}

type Overlay = { sentence: number; rect: Rect }
const NO_OVERLAYS: Overlay[] = []

// One page. Memoised, and the clickable sentence boxes are only made while the page is near the
// screen: a long book has tens of thousands of them.
const PdfPage = memo(function PdfPage({
  doc,
  index,
  width,
  size,
  scroller,
  setRef,
  overlays,
  active,
  onSentenceClick,
}: {
  doc: PdfDoc
  index: number
  width: number
  size: [number, number]
  scroller: React.RefObject<HTMLDivElement | null>
  setRef: (index: number, el: HTMLDivElement | null) => void
  overlays: Overlay[]
  active: number
  onSentenceClick: (index: number) => void
}) {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const [near, setNear] = useState(false)
  const height = (width * size[1]) / size[0]

  // Only pages near the screen are drawn
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => setNear(e.isIntersecting), {
      root: scroller.current,
      rootMargin: "1500px 0px",
    })
    io.observe(el)
    return () => io.disconnect()
  }, [scroller])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    if (!near || !doc) {
      canvas.width = 0 // frees the picture's memory for pages far away
      return
    }
    let cancelled = false
    let task: { cancel: () => void; promise: Promise<unknown> } | null = null
    ;(async () => {
      const page = await doc.getPage(index + 1)
      if (cancelled) return
      const scale = width / page.getViewport({ scale: 1 }).width
      const vp = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) })
      canvas.width = Math.floor(vp.width)
      canvas.height = Math.floor(vp.height)
      const ctx = canvas.getContext("2d")
      if (!ctx) return
      task = page.render({ canvasContext: ctx, viewport: vp })
      await task.promise
      page.cleanup()
    })().catch(() => {}) // a cancelled draw rejects; nothing to do
    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [near, doc, index, width])

  return (
    <div
      ref={(el) => {
        boxRef.current = el
        setRef(index, el)
      }}
      className="relative bg-white shadow"
      style={{ width, height }}
      data-page={index}
    >
      <canvas ref={canvasRef} style={{ width, height }} />
      {near &&
        overlays.map(({ sentence, rect }, n) => {
          const s = width / size[0]
          const on = sentence === active
          return (
            <div
              key={n}
              data-sentence={sentence}
              data-active={on ? "1" : undefined}
              onClick={() => onSentenceClick(sentence)}
              className={`absolute cursor-pointer rounded-sm ${on ? "bg-yellow-300/60" : "hover:bg-sky-300/30"}`}
              style={{
                left: rect.x * s,
                top: (size[1] - rect.y - rect.h * 0.95) * s,
                width: Math.max(2, rect.w * s),
                height: rect.h * 1.2 * s,
              }}
            />
          )
        })}
    </div>
  )
})
