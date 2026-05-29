"use client";

import React from "react";

type AvailabilityStatus = "AVAILABLE_ALL_DAY" | "PARTIAL" | "UNAVAILABLE";

interface Teacher {
  id: number;
  full_name: string;
  teacher_type: string;
  is_active: boolean;
  subject_ids?: number[];
}

interface TeacherAvailability {
  teacher_id: number;
  status: AvailabilityStatus;
  source: string;
  responded_at?: string | null;
}

interface AvailabilityViewProps {
  teachers: Teacher[];
  availabilityMap: Map<number, TeacherAvailability>;
  handleToggleAvailability: (teacherId: number, currentStatus: AvailabilityStatus) => void;
}

export default function AvailabilityView({
  teachers,
  availabilityMap,
  handleToggleAvailability
}: AvailabilityViewProps) {
  return (
    <div className="flex flex-col gap-6 select-none">
      <div className="border-b border-divider-color pb-4">
        <h3 className="text-base font-semibold text-primary-text tracking-tight">Faculty Availability & Responses</h3>
        <p className="text-xs text-muted-text">Manage teacher response states for the selected target date. Toggle status rows to manually override responses.</p>
      </div>

      <div className="bg-elevated border border-border-color rounded-lg overflow-hidden shadow-sm">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="bg-sidebar border-b border-border-color font-semibold uppercase tracking-wider text-secondary-text">
              <th className="p-4 border-r border-border-color/60">Faculty Member</th>
              <th className="p-4 border-r border-border-color/60">Stream Type</th>
              <th className="p-4 border-r border-border-color/60">Poll Status</th>
              <th className="p-4 border-r border-border-color/60">Source Origin</th>
              <th className="p-4 border-r border-border-color/60">Responded At</th>
              <th className="p-4 text-center">Roster Action</th>
            </tr>
          </thead>
          <tbody>
            {teachers.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-8 text-center text-xs text-muted-text">
                  No teachers registered. Go to Master Data.
                </td>
              </tr>
            ) : (
              teachers.map((t) => {
                const av = availabilityMap.get(t.id);
                const status = av?.status || "UNAVAILABLE";
                const source = av?.source || "DEFAULT";

                return (
                  <tr key={t.id} className="border-b border-divider-color last:border-b-0 hover:bg-card-bg/25 transition-colors duration-150">
                    <td className="p-4 border-r border-border-color/40 font-bold text-primary-text">{t.full_name}</td>
                    <td className="p-4 border-r border-border-color/40 font-semibold text-secondary-text">{t.teacher_type}</td>
                    <td className="p-4 border-r border-border-color/40">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${
                          status === "AVAILABLE_ALL_DAY" ? "bg-success-color" :
                          status === "PARTIAL" ? "bg-warning-color" : "bg-danger-color"
                        }`} />
                        <span className="font-semibold text-primary-text text-[11px] uppercase">{status}</span>
                      </div>
                    </td>
                    <td className="p-4 border-r border-border-color/40 uppercase font-semibold text-secondary-text text-[10px]">{source}</td>
                    <td className="p-4 border-r border-border-color/40 text-muted-text font-medium">
                      {av?.responded_at ? new Date(av.responded_at).toLocaleTimeString() : "No response"}
                    </td>
                    <td className="p-4 text-center">
                      <button
                        onClick={() => handleToggleAvailability(t.id, status)}
                        className="border border-border-color hover:border-accent-color/60 bg-card-bg hover:text-accent-color px-3 py-1 rounded text-[11px] font-bold transition-all duration-150 cursor-pointer"
                      >
                        Toggle Response State
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
