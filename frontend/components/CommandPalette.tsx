"use client";

import React from "react";
import { Search } from "lucide-react";

interface CommandItem {
  name: string;
  action: () => void;
  category: string;
  icon: React.ComponentType<any>;
}

interface CommandPaletteProps {
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
  commandSearch: string;
  setCommandSearch: (search: string) => void;
  commandMatches: CommandItem[];
  cmdPaletteInputRef: React.RefObject<HTMLInputElement | null>;
}

export default function CommandPalette({
  commandPaletteOpen,
  setCommandPaletteOpen,
  commandSearch,
  setCommandSearch,
  commandMatches,
  cmdPaletteInputRef
}: CommandPaletteProps) {
  if (!commandPaletteOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-28 bg-black/10 backdrop-blur-[1.5px] select-none">
      <div className="bg-elevated border border-border-color w-[480px] rounded-lg shadow-2xl flex flex-col overflow-hidden max-h-[380px]">
        {/* Command search input header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-divider-color">
          <Search className="w-4 h-4 text-muted-text shrink-0" />
          <input
            ref={cmdPaletteInputRef}
            type="text"
            placeholder="Search commands or quick navigate..."
            value={commandSearch}
            onChange={(e) => setCommandSearch(e.target.value)}
            className="w-full text-xs font-semibold bg-transparent text-primary-text border-0 focus:outline-none"
          />
          <span className="text-[10px] font-bold text-muted-text uppercase border border-border-color bg-sidebar px-1.5 py-0.5 rounded shrink-0">
            esc
          </span>
        </div>

        {/* Filtered lists container */}
        <div className="flex-1 overflow-y-auto p-2.5 flex flex-col gap-1.5">
          {commandMatches.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-text">No command matched. Try fuzzy keywords.</div>
          ) : (
            commandMatches.map((cmd, idx) => {
              const Icon = cmd.icon;
              return (
                <button
                  key={idx}
                  onClick={() => {
                    cmd.action();
                    setCommandPaletteOpen(false);
                    setCommandSearch("");
                  }}
                  className="w-full flex items-center justify-between px-3 py-2 text-xs text-secondary-text hover:text-accent-color hover:bg-card-bg rounded transition-all duration-100 text-left cursor-pointer"
                >
                  <div className="flex items-center gap-3">
                    <Icon className="w-4 h-4 text-muted-text shrink-0 stroke-[1.8]" />
                    <span className="font-semibold text-primary-text">{cmd.name}</span>
                  </div>
                  <span className="text-[10px] text-muted-text uppercase font-semibold bg-sidebar px-2 py-0.5 rounded border border-border-color/60">
                    {cmd.category}
                  </span>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
