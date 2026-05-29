"use client";

import React from "react";
import { Users, FolderKanban, BookOpen, Plus, Trash2 } from "lucide-react";

type TeacherType = "FULL_TIME" | "PART_TIME";
type Board = "SSC" | "ICSE";
type SubjectDifficulty = "STANDARD" | "DIFFICULT";

interface Teacher {
  id: number;
  full_name: string;
  teacher_type: TeacherType;
  max_lectures_per_day: number;
  is_active: boolean;
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

interface MasterDataViewProps {
  newTeacher: Partial<Teacher>;
  setNewTeacher: (t: Partial<Teacher>) => void;
  handleAddTeacher: (e: React.FormEvent) => void;
  teachers: Teacher[];
  handleDeleteTeacher: (id: number) => void;
  newBatch: Partial<Batch>;
  setNewBatch: (b: Partial<Batch>) => void;
  handleAddBatch: (e: React.FormEvent) => void;
  batches: Batch[];
  handleDeleteBatch: (id: number) => void;
  newSubject: Partial<Subject>;
  setNewSubject: (s: Partial<Subject>) => void;
  handleAddSubject: (e: React.FormEvent) => void;
  subjects: Subject[];
  handleDeleteSubject: (id: number) => void;
}

export default function MasterDataView({
  newTeacher,
  setNewTeacher,
  handleAddTeacher,
  teachers,
  handleDeleteTeacher,
  newBatch,
  setNewBatch,
  handleAddBatch,
  batches,
  handleDeleteBatch,
  newSubject,
  setNewSubject,
  handleAddSubject,
  subjects,
  handleDeleteSubject
}: MasterDataViewProps) {
  return (
    <div className="flex flex-col gap-8 select-none">
      <div className="border-b border-divider-color pb-4">
        <h3 className="text-base font-semibold text-primary-text tracking-tight">Global Registry Management</h3>
        <p className="text-xs text-muted-text">Register instructors, batch classes, and curriculum subjects. Information is validated before syncing. Forms support `Cmd + Enter` quick submits.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* 1. TEACHERS CARD */}
        <div className="bg-elevated border border-border-color rounded-lg p-5 flex flex-col gap-4">
          <div className="border-b border-divider-color pb-3">
            <h4 className="text-xs font-semibold text-primary-text uppercase tracking-wider flex items-center gap-2">
              <Users className="w-4 h-4 text-accent-color stroke-[2]" />
              Active Instructors
            </h4>
          </div>

          {/* Creation Form */}
          <form onSubmit={handleAddTeacher} className="flex flex-col gap-3 border-b border-divider-color/60 pb-4">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold text-secondary-text">Full Name</label>
              <input
                type="text"
                placeholder="Instructor name..."
                value={newTeacher.full_name || ""}
                onChange={(e) => setNewTeacher({ ...newTeacher, full_name: e.target.value })}
                className="bg-background border border-border-color rounded px-2.5 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-secondary-text">Contract Type</label>
                <select
                  value={newTeacher.teacher_type || "PART_TIME"}
                  onChange={(e) => setNewTeacher({ ...newTeacher, teacher_type: e.target.value as TeacherType })}
                  className="bg-background border border-border-color rounded px-2 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                >
                  <option value="FULL_TIME">FULL TIME</option>
                  <option value="PART_TIME">PART TIME</option>
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-secondary-text">Max load/day</label>
                <input
                  type="number"
                  value={newTeacher.max_lectures_per_day || 3}
                  onChange={(e) => setNewTeacher({ ...newTeacher, max_lectures_per_day: Number(e.target.value) })}
                  className="bg-background border border-border-color rounded px-2.5 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                  min={1}
                />
              </div>
            </div>

            {/* Subject Expertise Checkboxes */}
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold text-secondary-text">Expertise Subjects (Qualifications)</label>
              {subjects.length === 0 ? (
                <span className="text-[10px] text-muted-text italic">No subjects registered yet. Create subjects first.</span>
              ) : (
                <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto border border-border-color/50 rounded p-1.5 bg-background/50">
                  {subjects.map((sub) => {
                    const isChecked = (newTeacher.subject_ids || []).includes(sub.id);
                    return (
                      <label key={sub.id} className="flex items-center gap-1.5 bg-card-bg border border-border-color px-2 py-0.5 rounded text-[10px] font-semibold text-secondary-text cursor-pointer hover:border-accent-color/60 transition-all">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => {
                            const currentIds = newTeacher.subject_ids || [];
                            const updatedIds = e.target.checked
                              ? [...currentIds, sub.id]
                              : currentIds.filter(id => id !== sub.id);
                            setNewTeacher({ ...newTeacher, subject_ids: updatedIds });
                          }}
                          className="w-3 h-3 text-accent-color"
                        />
                        {sub.code}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>

            <button
              type="submit"
              className="flex items-center justify-center gap-1.5 border border-border-color bg-card-bg text-secondary-text hover:text-primary-text py-1.5 text-xs font-semibold rounded-md hover:border-accent-color/60 transition-all duration-150 mt-1 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5 stroke-[2.2]" />
              Add Faculty
            </button>
          </form>

          {/* List */}
          <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
            {teachers.map((t) => (
              <div key={t.id} className="flex justify-between items-center border border-divider-color/60 p-2.5 rounded-md hover:border-accent-color/30 transition-colors">
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs font-bold text-primary-text">{t.full_name}</span>
                  <span className="text-[10px] text-muted-text uppercase font-semibold">
                    {t.teacher_type} · Max {t.max_lectures_per_day} classes
                  </span>
                  {t.subject_ids && t.subject_ids.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {t.subject_ids.map((sId) => {
                        const sub = subjects.find(s => s.id === sId);
                        if (!sub) return null;
                        return (
                          <span key={sId} className="bg-accent-color/10 border border-accent-color/20 text-accent-color text-[9px] font-bold px-1.5 py-0.2 rounded font-sans">
                            {sub.code}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
                
                <button
                  onClick={() => handleDeleteTeacher(t.id)}
                  className="text-muted-text hover:text-danger-color p-1 rounded hover:bg-background transition-colors cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5 stroke-[1.8]" />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* 2. BATCHES CARD */}
        <div className="bg-elevated border border-border-color rounded-lg p-5 flex flex-col gap-4">
          <div className="border-b border-divider-color pb-3">
            <h4 className="text-xs font-semibold text-primary-text uppercase tracking-wider flex items-center gap-2">
              <FolderKanban className="w-4 h-4 text-accent-color stroke-[2]" />
              Registered Grade Batches
            </h4>
          </div>

          {/* Creation Form */}
          <form onSubmit={handleAddBatch} className="flex flex-col gap-3 border-b border-divider-color/60 pb-4">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold text-secondary-text">Batch Stream Name</label>
              <input
                type="text"
                placeholder="e.g. Grade 10 ICSE..."
                value={newBatch.name || ""}
                onChange={(e) => setNewBatch({ ...newBatch, name: e.target.value })}
                className="bg-background border border-border-color rounded px-2.5 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                required
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-secondary-text">Board</label>
                <select
                  value={newBatch.board || "SSC"}
                  onChange={(e) => setNewBatch({ ...newBatch, board: e.target.value as Board })}
                  className="bg-background border border-border-color rounded px-2 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                >
                  <option value="SSC">SSC</option>
                  <option value="ICSE">ICSE</option>
                </select>
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-secondary-text">Grade Level</label>
                <input
                  type="number"
                  value={newBatch.grade || 8}
                  onChange={(e) => setNewBatch({ ...newBatch, grade: Number(e.target.value) })}
                  className="bg-background border border-border-color rounded px-2.5 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                  min={5}
                  max={10}
                />
              </div>
            </div>

            <button
              type="submit"
              className="flex items-center justify-center gap-1.5 border border-border-color bg-card-bg text-secondary-text hover:text-primary-text py-1.5 text-xs font-semibold rounded-md hover:border-accent-color/60 transition-all duration-150 mt-1 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5 stroke-[2.2]" />
              Add Batch Stream
            </button>
          </form>

          {/* List */}
          <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
            {batches.map((b) => (
              <div key={b.id} className="flex justify-between items-center border border-divider-color/60 p-2.5 rounded-md hover:border-accent-color/30 transition-colors">
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs font-bold text-primary-text">{b.name}</span>
                  <span className="text-[10px] text-muted-text uppercase font-semibold">
                    {b.board} Stream · Grade {b.grade}
                  </span>
                </div>
                
                <button
                  onClick={() => handleDeleteBatch(b.id)}
                  className="text-muted-text hover:text-danger-color p-1 rounded hover:bg-background transition-colors cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5 stroke-[1.8]" />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* 3. SUBJECTS CARD */}
        <div className="bg-elevated border border-border-color rounded-lg p-5 flex flex-col gap-4">
          <div className="border-b border-divider-color pb-3">
            <h4 className="text-xs font-semibold text-primary-text uppercase tracking-wider flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-accent-color stroke-[2]" />
              Curriculum Subjects
            </h4>
          </div>

          {/* Creation Form */}
          <form onSubmit={handleAddSubject} className="flex flex-col gap-3 border-b border-divider-color/60 pb-4">
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2 flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-secondary-text">Subject Name</label>
                <input
                  type="text"
                  placeholder="e.g. Science..."
                  value={newSubject.name || ""}
                  onChange={(e) => setNewSubject({ ...newSubject, name: e.target.value })}
                  className="bg-background border border-border-color rounded px-2.5 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                  required
                />
              </div>

              <div className="flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-secondary-text">Code</label>
                <input
                  type="text"
                  placeholder="SCI"
                  value={newSubject.code || ""}
                  onChange={(e) => setNewSubject({ ...newSubject, code: e.target.value })}
                  className="bg-background border border-border-color rounded px-2.5 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
                  required
                />
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-[11px] font-semibold text-secondary-text">Subject Pacing Purity</label>
              <select
                value={newSubject.difficulty || "STANDARD"}
                onChange={(e) => setNewSubject({ ...newSubject, difficulty: e.target.value as SubjectDifficulty })}
                className="bg-background border border-border-color rounded px-2 py-1.5 text-xs text-primary-text focus:outline-none focus:border-accent-color font-sans"
              >
                <option value="STANDARD">STANDARD PACING</option>
                <option value="DIFFICULT">DIFFICULT PACING</option>
              </select>
            </div>

            <button
              type="submit"
              className="flex items-center justify-center gap-1.5 border border-border-color bg-card-bg text-secondary-text hover:text-primary-text py-1.5 text-xs font-semibold rounded-md hover:border-accent-color/60 transition-all duration-150 mt-1 cursor-pointer"
            >
              <Plus className="w-3.5 h-3.5 stroke-[2.2]" />
              Register Subject
            </button>
          </form>

          {/* List */}
          <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
            {subjects.map((s) => (
              <div key={s.id} className="flex justify-between items-center border border-divider-color/60 p-2.5 rounded-md hover:border-accent-color/30 transition-colors">
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs font-bold text-primary-text">{s.name}</span>
                  <span className="text-[10px] text-muted-text uppercase font-semibold text-accent-color font-bold">
                    {s.code} · {s.difficulty}
                  </span>
                </div>
                
                <button
                  onClick={() => handleDeleteSubject(s.id)}
                  className="text-muted-text hover:text-danger-color p-1 rounded hover:bg-background transition-colors cursor-pointer"
                >
                  <Trash2 className="w-3.5 h-3.5 stroke-[1.8]" />
                </button>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
