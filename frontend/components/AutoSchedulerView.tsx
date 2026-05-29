"use client";

import React from "react";
import { Loader2, SlidersHorizontal, CheckCircle2, Send, RefreshCw, Sparkles } from "lucide-react";

interface ScheduleEntry {
  id: number;
  batch_id: number;
  period_index: number;
  subject_id: number;
  teacher_id: number | null;
}

interface Schedule {
  id: number;
  version: number;
  status: "DRAFT" | "APPROVED" | "PUBLISHED" | "ARCHIVED";
  solver_status: string;
  objective_value?: number | null;
  solve_time_ms?: number | null;
  num_unfilled: number;
  contract_version?: string;
  entries: ScheduleEntry[];
}

interface TelegramLog {
  id: number;
  teacher_name: string;
  chat_id: number;
  target_date: string;
  status: "SENT" | "FAILED" | "SKIPPED_NO_CHAT";
  kind: string;
  message_preview: string;
  sent_at: string;
}

interface Batch {
  id: number;
  name: string;
}

interface Subject {
  id: number;
  name: string;
  code: string;
}

interface Teacher {
  id: number;
  full_name: string;
  subject_ids?: number[];
}

interface AutoSchedulerViewProps {
  handleAutoSolve: () => void;
  isLoading: boolean;
  currentSchedule: Schedule | null;
  handleApprove: () => void;
  handlePublish: () => void;
  telegramLogs: TelegramLog[];
  setSuccessMsg: (msg: string | null) => void;
  handleRetryNotification: (id: number) => void;
  batches: Batch[];
  subjectsMap: Map<number, Subject>;
  teachersMap: Map<number, Teacher>;
}

export default function AutoSchedulerView({
  handleAutoSolve,
  isLoading,
  currentSchedule,
  handleApprove,
  handlePublish,
  telegramLogs,
  setSuccessMsg,
  handleRetryNotification,
  batches,
  subjectsMap,
  teachersMap
}: AutoSchedulerViewProps) {
  return (
    <div className="flex flex-col gap-6 select-none">
      <div className="flex justify-between items-center border-b border-divider-color pb-4">
        <div>
          <h3 className="text-base font-semibold text-primary-text tracking-tight">Auto-Scheduler Review Queue</h3>
          <p className="text-xs text-muted-text">Invoke CP-SAT constraint optimization solvers deterministically. Suggestions are logged like operational updates.</p>
        </div>

        <button
          onClick={handleAutoSolve}
          disabled={isLoading}
          className="flex items-center gap-2 border border-accent-color bg-card-bg text-accent-color hover:bg-accent-color hover:text-white px-4 py-2 text-xs font-semibold rounded-md transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
        >
          {isLoading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <SlidersHorizontal className="w-3.5 h-3.5 stroke-[2.2]" />
          )}
          {isLoading ? "Running CP-SAT Solver..." : "Generate Optimized Draft"}
        </button>
      </div>

      {currentSchedule ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          
          {/* PR suggestion details panel */}
          <div className="lg:col-span-2 flex flex-col gap-6">
            <div className="bg-elevated border border-border-color rounded-lg p-6 flex flex-col gap-5">
              <div className="flex justify-between items-center border-b border-divider-color pb-3.5">
                <div className="flex items-center gap-2.5">
                  <span className="text-xs font-bold text-accent-color bg-card-bg border border-border-color px-2.5 py-0.5 rounded-full">
                    Draft v{currentSchedule.version}
                  </span>
                  <span className="text-xs text-muted-text font-semibold">Solver run completed</span>
                </div>

                <span className="text-xs text-secondary-text font-bold">
                  Objective Score: <span className="font-bold text-primary-text">{currentSchedule.objective_value ?? "N/A"}</span>
                </span>
              </div>

              <div className="flex flex-col gap-2">
                <h4 className="text-xs font-bold text-secondary-text uppercase tracking-wider">Solver Diagnostics</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 bg-background border border-border-color/60 rounded-md p-4">
                  {[
                    { label: "Solve Time", val: `${currentSchedule.solve_time_ms ?? 0} ms` },
                    { label: "Unfilled Slots", val: currentSchedule.num_unfilled },
                    { label: "Status Result", val: currentSchedule.solver_status },
                    { label: "Contract Version", val: `v${currentSchedule.contract_version ?? "1"}` }
                  ].map((stat, idx) => (
                    <div key={idx} className="flex flex-col gap-0.5">
                      <span className="text-[10px] text-muted-text uppercase font-bold">{stat.label}</span>
                      <span className="text-xs font-extrabold text-primary-text">{stat.val}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Quick review action triggers */}
              <div className="flex items-center gap-3.5 border-t border-divider-color pt-4">
                {currentSchedule.status === "DRAFT" && (
                  <button
                    onClick={handleApprove}
                    className="flex items-center gap-2 border border-border-color hover:border-accent-color/60 bg-card-bg text-accent-color px-4 py-2 text-xs font-semibold rounded-md transition-all duration-150 cursor-pointer"
                  >
                    <CheckCircle2 className="w-4 h-4 stroke-[2]" />
                    Approve Suggested Draft
                  </button>
                )}

                {currentSchedule.status === "APPROVED" && (
                  <button
                    onClick={handlePublish}
                    className="flex items-center gap-2 border border-border-color hover:border-success-color/60 bg-card-bg text-success-color px-4 py-2 text-xs font-semibold rounded-md transition-all duration-150 cursor-pointer"
                  >
                    <Send className="w-4 h-4 stroke-[2]" />
                    Publish to Telegram Channel
                  </button>
                )}

                {currentSchedule.status === "PUBLISHED" && (
                  <div className="flex items-center gap-2 text-success-color text-xs font-semibold">
                    <CheckCircle2 className="w-4 h-4 stroke-[2]" />
                    Schedule has been fully published and active on Telegram channel.
                  </div>
                )}
              </div>
            </div>

            {/* Telegram Notification Dispatch Log Inspector */}
            <div className="bg-elevated border border-border-color rounded-lg p-6 flex flex-col gap-4">
              <div className="flex justify-between items-center border-b border-divider-color pb-3">
                <div>
                  <h4 className="text-xs font-bold text-primary-text uppercase tracking-wider flex items-center gap-2">
                    <Send className="w-4 h-4 text-accent-color stroke-[2]" />
                    Telegram Dispatch logs
                  </h4>
                  <p className="text-xs text-muted-text font-sans">Real-time status of notification logs and reminder dispatches</p>
                </div>

                <button 
                  onClick={() => {
                    setSuccessMsg("Telegram log list refreshed.");
                  }}
                  className="flex items-center gap-1 border border-border-color hover:border-accent-color/60 bg-card-bg px-2.5 py-1 text-[11px] font-bold rounded text-secondary-text hover:text-primary-text transition-all duration-150 cursor-pointer"
                >
                  <RefreshCw className="w-3 h-3 stroke-[2]" />
                  Refresh logs
                </button>
              </div>

              <div className="flex flex-col gap-3">
                {telegramLogs.map((log) => (
                  <div 
                    key={log.id} 
                    className="flex items-center justify-between border border-divider-color/60 p-3 rounded-md text-xs hover:border-accent-color/20 transition-all duration-150 bg-sidebar/20"
                  >
                    <div className="flex items-center gap-3 overflow-hidden">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${
                        log.status === "SENT" ? "bg-success-color" :
                        log.status === "SKIPPED_NO_CHAT" ? "bg-warning-color" : "bg-danger-color"
                      }`} />
                      <div className="flex flex-col overflow-hidden font-sans">
                        <span className="font-bold text-primary-text text-[13px]">{log.teacher_name}</span>
                        <span className="text-[11px] text-muted-text truncate">{log.message_preview}</span>
                      </div>
                    </div>
                    
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-[10px] text-muted-text font-bold">{log.sent_at}</span>
                      {log.status === "FAILED" || log.status === "SKIPPED_NO_CHAT" ? (
                        <button
                          onClick={() => handleRetryNotification(log.id)}
                          className="border border-border-color hover:border-accent-color/60 px-2 py-0.5 rounded text-[10px] font-bold text-secondary-text hover:text-accent-color bg-card-bg transition-colors cursor-pointer"
                        >
                          Retry Dispatch
                        </button>
                      ) : (
                        <span className="text-[10px] font-semibold uppercase text-success-color bg-success-color/10 border border-success-color/20 px-2 py-0.5 rounded">
                          Dispatched
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Suggestion list checklist sidecar */}
          <div className="bg-elevated border border-border-color rounded-lg p-6 flex flex-col gap-4 max-h-[480px] overflow-y-auto">
            <div>
              <h4 className="text-xs font-semibold text-primary-text uppercase tracking-wider">Suggested Allocations</h4>
              <p className="text-xs text-muted-text">Draft checklist for active batch slots</p>
            </div>

            <div className="flex flex-col gap-2">
              {currentSchedule.entries.map((entry) => {
                const batch = batches.find(b => b.id === entry.batch_id);
                const subject = subjectsMap.get(entry.subject_id);
                const teacher = entry.teacher_id ? teachersMap.get(entry.teacher_id) : null;

                return (
                  <div 
                    key={entry.id}
                    className="flex items-center gap-3 border border-divider-color/60 p-2.5 rounded-md text-xs hover:border-accent-color/30 transition-all duration-100"
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${teacher ? "bg-success-color" : "bg-danger-color"}`} />
                    <div className="flex flex-col gap-0.5 flex-1 font-sans">
                      <div className="flex justify-between font-bold text-primary-text">
                        <span>{batch?.name} · P{entry.period_index}</span>
                        <span className="text-accent-color">{subject?.code}</span>
                      </div>
                      <span className="text-[11px] text-secondary-text">
                        {teacher ? teacher.full_name : "Unfilled - Reason: Resource overlap/max limits"}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

        </div>
      ) : (
        <div className="bg-elevated border border-dashed border-border-color rounded-lg p-16 flex flex-col items-center justify-center text-center gap-3.5">
          <Sparkles className="w-8 h-8 text-muted-text stroke-[1.5]" />
          <div className="flex flex-col gap-1 max-w-sm">
            <h4 className="text-xs font-semibold text-primary-text uppercase tracking-wider">No Draft Active</h4>
            <p className="text-xs text-muted-text font-sans">
              Press "Generate Optimized Draft" to trigger OR-Tools and solve daily schedule allocations with mathematical constraints.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
