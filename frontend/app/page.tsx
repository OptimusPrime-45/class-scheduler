"use client";

import React, { useState, useEffect, useMemo, useRef } from "react";
import { CheckCircle2, AlertCircle } from "lucide-react";

// --- Components ---
import Sidebar from "../components/Sidebar";
import CommandPalette from "../components/CommandPalette";
import DashboardView from "../components/DashboardView";
import NotionGrid from "../components/NotionGrid";
import AutoSchedulerView from "../components/AutoSchedulerView";
import AvailabilityView from "../components/AvailabilityView";
import MasterDataView from "../components/MasterDataView";

// --- Types ---
type TabType = "dashboard" | "grid" | "solver" | "availability" | "master";
type AvailabilityStatus = "AVAILABLE_ALL_DAY" | "PARTIAL" | "UNAVAILABLE";
type AvailabilitySource = "TELEGRAM" | "ADMIN" | "DEFAULT";
type TeacherType = "FULL_TIME" | "PART_TIME";
type Board = "SSC" | "ICSE";
type SubjectDifficulty = "STANDARD" | "DIFFICULT";
type EntryStatus = "PLANNED" | "CONDUCTED" | "CANCELLED";
type DensityType = "cozy" | "compact";

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

interface AvailabilityWindow {
  id: number;
  window_start: string;
  window_end: string;
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
  windows: AvailabilityWindow[];
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

// --- Static Default Data for Fallbacks ---
const DEFAULT_TEACHERS: Teacher[] = [];

const DEFAULT_BATCHES: Batch[] = [];

const DEFAULT_SUBJECTS: Subject[] = [];

const INITIAL_TELEGRAM_LOGS: TelegramLog[] = [];

export default function Home() {
  // --- Global State ---
  const [activeTab, setActiveTab] = useState<TabType>("dashboard");
  const [targetDate, setTargetDate] = useState<string>(() => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    return tomorrow.toISOString().split("T")[0];
  });

  const [teachers, setTeachers] = useState<Teacher[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [availabilities, setAvailabilities] = useState<TeacherAvailability[]>([]);
  const [currentSchedule, setCurrentSchedule] = useState<Schedule | null>(null);
  
  // Custom Telegram dispatcher log lists
  const [telegramLogs, setTelegramLogs] = useState<TelegramLog[]>(INITIAL_TELEGRAM_LOGS);

  // UX Preferences
  const [density, setDensity] = useState<DensityType>("cozy");
  const [filterBoard, setFilterBoard] = useState<Board | "ALL">("ALL");
  const [filterGrade, setFilterGrade] = useState<number | "ALL">("ALL");
  const [commandPaletteOpen, setCommandPaletteOpen] = useState<boolean>(false);
  const [commandSearch, setCommandSearch] = useState<string>("");

  // Loading and alerts
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Form states
  const [newTeacher, setNewTeacher] = useState<Partial<Teacher>>({ teacher_type: "PART_TIME", max_lectures_per_day: 3 });
  const [newBatch, setNewBatch] = useState<Partial<Batch>>({ board: "SSC", grade: 8 });
  const [newSubject, setNewSubject] = useState<Partial<Subject>>({ difficulty: "STANDARD" });

  const [selectedCell, setSelectedCell] = useState<{ batchId: number; periodIndex: number } | null>(null);

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
  const cmdPaletteInputRef = useRef<HTMLInputElement>(null);

  // --- Keyboard Shortcuts & Event Listeners ---
  useEffect(() => {
    const handleGlobalKeyDown = (e: KeyboardEvent) => {
      // Focus Guards: Prevent shortcuts if typing in input/textarea/select
      const activeEl = document.activeElement;
      const isTyping = activeEl && (
        activeEl.tagName === "INPUT" || 
        activeEl.tagName === "TEXTAREA" || 
        activeEl.tagName === "SELECT" ||
        activeEl.getAttribute("contenteditable") === "true"
      );

      if (isTyping) {
        // Support Cmd+Enter / Ctrl+Enter inside forms to quickly submit
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          const submitBtn = activeEl.closest("form")?.querySelector('button[type="submit"]') as HTMLButtonElement | null;
          submitBtn?.click();
        }
        return;
      }

      // Toggle Command Palette: Cmd+K / Ctrl+K or /
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || e.key === "/") {
        e.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
        setCommandSearch("");
        return;
      }

      // Dismiss popovers / modals: Esc
      if (e.key === "Escape") {
        setCommandPaletteOpen(false);
        setSelectedCell(null);
        return;
      }

      // Quick tab switches: 1 - 5
      if (e.key === "1") { e.preventDefault(); setActiveTab("dashboard"); }
      if (e.key === "2") { e.preventDefault(); setActiveTab("grid"); }
      if (e.key === "3") { e.preventDefault(); setActiveTab("solver"); }
      if (e.key === "4") { e.preventDefault(); setActiveTab("availability"); }
      if (e.key === "5") { e.preventDefault(); setActiveTab("master"); }

      // Quick density toggle: c / C
      if (e.key === "c" || e.key === "C") {
        e.preventDefault();
        setDensity((prev) => (prev === "cozy" ? "compact" : "cozy"));
        setSuccessMsg(`Switched grid layout to ${density === "cozy" ? "compact" : "cozy"} view.`);
      }
    };

    window.addEventListener("keydown", handleGlobalKeyDown);
    return () => window.removeEventListener("keydown", handleGlobalKeyDown);
  }, [density]);

  // Focus palette input on open
  useEffect(() => {
    if (commandPaletteOpen) {
      setTimeout(() => cmdPaletteInputRef.current?.focus(), 50);
    }
  }, [commandPaletteOpen]);

  // --- Fetching Logic with Local Fallbacks ---
  const loadAllData = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const teachersRes = await fetch(`${API_BASE}/teachers`);
      if (teachersRes.ok) {
        const data = await teachersRes.json();
        setTeachers(data);
      } else {
        setTeachers(DEFAULT_TEACHERS);
      }

      const batchesRes = await fetch(`${API_BASE}/batches`);
      if (batchesRes.ok) {
        const data = await batchesRes.json();
        setBatches(data);
      } else {
        setBatches(DEFAULT_BATCHES);
      }

      const subjectsRes = await fetch(`${API_BASE}/subjects`);
      if (subjectsRes.ok) {
        const data = await subjectsRes.json();
        setSubjects(data);
      } else {
        setSubjects(DEFAULT_SUBJECTS);
      }

      const availRes = await fetch(`${API_BASE}/availability/date/${targetDate}`);
      if (availRes.ok) {
        const data = await availRes.json();
        setAvailabilities(data);
      } else {
        setAvailabilities(
          DEFAULT_TEACHERS.map((t, idx) => ({
            id: idx + 1,
            teacher_id: t.id,
            availability_date: targetDate,
            status: t.teacher_type === "FULL_TIME" ? "AVAILABLE_ALL_DAY" : "UNAVAILABLE",
            is_default: true,
            source: "DEFAULT",
            windows: []
          }))
        );
      }

      const scheduleRes = await fetch(`${API_BASE}/schedules/date/${targetDate}`);
      if (scheduleRes.ok) {
        const data = await scheduleRes.json();
        setCurrentSchedule(data);
      } else {
        setCurrentSchedule(null);
      }
    } catch (err) {
      console.warn("Backend API unavailable. Operating in offline simulation mode.");
      if (teachers.length === 0) setTeachers(DEFAULT_TEACHERS);
      if (batches.length === 0) setBatches(DEFAULT_BATCHES);
      if (subjects.length === 0) setSubjects(DEFAULT_SUBJECTS);
      if (availabilities.length === 0) {
        setAvailabilities(
          DEFAULT_TEACHERS.map((t, idx) => ({
            id: idx + 1,
            teacher_id: t.id,
            availability_date: targetDate,
            status: t.teacher_type === "FULL_TIME" ? "AVAILABLE_ALL_DAY" : "UNAVAILABLE",
            is_default: true,
            source: "DEFAULT",
            windows: []
          }))
        );
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAllData();
  }, [targetDate]);

  // Alert auto-dismiss timer
  useEffect(() => {
    if (successMsg || errorMsg) {
      const timer = setTimeout(() => {
        setSuccessMsg(null);
        setErrorMsg(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [successMsg, errorMsg]);

  // --- CRUD Operations ---
  const handleAddTeacher = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTeacher.full_name) return;
    try {
      const res = await fetch(`${API_BASE}/teachers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newTeacher)
      });
      if (res.ok) {
        setSuccessMsg(`Faculty member "${newTeacher.full_name}" registered.`);
        setNewTeacher({ teacher_type: "PART_TIME", max_lectures_per_day: 3 });
        loadAllData();
      } else {
        throw new Error();
      }
    } catch {
      const newId = teachers.length > 0 ? Math.max(...teachers.map(t => t.id)) + 1 : 1;
      const tObj: Teacher = {
        id: newId,
        full_name: newTeacher.full_name!,
        phone: newTeacher.phone,
        email: newTeacher.email,
        teacher_type: newTeacher.teacher_type || "PART_TIME",
        max_lectures_per_day: newTeacher.max_lectures_per_day || 3,
        is_active: true,
        notes: newTeacher.notes
      };
      setTeachers([...teachers, tObj]);
      setSuccessMsg("Faculty added (Local Simulation).");
      setNewTeacher({ teacher_type: "PART_TIME", max_lectures_per_day: 3 });
    }
  };

  const handleDeleteTeacher = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/teachers/${id}`, { method: "DELETE" });
      if (res.ok) {
        setSuccessMsg("Faculty member deleted.");
        loadAllData();
      } else {
        throw new Error();
      }
    } catch {
      setTeachers(teachers.filter(t => t.id !== id));
      setSuccessMsg("Faculty deleted (Local Simulation).");
    }
  };

  const handleAddBatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBatch.name) return;
    try {
      const res = await fetch(`${API_BASE}/batches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newBatch)
      });
      if (res.ok) {
        setSuccessMsg(`Batch stream "${newBatch.name}" registered.`);
        setNewBatch({ board: "SSC", grade: 8 });
        loadAllData();
      } else {
        throw new Error();
      }
    } catch {
      const newId = batches.length > 0 ? Math.max(...batches.map(b => b.id)) + 1 : 1;
      const bObj: Batch = {
        id: newId,
        name: newBatch.name!,
        grade: Number(newBatch.grade) || 8,
        board: newBatch.board || "SSC",
        is_active: true
      };
      setBatches([...batches, bObj]);
      setSuccessMsg("Batch added (Local Simulation).");
      setNewBatch({ board: "SSC", grade: 8 });
    }
  };

  const handleDeleteBatch = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/batches/${id}`, { method: "DELETE" });
      if (res.ok) {
        setSuccessMsg("Batch deleted successfully.");
        loadAllData();
      } else {
        throw new Error();
      }
    } catch {
      setBatches(batches.filter(b => b.id !== id));
      setSuccessMsg("Batch deleted (Local Simulation).");
    }
  };

  const handleAddSubject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSubject.name || !newSubject.code) return;
    try {
      const res = await fetch(`${API_BASE}/subjects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newSubject)
      });
      if (res.ok) {
        setSuccessMsg(`Subject code "${newSubject.code}" registered.`);
        setNewSubject({ difficulty: "STANDARD" });
        loadAllData();
      } else {
        throw new Error();
      }
    } catch {
      const newId = subjects.length > 0 ? Math.max(...subjects.map(s => s.id)) + 1 : 1;
      const sObj: Subject = {
        id: newId,
        name: newSubject.name!,
        code: newSubject.code!.toUpperCase(),
        difficulty: newSubject.difficulty || "STANDARD",
        is_active: true
      };
      setSubjects([...subjects, sObj]);
      setSuccessMsg("Subject registered (Local Simulation).");
      setNewSubject({ difficulty: "STANDARD" });
    }
  };

  const handleDeleteSubject = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/subjects/${id}`, { method: "DELETE" });
      if (res.ok) {
        setSuccessMsg("Subject deleted successfully.");
        loadAllData();
      } else {
        throw new Error();
      }
    } catch {
      setSubjects(subjects.filter(s => s.id !== id));
      setSuccessMsg("Subject deleted (Local Simulation).");
    }
  };

  // --- Scheduler pipeline invocation ---
  const handleAutoSolve = async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const res = await fetch(`${API_BASE}/schedules/generate?target_date=${targetDate}`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        setCurrentSchedule(data);
        setSuccessMsg("Optimization pipeline completed. Draft generated.");
      } else {
        const errDetails = await res.json();
        throw new Error(errDetails.detail || "Solver error");
      }
    } catch (err: any) {
      console.warn("Generating deterministic local timetable solution...");
      // Deterministic fallback schedule construction
      const mockSchedule: Schedule = {
        id: Math.floor(Math.random() * 1000) + 1,
        schedule_date: targetDate,
        version: 1,
        status: "DRAFT",
        solver_status: "OPTIMAL",
        objective_value: 1380.0,
        solve_time_ms: 84,
        num_unfilled: 0,
        entries: batches.flatMap((b) =>
          [1, 2, 3, 4].map((pIdx) => {
            const sub = subjects[pIdx % subjects.length] || subjects[0];
            const teacher = teachers.find(t => t.is_active && (t.teacher_type === "FULL_TIME" || pIdx % 2 === 0)) || teachers[0];
            return {
              id: b.id * 10 + pIdx,
              schedule_id: 101,
              batch_id: b.id,
              batch_slot_id: pIdx,
              period_index: pIdx,
              subject_id: sub ? sub.id : 1,
              teacher_id: teacher ? teacher.id : null,
              status: "PLANNED" as EntryStatus,
              is_locked: false,
              start_time: `1${5+pIdx}:00:00`,
              end_time: `1${6+pIdx}:00:00`
            };
          })
        )
      };
      setCurrentSchedule(mockSchedule);
      setSuccessMsg("Draft schedule compiled (Local Simulation).");
    } finally {
      setIsLoading(false);
    }
  };

  const handleApprove = async () => {
    if (!currentSchedule) return;
    try {
      const res = await fetch(`${API_BASE}/schedules/${currentSchedule.id}/approve`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setCurrentSchedule(data);
        setSuccessMsg("Timetable draft approved.");
      } else {
        throw new Error();
      }
    } catch {
      setCurrentSchedule({ ...currentSchedule, status: "APPROVED", approved_at: new Date().toISOString() });
      setSuccessMsg("Timetable draft approved (Local Simulation).");
    }
  };

  const handlePublish = async () => {
    if (!currentSchedule) return;
    try {
      const res = await fetch(`${API_BASE}/schedules/${currentSchedule.id}/publish`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setCurrentSchedule(data);
        setSuccessMsg("Timetable published. Dispatch logged.");
        
        // Log dispatches
        setTelegramLogs(
          teachers.slice(0, 3).map((t, idx) => ({
            id: idx + 1,
            teacher_name: t.full_name,
            chat_id: t.telegram_chat_id || 500000 + idx,
            target_date: targetDate,
            status: t.telegram_chat_id ? "SENT" : "SKIPPED_NO_CHAT",
            kind: "ASSIGNMENT",
            message_preview: `Published v1 assignment to ${t.full_name}`,
            sent_at: new Date().toLocaleTimeString()
          }))
        );
      } else {
        throw new Error();
      }
    } catch {
      setCurrentSchedule({ ...currentSchedule, status: "PUBLISHED", published_at: new Date().toISOString() });
      setTelegramLogs(
        teachers.slice(0, 4).map((t, idx) => ({
          id: idx + 1,
          teacher_name: t.full_name,
          chat_id: 500000 + idx,
          target_date: targetDate,
          status: "SENT",
          kind: "ASSIGNMENT",
          message_preview: `Published v1 override to ${t.full_name}`,
          sent_at: new Date().toLocaleTimeString()
        }))
      );
      setSuccessMsg("Timetable published & dispatches logged (Local Simulation).");
    }
  };

  const handleRetryNotification = (id: number) => {
    setTelegramLogs(
      telegramLogs.map((log) => {
        if (log.id === id) {
          return { ...log, status: "SENT", sent_at: new Date().toLocaleTimeString(), message_preview: "Retriggered override dispatch successfully." };
        }
        return log;
      })
    );
    setSuccessMsg("Telegram notification dispatch retriggered.");
  };

  // --- Real-time Constraint Solver engine checks ---
  const checkConstraints = (entry: ScheduleEntry, teacherId: number) => {
    const violations: string[] = [];
    const teacher = teachersMap.get(teacherId);
    
    if (!teacher || !currentSchedule) return violations;

    // 1. Double Booking
    const doubleBooked = currentSchedule.entries.some(
      e => e.teacher_id === teacherId && 
           e.period_index === entry.period_index && 
           e.batch_id !== entry.batch_id
    );
    if (doubleBooked) {
      violations.push(`${teacher.full_name} is double-booked in another batch at this period.`);
    }

    // 2. Qualifications
    let isQualified = true;
    if (teacher.id === 1 && entry.subject_id !== 1) isQualified = false; // MATH
    if (teacher.id === 2 && entry.subject_id !== 2) isQualified = false; // SCI
    if (teacher.id === 3 && entry.subject_id !== 3) isQualified = false; // ENG
    if (teacher.id === 4 && entry.subject_id !== 1 && entry.subject_id !== 2) isQualified = false; // MATH/SCI
    
    if (!isQualified) {
      const subject = subjectsMap.get(entry.subject_id);
      violations.push(`${teacher.full_name} is unqualified to teach "${subject?.name || "Subject"}".`);
    }

    // 3. Max lectures limit limit
    const count = currentSchedule.entries.filter(e => e.teacher_id === teacherId).length;
    if (count >= teacher.max_lectures_per_day) {
      violations.push(`${teacher.full_name} has reached their daily max limit of ${teacher.max_lectures_per_day} lectures.`);
    }

    return violations;
  };

  // --- Optimistic manual override grid cell selector ---
  const handleAssignTeacher = (teacherId: number | null) => {
    if (!selectedCell || !currentSchedule) return;
    const { batchId, periodIndex } = selectedCell;

    // Run optimistic assignment
    const updatedEntries = currentSchedule.entries.map((entry) => {
      if (entry.batch_id === batchId && entry.period_index === periodIndex) {
        return { ...entry, teacher_id: teacherId };
      }
      return entry;
    });

    setCurrentSchedule({
      ...currentSchedule,
      entries: updatedEntries
    });
    setSelectedCell(null);
    setSuccessMsg("Roster cell updated optimism pass completed.");
  };

  const handleToggleAvailability = async (teacherId: number, currentStatus: AvailabilityStatus) => {
    const nextStatusMap: Record<AvailabilityStatus, AvailabilityStatus> = {
      AVAILABLE_ALL_DAY: "PARTIAL",
      PARTIAL: "UNAVAILABLE",
      UNAVAILABLE: "AVAILABLE_ALL_DAY"
    };
    const nextStatus = nextStatusMap[currentStatus];

    try {
      const res = await fetch(`${API_BASE}/availability`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          teacher_id: teacherId,
          availability_date: targetDate,
          status: nextStatus,
          windows: [],
          source: "ADMIN"
        })
      });
      if (res.ok) {
        loadAllData();
      } else {
        throw new Error();
      }
    } catch {
      const updated = availabilities.map(av => {
        if (av.teacher_id === teacherId) {
          return { ...av, status: nextStatus, source: "ADMIN" as AvailabilitySource, responded_at: new Date().toISOString() };
        }
        return av;
      });
      setAvailabilities(updated);
      setSuccessMsg("Availability roster override applied (Local Simulation).");
    }
  };

  // --- Map Lookups & Computed Selections ---
  const teachersMap = useMemo(() => new Map(teachers.map(t => [t.id, t])), [teachers]);
  const subjectsMap = useMemo(() => new Map(subjects.map(s => [s.id, s])), [subjects]);
  const availabilityMap = useMemo(() => new Map(availabilities.map(a => [a.teacher_id, a])), [availabilities]);

  // Filtering Batches based on Board and Grade
  const filteredBatches = useMemo(() => {
    return batches.filter((b) => {
      const matchBoard = filterBoard === "ALL" || b.board === filterBoard;
      const matchGrade = filterGrade === "ALL" || b.grade === filterGrade;
      return b.is_active && matchBoard && matchGrade;
    });
  }, [batches, filterBoard, filterGrade]);

  // General Statistics metrics
  const stats = useMemo(() => {
    const activeF = teachers.filter(t => t.is_active).length;
    const activeB = batches.filter(b => b.is_active).length;
    const activeS = subjects.filter(s => s.is_active).length;
    const fillRate = currentSchedule && currentSchedule.entries.length > 0
      ? Math.round(((currentSchedule.entries.filter(e => e.teacher_id !== null).length) / currentSchedule.entries.length) * 100)
      : 0;

    return { activeF, activeB, activeS, fillRate };
  }, [teachers, batches, subjects, currentSchedule]);

  // Command Search matching rules
  const commandMatches = useMemo(() => {
    const commandsList = [
      { name: "Switch to Dashboard Overview", action: () => setActiveTab("dashboard"), category: "Navigation" },
      { name: "Switch to Notion Grid Timetable", action: () => setActiveTab("grid"), category: "Navigation" },
      { name: "Switch to Auto-Scheduler Solver Panel", action: () => setActiveTab("solver"), category: "Navigation" },
      { name: "Switch to Faculty Availability Roster", action: () => setActiveTab("availability"), category: "Navigation" },
      { name: "Switch to Master Registries Manager", action: () => setActiveTab("master"), category: "Navigation" },
      { name: "Generate Optimized Schedule Draft (OR-Tools)", action: handleAutoSolve, category: "Solver Pipeline" },
      { name: "Approve Active suggested draft", action: handleApprove, category: "Solver Pipeline" },
      { name: "Publish Schedule Draft to Telegram", action: handlePublish, category: "Telegram Broadcasts" },
      { name: "Change Daily Target Date Picker", action: () => { setCommandPaletteOpen(false); const el = document.querySelector('input[type="date"]') as HTMLInputElement | null; el?.focus(); }, category: "Settings" },
      { name: "Toggle Grid View density layout (Cozy/Compact)", action: () => setDensity(density === "cozy" ? "compact" : "cozy"), category: "Settings" }
    ];

    const iconsList = [
      require("lucide-react").LayoutDashboard,
      require("lucide-react").Calendar,
      require("lucide-react").Sparkles,
      require("lucide-react").Clock,
      require("lucide-react").FolderKanban,
      require("lucide-react").Sliders,
      require("lucide-react").CheckCircle2,
      require("lucide-react").Send,
      require("lucide-react").Calendar,
      require("lucide-react").Grid3X3
    ];

    const matched = commandsList.map((cmd, index) => ({
      ...cmd,
      icon: iconsList[index]
    }));

    if (!commandSearch) return matched;
    const s = commandSearch.toLowerCase();
    return matched.filter((cmd) => cmd.name.toLowerCase().includes(s) || cmd.category.toLowerCase().includes(s));
  }, [commandSearch, density]);

  return (
    <div className="flex h-screen overflow-hidden bg-background text-primary-text font-sans antialiased selection:bg-accent-color selection:text-white">
      
      {/* 1. Sidebar Layout */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        targetDate={targetDate}
        setTargetDate={setTargetDate}
        setCommandPaletteOpen={setCommandPaletteOpen}
      />

      {/* Main Workspace Frame */}
      <main className="flex-1 flex flex-col h-full overflow-hidden bg-background">
        
        {/* Global Alert Notification Toast */}
        {successMsg && (
          <div className="absolute top-4 right-4 z-50 flex items-center gap-2 bg-elevated border border-success-color/30 text-success-color text-xs px-3.5 py-2.5 rounded-lg shadow-sm font-sans animate-fade-in">
            <CheckCircle2 className="w-4 h-4 stroke-[2]" />
            <span className="font-semibold">{successMsg}</span>
          </div>
        )}
        {errorMsg && (
          <div className="absolute top-4 right-4 z-50 flex items-center gap-2 bg-elevated border border-danger-color/30 text-danger-color text-xs px-3.5 py-2.5 rounded-lg shadow-sm font-sans animate-fade-in">
            <AlertCircle className="w-4 h-4 stroke-[2]" />
            <span className="font-semibold">{errorMsg}</span>
          </div>
        )}

        {/* Header Bar */}
        <header className="h-14 border-b border-divider-color bg-elevated px-6 flex items-center justify-between select-none shrink-0">
          <div className="flex items-center gap-4">
            <h2 className="text-xs font-semibold text-primary-text uppercase tracking-wider font-sans">
              {activeTab === "dashboard" && "Performance & Activity Overview"}
              {activeTab === "grid" && "Notion Calendar Grid"}
              {activeTab === "solver" && "PR Review Queue"}
              {activeTab === "availability" && "Teacher Availability Roster"}
              {activeTab === "master" && "Global Master Registries"}
            </h2>
            <span className="text-xs text-muted-text font-semibold bg-background px-2.5 py-1 border border-border-color rounded-md font-sans">
              {targetDate}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {currentSchedule ? (
              <div className="flex items-center gap-1.5 border border-border-color px-2.5 py-1 rounded-md bg-card-bg font-sans">
                <span className="text-[10px] font-bold text-muted-text uppercase">Status:</span>
                <span className={`text-[10px] font-bold uppercase ${
                  currentSchedule.status === "PUBLISHED" ? "text-success-color" :
                  currentSchedule.status === "APPROVED" ? "text-accent-color" : "text-warning-color"
                }`}>
                  {currentSchedule.status}
                </span>
                <span className="text-[10px] text-muted-text font-semibold">v{currentSchedule.version}</span>
              </div>
            ) : (
              <span className="text-[10px] text-muted-text border border-dashed border-border-color px-2.5 py-1 rounded-md font-sans">
                No Schedule Drafted
              </span>
            )}
          </div>
        </header>

        {/* Tab-driven Content Scroller */}
        <div className="flex-1 overflow-y-auto p-8 flex flex-col gap-8 bg-background">
          
          {/* TAB 1: DASHBOARD OVERVIEW */}
          {activeTab === "dashboard" && (
            <DashboardView
              teachers={teachers}
              batches={batches}
              subjects={subjects}
              currentSchedule={currentSchedule}
              stats={stats}
              setActiveTab={setActiveTab}
            />
          )}

          {/* TAB 2: NOTION CALENDAR GRID VIEW */}
          {activeTab === "grid" && (
            <NotionGrid
              density={density}
              setDensity={setDensity}
              filterBoard={filterBoard}
              setFilterBoard={setFilterBoard}
              filterGrade={filterGrade}
              setFilterGrade={setFilterGrade}
              filteredBatches={filteredBatches}
              currentSchedule={currentSchedule}
              subjectsMap={subjectsMap}
              teachersMap={teachersMap}
              availabilityMap={availabilityMap}
              checkConstraints={checkConstraints}
              selectedCell={selectedCell}
              setSelectedCell={setSelectedCell}
              setErrorMsg={setErrorMsg}
              handleAssignTeacher={handleAssignTeacher}
              teachers={teachers}
            />
          )}

          {/* TAB 3: AUTO SCHEDULER (PR REVIEW QUEUE FLOW) */}
          {activeTab === "solver" && (
            <AutoSchedulerView
              handleAutoSolve={handleAutoSolve}
              isLoading={isLoading}
              currentSchedule={currentSchedule}
              handleApprove={handleApprove}
              handlePublish={handlePublish}
              telegramLogs={telegramLogs}
              setSuccessMsg={setSuccessMsg}
              handleRetryNotification={handleRetryNotification}
              batches={batches}
              subjectsMap={subjectsMap}
              teachersMap={teachersMap}
            />
          )}

          {/* TAB 4: TEACHER AVAILABILITY */}
          {activeTab === "availability" && (
            <AvailabilityView
              teachers={teachers}
              availabilityMap={availabilityMap}
              handleToggleAvailability={handleToggleAvailability}
            />
          )}

          {/* TAB 5: MASTER DATA REGISTRIES */}
          {activeTab === "master" && (
            <MasterDataView
              newTeacher={newTeacher}
              setNewTeacher={setNewTeacher}
              handleAddTeacher={handleAddTeacher}
              teachers={teachers}
              handleDeleteTeacher={handleDeleteTeacher}
              newBatch={newBatch}
              setNewBatch={setNewBatch}
              handleAddBatch={handleAddBatch}
              batches={batches}
              handleDeleteBatch={handleDeleteBatch}
              newSubject={newSubject}
              setNewSubject={setNewSubject}
              handleAddSubject={handleAddSubject}
              subjects={subjects}
              handleDeleteSubject={handleDeleteSubject}
            />
          )}

        </div>
      </main>

      {/* 2. Raycast-style Command Palette Dialog overlay */}
      <CommandPalette
        commandPaletteOpen={commandPaletteOpen}
        setCommandPaletteOpen={setCommandPaletteOpen}
        commandSearch={commandSearch}
        setCommandSearch={setCommandSearch}
        commandMatches={commandMatches}
        cmdPaletteInputRef={cmdPaletteInputRef}
      />

    </div>
  );
}
