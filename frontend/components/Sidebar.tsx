"use client";

import React from "react";
import {
  LayoutDashboard,
  Calendar,
  Sparkles,
  Clock,
  FolderKanban,
  Bookmark
} from "lucide-react";

type TabType = "dashboard" | "grid" | "solver" | "availability" | "master";

interface SidebarProps {
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  targetDate: string;
  setTargetDate: (date: string) => void;
  setCommandPaletteOpen: (open: boolean) => void;
}

export default function Sidebar({
  activeTab,
  setActiveTab,
  targetDate,
  setTargetDate,
  setCommandPaletteOpen
}: SidebarProps) {
  return (
    <aside className="w-64 bg-sidebar border-r border-border-color flex flex-col justify-between p-4 select-none">
      <div className="flex flex-col gap-6">
        <div className="flex items-center justify-between px-2 py-1">
          <div className="flex items-center gap-2.5">
            <Bookmark className="w-5 h-5 text-accent-color stroke-[2.5]" />
            <h1 className="text-[14px] font-bold tracking-tight text-primary-text">Smart Scheduler</h1>
          </div>
          
          <button
            onClick={() => setCommandPaletteOpen(true)}
            className="text-[10px] font-semibold text-muted-text border border-border-color bg-card-bg px-1.5 py-0.5 rounded cursor-pointer hover:border-accent-color/60 transition-colors"
          >
            ⌘K
          </button>
        </div>

        {/* Date Picker widget */}
        <div className="flex flex-col gap-1.5 px-2">
          <span className="text-[10px] font-bold uppercase tracking-wider text-muted-text">Target Date</span>
          <input
            type="date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            className="w-full text-xs font-semibold bg-card-bg border border-border-color rounded-md px-2.5 py-1.5 focus:outline-none focus:border-accent-color text-primary-text font-sans"
          />
        </div>

        {/* Sidebar Nav buttons */}
        <nav className="flex flex-col gap-1">
          {[
            { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
            { id: "grid", label: "Notion Grid", icon: Calendar },
            { id: "solver", label: "Auto Scheduler", icon: Sparkles },
            { id: "availability", label: "Availability", icon: Clock },
            { id: "master", label: "Master Data", icon: FolderKanban }
          ].map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => setActiveTab(item.id as TabType)}
                className={`flex items-center gap-3 px-3 py-2 text-xs font-medium rounded-md transition-all duration-150 text-left ${
                  isActive
                    ? "bg-card-bg text-accent-color border border-border-color/60 font-semibold"
                    : "text-secondary-text hover:text-primary-text hover:bg-card-bg/40"
                }`}
              >
                <Icon className={`w-4 h-4 stroke-[1.8] ${isActive ? "text-accent-color" : "text-secondary-text/80"}`} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Brand footer panel */}
      <div className="flex flex-col gap-1.5 px-2 border-t border-divider-color/60 pt-4">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-text">Operational Status</span>
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-success-color animate-pulse"></span>
          <span className="text-xs text-secondary-text font-sans">FastAPI Engine Online</span>
        </div>
      </div>
    </aside>
  );
}
