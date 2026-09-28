"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { AudioWaveform, FileAudio, FileText, Menu, X } from "lucide-react"

export type NavPage = "home" | "text-to-speech" | "speech-to-speech" | "voices" | "speech-to-text" | "audio-separation"

const links = [
  { page: "text-to-speech", href: "/text-to-speech", label: "Text to Speech", Icon: FileAudio },
  { page: "speech-to-text", href: "/speech-to-text", label: "Speech to Text", Icon: FileText },
  { page: "audio-separation", href: "/audio-separation", label: "Audio Separation", Icon: AudioWaveform },
]

export function NavMenu({ activePage = "home" }: { activePage?: NavPage }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Close on outside click or Escape while the menu is open
  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onMouseDown)
    document.addEventListener("keydown", onKeyDown)
    return () => {
      document.removeEventListener("mousedown", onMouseDown)
      document.removeEventListener("keydown", onKeyDown)
    }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        className="rounded-md p-1.5 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={open ? "Close menu" : "Open menu"}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>

      {open && (
        <nav
          role="menu"
          className="absolute left-0 top-full z-50 mt-2 w-56 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 p-1 shadow-lg"
        >
          {links.map(({ page, href, label, Icon }) => (
            <Link
              key={page}
              href={href}
              role="menuitem"
              onClick={() => setOpen(false)}
              className={`flex items-center space-x-3 rounded-md px-3 py-2 text-sm ${
                activePage === page
                  ? "bg-gray-100 dark:bg-gray-800 font-medium text-black dark:text-white"
                  : "text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800"
              }`}
            >
              <Icon className="h-5 w-5 shrink-0" />
              <span>{label}</span>
            </Link>
          ))}
        </nav>
      )}
    </div>
  )
}
