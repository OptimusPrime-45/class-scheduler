"use client";

import React from "react";
import { Users, FolderKanban, BookOpen, CheckCircle2, ChevronRight } from "lucide-react";

type TabType = "dashboard" | "grid" | "solver" | "availability" | "master";

interface Teacher {
  id: number;
  full_name: string;
  teacher_type: string;
  max_lectures_per_day: number;
  is_active: boolean;
  subject_ids?: number[];
}

interface Batch {
  is_active: boolean;
}

interface Subject {
  is_active: boolean;
}

interface ScheduleEntry {
  teacher_id: number | null;
}

interface Schedule {
  entries: ScheduleEntry[];
}

interface DashboardViewProps {
  teachers: Teacher[];
  batches: Batch[];
  subjects: Subject[];
  currentSchedule: Schedule | null;
  stats: { activeF: number; activeB: number; activeS: number; fillRate: number };
  setActiveTab: (tab: TabType) => void;
}

export default function DashboardView({
  teachers,
  stats,
  currentSchedule,
  setActiveTab
}: DashboardViewProps) {
  return (
    <>
      {/* 4 Cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {[
          { label: "Active Faculty", val: stats.activeF, sub: "Qualified Instructors", icon: Users },
          { label: "Grade Batches", val: stats.activeB, sub: "SSC & ICSE Streams", icon: FolderKanban },
          { label: "Curriculum Subjects", val: stats.activeS, sub: "Science / Math Focus", icon: BookOpen },
          { label: "Schedule Fill Rate", val: `${stats.fillRate}%`, sub: currentSchedule ? "Allocated Periods" : "No active draft", icon: CheckCircle2 }
        ].map((card, idx) => {
          const Icon = card.icon;
          return (
            <div key={idx} className="bg-card-bg border border-border-color p-4.5 rounded-lg flex flex-col gap-2 shadow-[0_1px_2px_rgba(0,0,0,0.01)] hover:border-accent-color/40 transition-colors duration-150">
              <div className="flex justify-between items-center">
                <span className="text-xs font-semibold text-secondary-text">{card.label}</span>
                <Icon className="w-4 h-4 text-muted-text stroke-[1.8]" />
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="text-2xl font-bold tracking-tight text-primary-text">{card.val}</span>
                <span className="text-[11px] text-muted-text">{card.sub}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Workload Progress Chart & Status Key */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 bg-elevated border border-border-color rounded-lg p-6 flex flex-col gap-4">
          <div>
            <h3 className="text-xs font-bold text-primary-text uppercase tracking-wider">Faculty Lesson Workload</h3>
            <p className="text-xs text-muted-text font-sans">Daily load assignment statistics (Max limits vs allocated slots)</p>
          </div>
          
          <div className="flex flex-col gap-3.5">
            {teachers.slice(0, 5).map((t) => {
              const allocated = currentSchedule 
                ? currentSchedule.entries.filter(e => e.teacher_id === t.id).length
                : 0;
              const percentage = Math.min(100, Math.round((allocated / t.max_lectures_per_day) * 100));

              return (
                <div key={t.id} className="flex flex-col gap-1">
                  <div className="flex justify-between text-xs font-semibold">
                    <span className="text-primary-text">{t.full_name} <span className="text-muted-text text-[10px] font-normal">({t.teacher_type})</span></span>
                    <span className="text-secondary-text">{allocated} / {t.max_lectures_per_day} Lectures</span>
                  </div>
                  <div className="h-2 w-full bg-background border border-border-color/50 rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-accent-color rounded-full transition-all duration-300"
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Status definitions sidebar */}
        <div className="bg-elevated border border-border-color rounded-lg p-6 flex flex-col justify-between">
          <div className="flex flex-col gap-4">
            <div>
              <h3 className="text-xs font-bold text-primary-text uppercase tracking-wider">Operational Status Keys</h3>
              <p className="text-xs text-muted-text font-sans">Linear-style status definitions for availability roster</p>
            </div>

            <div className="flex flex-col gap-3">
              <div className="flex items-center gap-3.5 text-xs text-secondary-text">
                <span className="w-2 h-2 rounded-full bg-success-color" />
                <div className="flex flex-col">
                  <span className="font-semibold text-primary-text">Available All Day</span>
                  <span className="text-[11px] text-muted-text">Teacher responded as fully available.</span>
                </div>
              </div>
              
              <div className="flex items-center gap-3.5 text-xs text-secondary-text">
                <span className="w-2 h-2 rounded-full bg-warning-color" />
                <div className="flex flex-col">
                  <span className="font-semibold text-primary-text">Partial Availability</span>
                  <span className="text-[11px] text-muted-text">Specific hours pick (e.g. 16:00 - 18:00).</span>
                </div>
              </div>

              <div className="flex items-center gap-3.5 text-xs text-secondary-text">
                <span className="w-2 h-2 rounded-full bg-danger-color" />
                <div className="flex flex-col">
                  <span className="font-semibold text-primary-text">Unavailable</span>
                  <span className="text-[11px] text-muted-text">Teacher marked as unavailable.</span>
                </div>
              </div>
            </div>
          </div>

          <button 
            onClick={() => setActiveTab("grid")}
            className="w-full flex items-center justify-between border border-border-color bg-card-bg px-3.5 py-2 text-xs font-semibold rounded-md text-secondary-text hover:text-primary-text transition-colors duration-150 mt-4 cursor-pointer"
          >
            Launch Timetable Editor
            <ChevronRight className="w-4 h-4 text-muted-text" />
          </button>
        </div>
      </div>
    </>
  );
}
