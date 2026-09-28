"use client"

import type { ReactNode } from "react"
import type { NavPage } from "@/components/nav-menu"
import { Navbar } from "@/components/navbar"

interface LayoutWrapperProps {
  children: ReactNode
  activeTab?: "audio" | "chat" | "video"
  activePage?: NavPage
}

export function LayoutWrapper({ children, activeTab = "audio", activePage = "home" }: LayoutWrapperProps) {
  return (
    <div className="flex h-screen flex-col bg-white dark:bg-gray-900 dark:text-white transition-colors">
      <Navbar activeTab={activeTab} activePage={activePage} />

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">{children}</div>
    </div>
  )
}
