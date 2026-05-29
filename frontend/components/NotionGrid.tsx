"use client";

import React from "react";
import { ListFilter, AlertTriangle, AlertCircle } from "lucide-react";

type DensityType = "cozy" | "compact";
type Board = "SSC" | "ICSE";
type EntryStatus = "PLANNED" | "CONDUCTED" | "CANCELLED";
type AvailabilityStatus = "AVAILABLE_ALL_DAY" | "PARTIAL" | "UNAVAILABLE";
type AvailabilitySource = "TELEGRAM" | "ADMIN" | "DEFAULT";
type TeacherType = "FULL_TIME" | "PART_TIME";
type SubjectDifficulty = "STANDARD" | "DIFFICULT";

interface Teacher {
  id: number;
  full_name: string;
  phone?: string;
  email?: string;
  teacher_type: TeacherType;
  telegram_chat_id?: number | null;
  telegram_username?: string | null;
  max_lectures_per_day: number;
  preferred_hours_start?: string | null;
  preferred_hours_end?: string | null;
  is_active: boolean;
  notes?: string | null;
  subject_ids?: number[];
}

interface Batch {
  id: number;
  name: string;
  grade: number;
  board: Board;
  is_active: boolean;
}

interface Subject {
  id: number;
  name: string;
  code: string;
  difficulty: SubjectDifficulty;
  is_active: boolean;
}

interface ScheduleEntry {
  id: number;
  schedule_id: number;
  batch_id: number;
  batch_slot_id: number | null;
  period_index: number;
  subject_id: number;
  teacher_id: number | null;
  status: EntryStatus;
  is_locked: boolean;
  start_time: string;
  end_time: string;
  cancelled_reason?: string | null;
}

interface Schedule {
  id: number;
  schedule_date: string;
  version: number;
  status: "DRAFT" | "APPROVED" | "PUBLISHED" | "ARCHIVED";
  solver_status: "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "UNKNOWN" | "MODEL_INVALID" | "ERROR";
  objective_value?: number | null;
  solve_time_ms?: number | null;
  num_unfilled: number;
  generated_at?: string | null;
  approved_at?: string | null;
  published_at?: string | null;
  notes?: string | null;
  contract_version?: string;
  entries: ScheduleEntry[];
}

interface TeacherAvailability {
  id: number;
  teacher_id: number;
  availability_date: string;
  status: AvailabilityStatus;
  is_default: boolean;
  responded_at?: string | null;
  source: AvailabilitySource;
  notes?: string | null;
  windows: any[];
}

interface NotionGridProps {
  density: DensityType;
  setDensity: (density: DensityType) => void;
  filterBoard: Board | "ALL";
  setFilterBoard: (board: Board | "ALL") => void;
  filterGrade: number | "ALL";
  setFilterGrade: (grade: number | "ALL") => void;
  filteredBatches: Batch[];
  currentSchedule: Schedule | null;
  subjectsMap: Map<number, Subject>;
  teachersMap: Map<number, Teacher>;
  availabilityMap: Map<number, TeacherAvailability>;
  checkConstraints: (entry: ScheduleEntry, teacherId: number) => string[];
  selectedCell: { batchId: number; periodIndex: number } | null;
  setSelectedCell: (cell: { batchId: number; periodIndex: number } | null) => void;
  setErrorMsg: (msg: string | null) => void;
  handleAssignTeacher: (teacherId: number | null) => void;
  teachers: Teacher[];
}

export default function NotionGrid({
  density,
  setDensity,
  filterBoard,
  setFilterBoard,
  filterGrade,
  setFilterGrade,
  filteredBatches,
  currentSchedule,
  subjectsMap,
  teachersMap,
  availabilityMap,
  checkConstraints,
  selectedCell,
  setSelectedCell,
  setErrorMsg,
  handleAssignTeacher,
  teachers
}: NotionGridProps) {
  return (
    <div className="flex flex-col gap-6 select-none">
      {/* Density Controls & Stream Filters Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-sidebar border border-border-color p-3.5 rounded-lg select-none">
        <div className="flex flex-wrap items-center gap-4">
          {/* Stream Filter: Board */}
          <div className="flex items-center gap-2">
            <ListFilter className="w-3.5 h-3.5 text-secondary-text" />
            <span className="text-[11px] font-semibold uppercase text-secondary-text">Board</span>
            <select
              value={filterBoard}
              onChange={(e) => setFilterBoard(e.target.value as Board | "ALL")}
              className="bg-card-bg border border-border-color rounded px-2.5 py-1 text-xs text-primary-text font-medium focus:outline-none"
            >
              <option value="ALL">All Boards</option>
              <option value="SSC">SSC</option>
              <option value="ICSE">ICSE</option>
            </select>
          </div>

          {/* Stream Filter: Grade */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase text-secondary-text">Grade</span>
            <select
              value={filterGrade}
              onChange={(e) => setFilterGrade(e.target.value === "ALL" ? "ALL" : Number(e.target.value))}
              className="bg-card-bg border border-border-color rounded px-2.5 py-1 text-xs text-primary-text font-medium focus:outline-none"
            >
              <option value="ALL">All Grades</option>
              <option value="5">Grade 5</option>
              <option value="6">Grade 6</option>
              <option value="7">Grade 7</option>
              <option value="8">Grade 8</option>
              <option value="9">Grade 9</option>
              <option value="10">Grade 10</option>
            </select>
          </div>
        </div>

        {/* Density layout Toggler */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase text-secondary-text">Density</span>
          <div className="flex border border-border-color rounded overflow-hidden">
            <button
              onClick={() => setDensity("cozy")}
              className={`px-3 py-1 text-xs font-semibold cursor-pointer ${
                density === "cozy" ? "bg-accent-color text-white" : "bg-card-bg text-secondary-text hover:text-primary-text"
              }`}
            >
              Cozy
            </button>
            <button
              onClick={() => setDensity("compact")}
              className={`px-3 py-1 text-xs font-semibold cursor-pointer ${
                density === "compact" ? "bg-accent-color text-white" : "bg-card-bg text-secondary-text hover:text-primary-text"
              }`}
            >
              Compact
            </button>
          </div>
        </div>
      </div>

      {/* Notion style Resource-Timeline table grid */}
      <div className="bg-elevated border border-border-color rounded-lg overflow-hidden shadow-sm">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr className="bg-sidebar border-b border-border-color">
              <th className={`text-xs font-bold uppercase tracking-wider text-secondary-text border-r border-border-color w-48 ${
                density === "cozy" ? "p-4" : "p-2.5"
              }`}>Batch Stream</th>
              {[1, 2, 3, 4].map((pIdx) => (
                <th key={pIdx} className={`text-xs font-bold uppercase tracking-wider text-secondary-text border-r border-border-color last:border-r-0 ${
                  density === "cozy" ? "p-4" : "p-2.5"
                }`}>
                  Period {pIdx} <span className="text-muted-text font-semibold lowercase text-[10px] block">{15+pIdx}:00 - {16+pIdx}:00</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filteredBatches.length === 0 ? (
              <tr>
                <td colSpan={5} className="p-8 text-center text-xs text-muted-text">
                  No matching batch streams found. Adjust your filters or CRUD registries.
                </td>
              </tr>
            ) : (
              filteredBatches.map((batch) => (
                <tr key={batch.id} className="border-b border-divider-color last:border-b-0 hover:bg-card-bg/20 transition-colors duration-150">
                  <td className={`text-xs font-bold text-primary-text border-r border-border-color w-48 bg-sidebar/30 ${
                    density === "cozy" ? "p-4" : "p-2.5"
                  }`}>
                    {batch.name}
                    <span className="text-[10px] text-muted-text block uppercase font-medium">{batch.board} grade {batch.grade}</span>
                  </td>
                  
                  {[1, 2, 3, 4].map((pIdx) => {
                    const entry = currentSchedule?.entries.find(
                      e => e.batch_id === batch.id && e.period_index === pIdx
                    );
                    
                    const subject = entry ? subjectsMap.get(entry.subject_id) : null;
                    const teacher = entry && entry.teacher_id ? teachersMap.get(entry.teacher_id) : null;
                    const avail = teacher ? availabilityMap.get(teacher.id) : null;

                    // Run real-time client-side validator checks
                    const violations = entry && entry.teacher_id ? checkConstraints(entry, entry.teacher_id) : [];
                    const hasWarnings = violations.length > 0;

                    return (
                      <td 
                        key={pIdx} 
                        onClick={() => {
                          if (currentSchedule) {
                            setSelectedCell({ batchId: batch.id, periodIndex: pIdx });
                          } else {
                            setErrorMsg("Generate or load a schedule draft first.");
                          }
                        }}
                        className={`text-xs border-r border-border-color last:border-r-0 cursor-pointer hover:bg-card-bg/60 transition-all duration-100 group relative ${
                          density === "cozy" ? "p-4" : "p-2.5"
                        } ${hasWarnings ? "border-danger-color/40 bg-danger-color/5" : ""}`}
                      >
                        {entry ? (
                          <div className="flex flex-col gap-1.5">
                            <div className="flex justify-between items-center">
                              <span className="font-bold text-accent-color tracking-tight">{subject?.code || "SUB"}</span>
                              
                              {/* Alert Warnings Icon */}
                              {hasWarnings ? (
                                <AlertTriangle className="w-3.5 h-3.5 text-danger-color stroke-[2.2]" />
                              ) : (
                                <span className="text-[10px] font-semibold text-secondary-text">{subject?.name}</span>
                              )}
                            </div>
                            
                            <div className="flex items-center justify-between border border-border-color/30 bg-background/50 rounded px-1.5 py-0.5 w-full">
                              <div className="flex items-center gap-1.5 overflow-hidden">
                                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                  avail?.status === "AVAILABLE_ALL_DAY" ? "bg-success-color" :
                                  avail?.status === "PARTIAL" ? "bg-warning-color" : "bg-danger-color"
                                }`} />
                                <span className="font-semibold text-primary-text text-[11px] truncate">
                                  {teacher?.full_name || "Unassigned"}
                                </span>
                              </div>
                            </div>

                            {/* Real-time Constraint Warnings Tooltip Popover on Hover */}
                            {hasWarnings && (
                              <div className="absolute hidden group-hover:flex flex-col gap-1.5 z-40 bg-elevated border border-danger-color/30 p-3 rounded-lg shadow-lg w-64 -bottom-2 translate-y-full left-4 font-sans text-xs">
                                <div className="flex items-center gap-1.5 text-danger-color font-semibold">
                                  <AlertCircle className="w-4 h-4 stroke-[2]" />
                                  <span>Roster Constraint Failure</span>
                                </div>
                                <div className="flex flex-col gap-1 border-t border-divider-color/60 pt-1.5">
                                  {violations.map((v, i) => (
                                    <p key={i} className="text-secondary-text text-[11px] font-medium leading-relaxed">
                                      · {v}
                                    </p>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-[11px] text-muted-text italic group-hover:text-accent-color transition-colors duration-100 block py-1">
                            Click to assign
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Assignment popover picker */}
      {selectedCell && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/10 backdrop-blur-[1px]">
          <div className="bg-elevated border border-border-color w-96 p-6 rounded-lg shadow-lg flex flex-col gap-4">
            <div>
              <h4 className="text-xs font-semibold text-primary-text uppercase tracking-wider">Assign Instructor</h4>
              <p className="text-xs text-muted-text">
                Select a qualified teacher for Batch ID {selectedCell.batchId}, Period {selectedCell.periodIndex}
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <label className="text-[11px] font-medium text-secondary-text">Available Qualified Teachers</label>
              <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto">
                <button
                  onClick={() => handleAssignTeacher(null)}
                  className="w-full text-left text-xs font-bold border border-border-color border-dashed p-2 rounded hover:border-danger-color/60 hover:text-danger-color transition-all duration-150 cursor-pointer"
                >
                  Clear Assignment (Leave Unassigned)
                </button>
                
                {teachers.map((t) => {
                  const avail = availabilityMap.get(t.id);
                  return (
                    <button
                      key={t.id}
                      onClick={() => handleAssignTeacher(t.id)}
                      className="w-full text-left text-xs border border-border-color p-2 rounded hover:bg-card-bg hover:border-accent-color/60 transition-all duration-150 flex justify-between items-center cursor-pointer"
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-1.5 h-1.5 rounded-full ${
                          avail?.status === "AVAILABLE_ALL_DAY" ? "bg-success-color" :
                          avail?.status === "PARTIAL" ? "bg-warning-color" : "bg-danger-color"
                        }`} />
                        <span className="font-semibold text-primary-text">{t.full_name}</span>
                      </div>
                      <span className="text-[10px] text-muted-text uppercase font-semibold">{t.teacher_type}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setSelectedCell(null)}
                className="border border-border-color px-3.5 py-1.5 text-xs font-semibold rounded-md text-secondary-text hover:text-primary-text transition-colors duration-150 cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
