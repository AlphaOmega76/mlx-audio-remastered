"use client"
import Link from "next/link"
import { Github } from "lucide-react"
import { ThemeToggle } from "@/components/theme-toggle"
import { NavMenu, type NavPage } from "@/components/nav-menu"

interface NavbarProps {
  activeTab?: "audio" | "chat" | "video"
  activePage?: NavPage
}

export function Navbar({ activeTab = "audio", activePage = "home" }: NavbarProps) {
  return (
    <header className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 px-4 py-2">
      <div className="flex items-center space-x-3">
        <NavMenu activePage={activePage} />
        <Link href="/" className="flex items-center">
          <div className="mr-2 h-5 w-5">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" className="stroke-current">
              <path d="M9 18V5l12-2v13" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="6" cy="18" r="3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="18" cy="16" r="3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <span className="font-bold">MLX-Audio</span>
        </Link>
      </div>
      <div className="flex items-center space-x-4">
        <div className="flex items-center rounded-full bg-sky-100 dark:bg-sky-900 px-3 py-1 text-sm text-sky-600 dark:text-sky-300">
          <span className="mr-1">Connected</span>
          <div className="h-2 w-2 rounded-full bg-sky-600 dark:bg-sky-400"></div>
        </div>
        <a
          href="https://github.com/Blaizzy/mlx-audio"
          target="_blank"
          rel="noopener noreferrer"
          className="text-gray-600 dark:text-gray-300 hover:text-gray-800 dark:hover:text-gray-100"
        >
          <Github className="h-5 w-5" />
        </a>
        <ThemeToggle />
      </div>
    </header>
  )
}
