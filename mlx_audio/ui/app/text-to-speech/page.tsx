"use client"

import type React from "react"

import { useState, useRef, useEffect } from "react"
import { ChevronDown, ChevronLeft, ChevronRight, Download, Play, Pause, RefreshCw, Square, Upload } from "lucide-react"
import { LayoutWrapper } from "@/components/layout-wrapper"
import { getApiUrl } from "@/utils/api"
import { splitIntoChunks } from "@/utils/chunking"
import { VoiceSelection } from "@/components/voice-selection"

// Custom range input component with colored progress
function RangeInput({
  min,
  max,
  step,
  value,
  onChange,
  className = "",
  ariaLabel,
}: {
  min: number
  max: number
  step: number
  value: number
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  className?: string
  ariaLabel?: string
}) {
  const percentage = ((value - Number(min)) / (Number(max) - Number(min))) * 100

  return (
    <div className={`relative flex-1 ${className}`}>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={onChange}
        className="w-full appearance-none bg-transparent cursor-pointer"
        aria-label={ariaLabel}
        style={{
          background: `linear-gradient(to right, #0ea5e9 0%, #0ea5e9 ${percentage}%, #e5e7eb ${percentage}%, #e5e7eb 100%)`,
          height: "2px",
          borderRadius: "2px",
        }}
      />
    </div>
  )
}

type AudioChunk = { blob: Blob; url: string; duration: number }

const formatTime = (seconds: number) => {
  const total = Math.max(0, Math.floor(seconds || 0))
  const m = Math.floor(total / 60)
  const sec = total % 60
  return `${m.toString().padStart(2, "0")}:${sec.toString().padStart(2, "0")}`
}

const getBlobDuration = (url: string) =>
  new Promise<number>((resolve) => {
    const a = new Audio()
    a.preload = "metadata"
    a.onloadedmetadata = () => resolve(Number.isFinite(a.duration) ? a.duration : 0)
    a.onerror = () => resolve(0)
    a.src = url
  })

// Decode every chunk and join them into a single 16-bit PCM WAV file.
const mergeToWav = async (blobs: Blob[]): Promise<Blob> => {
  const ctx = new AudioContext()
  const parts: Int16Array<ArrayBuffer>[] = []
  let sampleRate = ctx.sampleRate
  let channels = 1
  try {
    for (let i = 0; i < blobs.length; i++) {
      const buf = await ctx.decodeAudioData(await blobs[i].arrayBuffer())
      if (i === 0) {
        sampleRate = buf.sampleRate
        channels = buf.numberOfChannels
      }
      const length = buf.length
      const out = new Int16Array(length * channels)
      for (let ch = 0; ch < channels; ch++) {
        const data = buf.getChannelData(Math.min(ch, buf.numberOfChannels - 1))
        for (let j = 0; j < length; j++) {
          const v = Math.max(-1, Math.min(1, data[j]))
          out[j * channels + ch] = v < 0 ? v * 0x8000 : v * 0x7fff
        }
      }
      parts.push(out)
    }
  } finally {
    await ctx.close()
  }

  const dataBytes = parts.reduce((n, p) => n + p.byteLength, 0)
  const header = new ArrayBuffer(44)
  const dv = new DataView(header)
  const writeStr = (off: number, str: string) => {
    for (let i = 0; i < str.length; i++) dv.setUint8(off + i, str.charCodeAt(i))
  }
  writeStr(0, "RIFF")
  dv.setUint32(4, 36 + dataBytes, true)
  writeStr(8, "WAVE")
  writeStr(12, "fmt ")
  dv.setUint32(16, 16, true)
  dv.setUint16(20, 1, true)
  dv.setUint16(22, channels, true)
  dv.setUint32(24, sampleRate, true)
  dv.setUint32(28, sampleRate * channels * 2, true)
  dv.setUint16(32, channels * 2, true)
  dv.setUint16(34, 16, true)
  writeStr(36, "data")
  dv.setUint32(40, dataBytes, true)
  return new Blob([header, ...parts], { type: "audio/wav" })
}

export default function SpeechSynthesis() {
  const [text, setText] = useState("")
  const [isPlaying, setIsPlaying] = useState(false)
  const [isGenerating, setIsGenerating] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [currentTime, setCurrentTime] = useState("00:00")
  const [duration, setDuration] = useState("00:00")
  const [baseModel, setBaseModel] = useState("mlx-community/Kokoro-82M-bf16")
  const [quantization, setQuantization] = useState("6bit")
  const [selectedVoice, setSelectedVoice] = useState("ryan")
  const [instruction, setInstruction] = useState("calm, measured narrator tone")

  const [settingsOpen, setSettingsOpen] = useState(true)
  const [isDragging, setIsDragging] = useState(false)
  const [isExtracting, setIsExtracting] = useState(false)
  const [pdfName, setPdfName] = useState<string | null>(null)
  const [message, setMessage] = useState<{ type: "error" | "info"; text: string } | null>(null)
  const [genProgress, setGenProgress] = useState({ done: 0, total: 0 })
  const [progress, setProgress] = useState(0)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  // Chunked playback state (refs so the audio event handlers never go stale)
  const chunksRef = useRef<AudioChunk[]>([])
  const currentIdxRef = useRef(0)
  const generatingRef = useRef(false)
  const waitingRef = useRef(false) // playback caught up with generation
  const wantPlayRef = useRef(false) // user intends audio to be playing
  const abortRef = useRef<AbortController | null>(null)

  const totalDuration = () => chunksRef.current.reduce((n, c) => n + c.duration, 0)
  const elapsedBefore = (idx: number) =>
    chunksRef.current.slice(0, idx).reduce((n, c) => n + c.duration, 0)

  const updateTimeline = () => {
    const audio = audioRef.current
    const total = totalDuration()
    const elapsed = elapsedBefore(currentIdxRef.current) + (audio?.currentTime || 0)
    setCurrentTime(formatTime(elapsed))
    setDuration(formatTime(total))
    setProgress(total > 0 ? Math.min(1, elapsed / total) : 0)
  }

  const loadChunk = (idx: number) => {
    const audio = audioRef.current
    const chunk = chunksRef.current[idx]
    if (!audio || !chunk) return false
    currentIdxRef.current = idx
    audio.src = chunk.url
    return true
  }

  const playChunk = (idx: number) => {
    if (!loadChunk(idx)) return
    audioRef.current?.play().catch(() => setIsPlaying(false))
  }

  // Rewind to the start (paused) once everything has played
  const finishPlayback = () => {
    waitingRef.current = false
    wantPlayRef.current = false
    setIsPlaying(false)
    if (chunksRef.current.length > 0) loadChunk(0)
    setCurrentTime("00:00")
    setProgress(0)
  }

  const advanceIfWaiting = () => {
    if (!waitingRef.current || !wantPlayRef.current) return
    const next = currentIdxRef.current + 1
    if (next < chunksRef.current.length) {
      waitingRef.current = false
      playChunk(next)
    }
  }

  const clearChunks = () => {
    chunksRef.current.forEach((c) => URL.revokeObjectURL(c.url))
    chunksRef.current = []
    currentIdxRef.current = 0
  }

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    audio.ontimeupdate = updateTimeline
    audio.onended = () => {
      const next = currentIdxRef.current + 1
      if (next < chunksRef.current.length) {
        playChunk(next)
      } else if (generatingRef.current) {
        waitingRef.current = true // more audio is still being generated
      } else {
        finishPlayback()
      }
    }
    return () => {
      abortRef.current?.abort()
      audio.pause()
      clearChunks()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Helper function to check if the model is a Marvis model
  const isMarvisModel = (modelName: string) => {
    return modelName.toLowerCase().includes("marvis")
  }
  
  // Helper function to check if the model is a Qwen3 model
  const isQwen3Model = (modelName: string) => {
    return modelName.toLowerCase().includes("qwen3")
  }

  const qwen3Voices = ["ryan", "serena", "vivian", "uncle_fu", "aiden", "ono_anna", "sohee", "eric", "dylan"]

  // Helper function to get available quantizations for a model
  const getAvailableQuantizations = (modelName: string) => {
    if (modelName === "Marvis-AI/marvis-tts-100m-v0.2") {
      return ["none", "6bit", "8bit"]
    } else if (modelName === "Marvis-AI/marvis-tts-250m-v0.2") {
      return ["none", "4bit", "6bit", "8bit"]
    } else if (modelName === "Marvis-AI/marvis-tts-250m-v0.1") {
      return ["none", "4bit", "8bit"]
    }
    return []
  }

  // Helper function to construct the full model name
  const getFullModelName = () => {
    if (isMarvisModel(baseModel) && quantization !== "none") {
      return `${baseModel}-MLX-${quantization}`
    }
    return baseModel
  }

  // Get the current full model name
  const model = getFullModelName()

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
  }

  const handleModelChange = (newModel: string) => {
    setBaseModel(newModel)
    // Set default quantization based on available options
    if (isMarvisModel(newModel)) {
      const availableQuants = getAvailableQuantizations(newModel)
      if (availableQuants.includes("6bit")) {
        setQuantization("6bit")
      } else if (availableQuants.length > 0) {
        setQuantization(availableQuants[0])
      }
    }
  }

  const handlePlayPause = () => {
    const audio = audioRef.current
    if (!audio || chunksRef.current.length === 0) {
      // Nothing generated yet: generate first.
      handleGenerate()
      return
    }

    if (isPlaying) {
      wantPlayRef.current = false
      audio.pause()
      setIsPlaying(false)
    } else {
      wantPlayRef.current = true
      setIsPlaying(true)
      if (waitingRef.current) {
        advanceIfWaiting()
        if (!generatingRef.current && waitingRef.current) finishPlayback()
      } else {
        audio.play().catch(() => setIsPlaying(false))
      }
    }
  }

  const buildSpeechBody = (input: string, pauseMs: number, narrationId: string) => {
    const lower = model.toLowerCase()
    const voice = model.includes("marvis")
      ? "conversational_a"
      : lower.includes("qwen3")
        ? qwen3Voices.includes(selectedVoice)
          ? selectedVoice
          : "ryan"
        : "af_heart"

    return {
      model: model, // Or the specific model identifier if different
      input,
      voice: voice,
      speed: speed,
      // WAV keeps chunk boundaries gapless and makes merging for download simple
      response_format: "wav",
      // Make separately generated chunks sound like one narration: the server trims
      // silence, caps long pauses, levels the volume, matches the pace of the first
      // chunk (narration_id) and adds a fixed pause after the chunk.
      trim_silence: true,
      max_pause_ms: 500,
      loudness_db: -20,
      pause_ms: pauseMs,
      narration_id: narrationId,
      // The model sometimes fails to stop; bound how long a chunk can run (Qwen3 speaks
      // about 12.5 tokens per second, roughly 1 token per character).
      ...(lower.includes("qwen3") ? { max_tokens: Math.min(1200, Math.ceil(input.length * 1.6) + 40) } : {}),
      ...(lower.includes("qwen3") && instruction ? { instruct: instruction } : {}),
    }
  }

  const handleGenerate = async () => {
    if (!audioRef.current || generatingRef.current) return

    const parts = splitIntoChunks(text)
    const narrationId = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
    if (parts.length === 0) {
      setMessage({ type: "error", text: "There is no text to convert to speech." })
      return
    }

    // Reset any previous playback
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    audioRef.current.pause()
    clearChunks()
    waitingRef.current = false
    wantPlayRef.current = true
    generatingRef.current = true
    setIsPlaying(false)
    setMessage(null)
    setCurrentTime("00:00")
    setDuration("00:00")
    setProgress(0)
    setGenProgress({ done: 0, total: parts.length })
    setIsGenerating(true)

    try {
      for (let i = 0; i < parts.length; i++) {
        const response = await fetch(`${getApiUrl()}/v1/audio/speech`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(buildSpeechBody(parts[i].text, parts[i].pauseMs, narrationId)),
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const chunkDuration = await getBlobDuration(url)
        chunksRef.current.push({ blob, url, duration: chunkDuration })
        setGenProgress({ done: i + 1, total: parts.length })
        setDuration(formatTime(totalDuration()))

        if (i === 0) {
          if (wantPlayRef.current) {
            setIsPlaying(true)
            playChunk(0)
          } else {
            loadChunk(0)
          }
        } else {
          advanceIfWaiting()
        }
      }
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        // Stopped by the user: keep whatever was already generated
        if (abortRef.current === controller) {
          const done = chunksRef.current.length
          setMessage({
            type: "info",
            text:
              done > 0
                ? `Generation stopped after ${done} of ${parts.length} ${done === 1 ? "part" : "parts"}. The audio generated so far is still available.`
                : "Generation stopped.",
          })
        }
        return
      }
      console.error("Error generating speech:", error)
      setMessage({
        type: "error",
        text:
          chunksRef.current.length > 0
            ? `Generation stopped after ${chunksRef.current.length} of ${parts.length} parts: ${(error as Error).message}`
            : `Error generating speech: ${(error as Error).message}`,
      })
    } finally {
      if (abortRef.current === controller) {
        generatingRef.current = false
        setIsGenerating(false)
        // Playback reached the end of what existed and nothing more is coming
        if (waitingRef.current) {
          const next = currentIdxRef.current + 1
          if (next < chunksRef.current.length && wantPlayRef.current) advanceIfWaiting()
          else finishPlayback()
        }
      }
    }
  }

  const handleStop = () => {
    // Cancels the in-flight request (the server drops it on disconnect) and skips
    // the remaining chunks. Audio already generated stays playable.
    abortRef.current?.abort()
  }

  const handleDownload = async () => {
    const chunks = chunksRef.current
    if (chunks.length === 0) {
      setMessage({ type: "error", text: "Generate some audio first, then download it." })
      return
    }
    if (generatingRef.current) {
      setMessage({ type: "info", text: "Please wait for generation to finish before downloading." })
      return
    }

    try {
      const blob = chunks.length === 1 ? chunks[0].blob : await mergeToWav(chunks.map((c) => c.blob))
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `${(pdfName ?? "speech").replace(/\.pdf$/i, "")}.wav`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 10000)
    } catch (error) {
      console.error("Error preparing download:", error)
      setMessage({ type: "error", text: `Could not prepare download: ${(error as Error).message}` })
    }
  }

  const seekTo = (fraction: number) => {
    const audio = audioRef.current
    const chunks = chunksRef.current
    if (!audio || chunks.length === 0) return
    const target = Math.max(0, Math.min(1, fraction)) * totalDuration()
    let acc = 0
    for (let i = 0; i < chunks.length; i++) {
      if (target < acc + chunks[i].duration || i === chunks.length - 1) {
        const offset = Math.min(Math.max(0, target - acc), chunks[i].duration)
        if (i === currentIdxRef.current) {
          audio.currentTime = offset
        } else {
          waitingRef.current = false
          loadChunk(i)
          audio.addEventListener(
            "loadedmetadata",
            () => {
              audio.currentTime = offset
              if (wantPlayRef.current) audio.play().catch(() => setIsPlaying(false))
            },
            { once: true },
          )
        }
        updateTimeline()
        return
      }
      acc += chunks[i].duration
    }
  }

  const isPdfDrag = (e: React.DragEvent) => Array.from(e.dataTransfer.types || []).includes("Files")

  const handleDragOver = (e: React.DragEvent) => {
    if (!isPdfDrag(e)) return
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: React.DragEvent) => {
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return
    setIsDragging(false)
  }

  const handleDrop = async (e: React.DragEvent) => {
    if (!isPdfDrag(e)) return
    e.preventDefault()
    setIsDragging(false)

    const files = Array.from(e.dataTransfer.files)
    const pdf = files.find((f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"))
    if (!pdf) {
      setMessage({ type: "error", text: "Only PDF files are supported. Drop a .pdf file." })
      return
    }

    setIsExtracting(true)
    setMessage(null)
    try {
      const form = new FormData()
      form.append("file", pdf)
      const response = await fetch(`${getApiUrl()}/v1/documents/extract-text`, {
        method: "POST",
        body: form,
      })
      if (!response.ok) {
        let detail = `HTTP error! status: ${response.status}`
        try {
          const body = await response.json()
          if (body?.detail) detail = String(body.detail)
        } catch {}
        throw new Error(detail)
      }
      const data = await response.json()
      setText(data.text)
      setPdfName(pdf.name)
      setMessage({
        type: "info",
        text: `Loaded ${pdf.name} (${data.pages} ${data.pages === 1 ? "page" : "pages"}${
          files.length > 1 ? "; only the first PDF was used" : ""
        }). Review the text, then click Generate.`,
      })
    } catch (error) {
      console.error("Error extracting PDF text:", error)
      setMessage({ type: "error", text: `Could not read ${pdf.name}: ${(error as Error).message}` })
    } finally {
      setIsExtracting(false)
    }
  }

  const getCharacterCount = () => {
    return text.length
  }

  const handleVoiceChange = (voice: string) => {
    setSelectedVoice(voice)
  }

  return (
    <LayoutWrapper activeTab="audio" activePage="text-to-speech">
      <div className="flex flex-1 overflow-hidden">
        {/* Text Input Area */}
        <div
          className="relative flex-1 overflow-auto border-r border-gray-200 dark:border-gray-700 p-6"
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {(isDragging || isExtracting) && (
            <div className="pointer-events-none absolute inset-2 z-10 flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-sky-500 bg-sky-50/90 dark:bg-gray-900/90 text-sky-600 dark:text-sky-400">
              {isExtracting ? (
                <RefreshCw className="mb-2 h-8 w-8 animate-spin" />
              ) : (
                <Upload className="mb-2 h-8 w-8" />
              )}
              <span className="text-sm font-medium">
                {isExtracting ? "Extracting text from PDF..." : "Drop a PDF to load its text"}
              </span>
            </div>
          )}
          <h1 className="mb-6 text-2xl font-bold">Speech Synthesis</h1>
          <textarea
            className="min-h-[200px] w-full resize-none rounded-md border border-gray-200 dark:border-gray-700 p-4 text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 focus:border-blue-500 focus:outline-none"
            value={text}
            onChange={handleTextChange}
            placeholder="Enter text to convert to speech, or drop a PDF here..."
          />
          {message && (
            <div
              className={`mt-3 rounded-md border px-3 py-2 text-sm ${
                message.type === "error"
                  ? "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                  : "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-300"
              }`}
            >
              {message.text}
            </div>
          )}
          <div className="mt-auto flex items-center justify-between pt-4 text-xs text-gray-500 dark:text-gray-400">
            <div className="flex items-center space-x-2">
              <span>Long Text</span>
              <div className="h-2 w-2 rounded-full bg-gray-400 dark:bg-gray-500"></div>
            </div>
            <div className="flex items-center space-x-2">
              <span>{getCharacterCount().toLocaleString()} characters</span>
              <div className="h-2 w-2 rounded-full bg-gray-200 dark:bg-gray-600"></div>
            </div>
          </div>
          <div className="mt-4 flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <button
                className="rounded-md border border-gray-200 dark:border-gray-700 p-1 hover:bg-gray-50 dark:hover:bg-gray-800"
                onClick={handleDownload}
              >
                <Download className="h-4 w-4 text-gray-500 dark:text-gray-400" />
              </button>
            </div>
            <div className="flex items-center space-x-2">
              {isGenerating && (
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {genProgress.total > 1
                    ? `Generating ${Math.min(genProgress.done + 1, genProgress.total)} of ${genProgress.total}...`
                    : "Generating..."}
                </span>
              )}
              {isGenerating ? (
                <button
                  className="rounded-md bg-red-500 dark:bg-red-600 px-3 py-1 text-sm text-white flex items-center hover:bg-red-600 dark:hover:bg-red-700"
                  onClick={handleStop}
                  title="Stop generating (audio already generated is kept)"
                >
                  <Square className="h-4 w-4 mr-1 fill-current" />
                  Stop
                </button>
              ) : (
                <button
                  className="rounded-md bg-sky-500 dark:bg-sky-600 px-3 py-1 text-sm text-white flex items-center hover:bg-sky-600 dark:hover:bg-sky-700"
                  onClick={handleGenerate}
                >
                  <RefreshCw className="h-4 w-4 mr-1" />
                  Generate
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Settings Panel */}
        <div className="relative shrink-0">
        <button
          className={`absolute left-0 top-1/2 z-20 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-full border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-500 dark:text-gray-400 shadow-sm hover:bg-gray-50 dark:hover:bg-gray-700 transition-transform duration-200 ${
            settingsOpen ? "-translate-x-1/2" : "-translate-x-full"
          }`}
          onClick={() => setSettingsOpen((open) => !open)}
          aria-label={settingsOpen ? "Hide settings panel" : "Show settings panel"}
          aria-expanded={settingsOpen}
          title={settingsOpen ? "Hide settings" : "Show settings"}
        >
          {settingsOpen ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
        <div
          className={`h-full overflow-hidden bg-white dark:bg-gray-900 transition-[width,visibility] duration-200 ease-in-out ${
            settingsOpen ? "w-80" : "invisible w-0"
          }`}
          aria-hidden={!settingsOpen}
        >
          <div className="h-full w-80 overflow-auto p-4">
          <>
              <div className="mb-6">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm">Model</span>
                  <div className="relative">
                    <select
                      className="flex w-40 appearance-none items-center justify-between rounded-md border border-gray-200 dark:border-gray-700 px-2 py-1 text-sm pr-8 bg-white dark:bg-gray-800"
                      value={baseModel}
                      onChange={(e) => handleModelChange(e.target.value)}
                    >
                      <option value="Marvis-AI/marvis-tts-100m-v0.2">Marvis-TTS-100m-v0.2</option>
                      <option value="Marvis-AI/marvis-tts-250m-v0.2">Marvis-TTS-250m-v0.2</option>
                      <option value="Marvis-AI/marvis-tts-250m-v0.1">Marvis-TTS-250m-v0.1</option>
                      <option value="mlx-community/Kokoro-82M-bf16">Kokoro</option>
                      <option value="mlx-community/Spark-TTS-0.5B-bf16">SparkTTS</option>
		      <option value="mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16">Qwen3-TTS</option>
                    </select>
                    <ChevronDown className="absolute right-2 top-2 h-4 w-4 pointer-events-none" />
                  </div>
                </div>
              </div>

              {isMarvisModel(baseModel) && (
                <div className="mb-6">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-sm">Quantization</span>
                    <div className="relative">
                      <select
                        className="flex w-40 appearance-none items-center justify-between rounded-md border border-gray-200 dark:border-gray-700 px-2 py-1 text-sm pr-8 bg-white dark:bg-gray-800"
                        value={quantization}
                        onChange={(e) => setQuantization(e.target.value)}
                      >
                        {getAvailableQuantizations(baseModel).map((quant) => (
                          <option key={quant} value={quant}>
                            {quant === "none" ? "None (bf16)" : quant.replace("bit", "-bit")}
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-2 top-2 h-4 w-4 pointer-events-none" />
                    </div>
                  </div>
                </div>
              )}
              {isQwen3Model(baseModel) && (
                <div className="mb-6">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-sm">Voice</span>
                    <div className="relative">
                      <select
                        className="flex w-40 appearance-none items-center justify-between rounded-md border border-gray-200 dark:border-gray-700 px-2 py-1 text-sm pr-8 bg-white dark:bg-gray-800"
                        value={qwen3Voices.includes(selectedVoice) ? selectedVoice : "ryan"}
                        onChange={(e) => setSelectedVoice(e.target.value)}
                      >
                        {qwen3Voices.map((v) => (
                          <option key={v} value={v}>
                            {v}
                          </option>
                        ))}
                      </select>
                      <ChevronDown className="absolute right-2 top-2 h-4 w-4 pointer-events-none" />
                    </div>
                  </div>
                </div>
              )}

              {isQwen3Model(baseModel) && (
                <div className="mb-6">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-sm">Instruction (style)</span>
                  </div>
                  <textarea
                    className="w-full rounded-md border border-gray-200 dark:border-gray-700 p-2 text-sm bg-white dark:bg-gray-800"
                    rows={2}
                    placeholder="Describe the speaking style (leave empty for none)"
                    value={instruction}
                    onChange={(e) => setInstruction(e.target.value)}
                  />
                </div>
              )}
              <div className="mb-6">
                <div className="text-xs text-gray-500 dark:text-gray-400">
                  <span className="font-medium">Selected Model:</span> <span className="font-mono">{model}</span>
                </div>
              </div>



              <div className="mb-6">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm">Speed</span>
                  <div className="flex items-center">
                    <div className="flex space-x-2 mr-2">
                      <button
                        onClick={() => setSpeed(0.5)}
                        className={`px-2 py-0.5 text-xs rounded-md ${speed === 0.5 ? "bg-sky-100 dark:bg-sky-900 text-sky-600 dark:text-sky-300" : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"}`}
                      >
                        0.5x
                      </button>
                      <button
                        onClick={() => setSpeed(1)}
                        className={`px-2 py-0.5 text-xs rounded-md ${speed === 1 ? "bg-sky-100 dark:bg-sky-900 text-sky-600 dark:text-sky-300" : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"}`}
                      >
                        1x
                      </button>
                      <button
                        onClick={() => setSpeed(1.5)}
                        className={`px-2 py-0.5 text-xs rounded-md ${speed === 1.5 ? "bg-sky-100 dark:bg-sky-900 text-sky-600 dark:text-sky-300" : "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"}`}
                      >
                        1.5x
                      </button>
                    </div>
                    <span className="text-sm font-medium">{speed}x</span>
                  </div>
                </div>
                <div className="flex items-center">
                  <span className="text-xs text-gray-500 mr-2">Slow</span>
                  <RangeInput
                    min={0.5}
                    max={2}
                    step={0.1}
                    value={speed}
                    onChange={(e) => setSpeed(Number.parseFloat(e.target.value))}
                    ariaLabel="Speed control"
                  />
                  <span className="text-xs text-gray-500 ml-2">Fast</span>
                </div>
              </div>
          </>
          </div>
        </div>
        </div>
      </div>

      {/* Audio Player */}
      <div className="border-t border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 w-full">
        <div className="flex items-center w-full px-0">
          <button
            className="flex h-14 w-14 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 ml-4"
            onClick={handlePlayPause}
          >
            {isPlaying ? <Pause className="h-6 w-6" /> : <Play className="h-6 w-6" />}
          </button>

          <div className="flex flex-col justify-between h-full flex-1 px-4 py-2">
            <div className="flex items-center justify-end w-full">
              <div className="flex items-center space-x-2">
                <button
                  className="rounded-md border border-gray-200 dark:border-gray-700 p-1 hover:bg-gray-50 dark:hover:bg-gray-800"
                  onClick={handleDownload}
                >
                  <Download className="h-4 w-4 text-gray-500 dark:text-gray-400" />
                </button>
              </div>
            </div>

            <div className="flex items-center mt-2">
              <div
                className="flex-1 bg-gray-200 dark:bg-gray-700 h-1 rounded-full cursor-pointer relative"
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect()
                  seekTo((e.clientX - rect.left) / rect.width)
                }}
              >
                <div
                  className="bg-black dark:bg-white h-1 rounded-full absolute top-0 left-0"
                  style={{ width: `${progress * 100}%` }}
                ></div>
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400 ml-4 whitespace-nowrap mr-4">
                {currentTime} / {duration}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Hidden audio element for actual implementation */}
      <audio ref={audioRef} className="hidden" />
    </LayoutWrapper>
  )
}
