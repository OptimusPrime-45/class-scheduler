# Tuition Scheduler — Canonical Data Model & Solver Contract

> **Status:** authoritative Phase-0 specification. Synthesized from three design proposals
> (normalized, solver-first, operations), reconciled against the full README (phases 0–4,
> pitfalls, testing cheatsheet), and hardened by an adversarial completeness pass (§4).
>
> An engineer can implement `app/models.py` and `app/schemas.py` directly from this with no
> further design work. Where the three proposals disagreed, a single decision is made and
> justified in §5.
>
> **Stack alignment:** SQLAlchemy 2.0 async (`Mapped[]` + `mapped_column`), Pydantic v2,
> Python 3.12, PostgreSQL (NeonDB), CP-SAT. `Base` is the existing
> `class Base(AsyncAttrs, DeclarativeBase)` in `app/db.py` — `models.py` imports it from
> there; do **not** redefine it.

---

## 0. Conventions (apply to every table)

| Convention | Decision | Why |
|---|---|---|
| Declarative base | Import `Base` from `app.db` (`AsyncAttrs, DeclarativeBase`). All models use `Mapped[]` + `mapped_column()`. | Engine/session already wired; one base. |
| Primary keys | `id: Mapped[int] = mapped_column(BigInteger, primary_key=True)` (Postgres `IDENTITY`) on every business table. Pure association tables use a composite PK instead. `institution_settings` is the one exception (SmallInteger singleton, see §1.1). | Single-host app; int FK joins in the hot loader path are cheaper than UUID. No UUIDs. |
| Audit mixin | `TimestampMixin` mixed into every business table: `created_at` and `updated_at`, both `DateTime(timezone=True)`, `server_default=func.now()`, `updated_at` also `onupdate=func.now()`. | Audit trail; deterministic. |
| **Timestamps = UTC** | Every `DateTime` column is `DateTime(timezone=True)` storing **UTC**. The only IST source for conversion is `institution_settings.timezone`. Conversion happens at the edges (API/bot/UI), never in the solver. The full UTC set is enumerated in §3. | README principle 5 ("UTC in, IST out"). |
| **Calendar dates = `Date`** | A timetable / availability is *for a day*: stored as `Date` (no tz), already resolved to the IST civil date by the caller. "Tomorrow" = IST-now + `target_offset_days`, computed once, then used as a naive date key. | A school day is a civil concept, not an instant. Keeps the debt week-boundary math in date space (avoids the UTC-mismatch trap, README Phase-2 pitfall). |
| **Wall-clock times = `Time`** | Period start/end, availability windows, preferred bands, subject preferred windows are `Time` **without timezone** = IST wall-clock-of-day. | The solver only compares same-day wall-clock overlap; `Asia/Kolkata` is fixed +05:30 (no DST). Converting to UTC adds zero information and reintroduces date rollover near midnight. See §3 B.0. |
| Enums | Native PostgreSQL enums: `mapped_column(SAEnum(PyEnum, name="<pg_name>", native_enum=True))`. Python side `enum.Enum` (str-valued; `Weekday` is `IntEnum`). | Stronger integrity than `VARCHAR+CHECK`, illegal values unstorable. Explicit `name=` → stable Alembic type names (see §5 risk on enum migration). |
| Soft delete | `is_active: bool` (default `True`) on master-data tables (subjects, teachers, batches, batch_slots, batch_subjects). No hard delete of master data. | Historical schedules keep referencing retired teachers/subjects. |
| FK delete policy | Master-data references that must not orphan: `RESTRICT`. Child rows owned by a parent (windows, entries): `CASCADE`. Soft references that may dangle (teacher on an entry / owner teacher): `SET NULL`. | Illegal-states-unrepresentable where cheap; graceful degradation where a teacher is deactivated. |
| Constraint naming | `MetaData(naming_convention=…)` with deterministic `ix/uq/ck/fk/pk` templates so Alembic autogenerate is stable. | Deterministic migrations. |
| Naming | Tables `snake_case` plural; enum types `snake_case` singular; ORM classes `PascalCase` singular. | Convention. |

---

## 1. Enum definitions

All native PG enums. `Board`, `TeacherType`, etc. are `str`-valued `enum.Enum`; `Weekday` is an
`IntEnum` (Mon=0) to align with Python `date.weekday()` so the loader's weekday match is a
comparison, not a lookup table.

| Python enum | PG type name | Members |
|---|---|---|
| `Board` | `board` | `SSC`, `ICSE` |
| `Weekday` | `weekday` | `MON=0, TUE=1, WED=2, THU=3, FRI=4, SAT=5, SUN=6` (`IntEnum`) |
| `TeacherType` | `teacher_type` | `FULL_TIME`, `PART_TIME` |
| `SubjectDifficulty` | `subject_difficulty` | `STANDARD`, `DIFFICULT` |
| `AvailabilityStatus` | `availability_status` | `AVAILABLE_ALL_DAY`, `PARTIAL`, `UNAVAILABLE` |
| `AvailabilitySource` | `availability_source` | `TELEGRAM`, `ADMIN`, `DEFAULT` |
| `SettingsScope` | `settings_scope` | `GLOBAL`, `BATCH` |
| `ScheduleStatus` | `schedule_status` | `DRAFT`, `APPROVED`, `PUBLISHED`, `ARCHIVED` |
| `SolverStatus` | `solver_status` | `OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `UNKNOWN`, `MODEL_INVALID`, `ERROR` |
| `EntryStatus` | `entry_status` | `PLANNED`, `CONDUCTED`, `CANCELLED` |
| `NotificationKind` | `notification_kind` | `POLL_OPEN`, `REMINDER`, `CUTOFF_DEFAULT`, `ASSIGNMENT`, `NO_ASSIGNMENT`, `SCHEDULE_PUBLISHED`, `ONBOARDING` |
| `NotificationStatus` | `notification_status` | `QUEUED`, `SENT`, `FAILED`, `SKIPPED_NO_CHAT` |
| `UserRole` | `user_role` | `ADMIN`, `MANAGER`, `VIEWER` |

**Decisions on enum disputes:**
- `EntryStatus` has **no `UNFILLED` member** (Proposal 3 added one; rejected). An unfilled cell is
  represented by `teacher_id IS NULL` (§2.11), orthogonal to lifecycle status. A cell can be
  *unfilled and planned*, or *unfilled and cancelled*; conflating them into one enum loses
  information. The debt query counts `status = CONDUCTED`; unfilled rows never have `CONDUCTED`
  unless an admin manually fills then conducts them. This is the cleaner, more expressive model.
- `ScheduleStatus` **keeps `ARCHIVED`** (from Proposal 3) to support re-generation via versioning
  (§2.10) without violating one-schedule-per-date-per-version or deleting history.
- `SolverStatus` **keeps `ERROR`** (Proposal 3) for an exception around the solve, distinct from
  CP-SAT's own `MODEL_INVALID`/`UNKNOWN`.
- `AvailabilitySource` is included (Proposal 3) for response provenance; values trimmed to the
  three that actually occur (`TELEGRAM`, `ADMIN`, `DEFAULT`).

---

## 2. Table-by-table schema

Tables in dependency order. `created_at`/`updated_at` (UTC, via `TimestampMixin`) are present on
every table below and are not repeated in each grid. "UTC" flags additional UTC instant columns.

### 2.1 `institution_settings` — global config + per-batch override

One `GLOBAL` singleton row plus zero-or-more `BATCH` override rows in the **same table**, keyed by
a `scope` discriminator + nullable `batch_id`. Effective setting for a batch = its `BATCH` row if
present, else the `GLOBAL` row (resolution lives in loader/jobs, not the DB). This makes the
multi-batch "earliest cutoff" a `min()` over each candidate batch's resolved `cutoff_time` (§4 / §5).

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `name` | `String(120)` | no | `'default'` | display label |
| `scope` | `SettingsScope` enum | no | `GLOBAL` | discriminator |
| `batch_id` | `BigInteger` FK→`batches.id` `ON DELETE CASCADE` | yes | NULL | NULL ⇔ `GLOBAL`; **unique** when not null (`uq_institution_settings_batch_id`) → ≤1 override per batch |
| `timezone` | `String(64)` | no | `'Asia/Kolkata'` | IANA tz; only meaningful on the `GLOBAL` row; the **only** UTC↔IST source |
| `week_start_day` | `Weekday` enum | no | `MON` | anchors the weekly-target / debt window (§4) |
| `poll_open_time` | `Time` (naive IST) | no | `19:00` | nightly poll opens |
| `reminder_offsets_minutes` | `ARRAY(SmallInteger)` | no | `[60, 120]` | minutes after poll open to nudge non-responders |
| `cutoff_time` | `Time` (naive IST) | no | `22:00` | after this, apply per-teacher defaults; per-batch override drives earliest-cutoff |
| `solve_time` | `Time` (naive IST) | yes | `22:15` | when the nightly solve fires |
| `target_offset_days` | `SmallInteger` | no | `1` | poll on day D targets D + offset (tomorrow) |
| `default_lecture_minutes` | `SmallInteger` | no | `60` | fallback slot duration (informational) |
| `solver_time_limit_seconds` | `Float` | no | `10.0` | passed into CP-SAT (matches `config.solver_time_limit_seconds`) |
| `is_active` | `Boolean` | no | `True` | |

**Constraints / indexes:**
- Partial unique index `uq_institution_settings_global` on `(scope)` WHERE `scope = 'GLOBAL'` →
  exactly one global row.
- `CheckConstraint("(scope = 'GLOBAL') = (batch_id IS NULL)", name="scope_batch")` →
  `GLOBAL` ⇔ no batch; `BATCH` ⇔ a batch.

**Relationship:** `batch` (→ `Batch.settings_override`, `uselist=False`).

> Per-batch override columns (`poll_open_time`, `reminder_offsets_minutes`, `cutoff_time`,
> `solve_time`) are non-null with defaults; a `BATCH` row is a full override of those scheduling
> fields. (`timezone`/`week_start_day` are conceptually global; a `BATCH` row carries them but the
> resolver only ever reads them from `GLOBAL`.)

### 2.2 `subjects` — teachable subjects (+ difficulty for the soft window term)

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `name` | `String(80)` | no | — | **unique** `uq_subjects_name` |
| `code` | `String(16)` | no | — | **unique** `uq_subjects_code` (e.g. `MATH`) |
| `difficulty` | `SubjectDifficulty` enum | no | `STANDARD` | drives "difficult-subject preferred window" soft term |
| `is_active` | `Boolean` | no | `True` | index `ix_subjects_is_active` |

**Relationships:** `qualifications` (M2M via `teacher_subjects`), `batch_subjects` (1-M),
`preferred_windows` (1-M → `subject_preferred_windows`).

> **Decision (preferred window modelling):** a *child table* `subject_preferred_windows`
> (Proposal 1), not two columns on `subjects` (Proposals 2/3). This allows multiple bands and an
> optional per-weekday band, and matches the `availability_windows` shape so the loader treats them
> uniformly. The contract flattens the *target-weekday-applicable* windows into a list (§3).

#### 2.2a `subject_preferred_windows`

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `subject_id` | `BigInteger` FK→`subjects.id` `ON DELETE CASCADE` | no | — | index |
| `weekday` | `Weekday` enum | yes | NULL | NULL = all days |
| `window_start` | `Time` (naive IST) | no | — | |
| `window_end` | `Time` (naive IST) | no | — | `CheckConstraint("window_end > window_start")` |

### 2.3 `batches` — a class group (grade + board)

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `name` | `String(80)` | no | — | **unique** `uq_batches_name` (e.g. "Grade 8 ICSE - A") |
| `grade` | `SmallInteger` | no | — | `CheckConstraint("grade BETWEEN 5 AND 10")` |
| `board` | `Board` enum | no | — | |
| `is_active` | `Boolean` | no | `True` | index; composite index `ix_batches_grade_board (grade, board)` |

**Relationships:** `slots` (1-M `batch_slots`), `batch_subjects` (1-M), `settings_override`
(1-0..1 `institution_settings`), `schedule_entries` (1-M).

### 2.4 `teachers` — faculty, Telegram identity, capacity, preferences

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `full_name` | `String(120)` | no | — | index |
| `phone` | `String(20)` | yes | NULL | |
| `email` | `String(254)` | yes | NULL | **unique** `uq_teachers_email` (partial, WHERE not null) |
| `teacher_type` | `TeacherType` enum | no | `PART_TIME` | drives default-at-cutoff behaviour; index |
| `telegram_chat_id` | `BigInteger` | yes | NULL | **unique** `uq_teachers_telegram_chat_id` (partial); NULL until `/start` links them — surfaces "never onboarded" |
| `telegram_username` | `String(64)` | yes | NULL | display only |
| `max_lectures_per_day` | `SmallInteger` | no | `6` | hard constraint cap; `CheckConstraint("max_lectures_per_day >= 0")` |
| `preferred_hours_start` | `Time` (naive IST) | yes | NULL | soft "preferred hours" band start |
| `preferred_hours_end` | `Time` (naive IST) | yes | NULL | band end; `CheckConstraint` end > start when both set |
| `is_active` | `Boolean` | no | `True` | index; inactive ⇒ excluded from polls/solve |
| `notes` | `Text` | yes | NULL | |

**Default/standard availability semantics.** *What the default is* lives in
`teacher_standard_availability` (§2.5): a FULL_TIME teacher's recurring weekly windows. A PART_TIME
teacher's default is *unavailable* = no rows (absence is the default). *Whether a given day's record
was auto-applied* is the `is_default` flag on the per-date `teacher_availability` row (§2.9). The
cutoff job materializes `teacher_availability(is_default=True)` rows from this template for
non-responding full-timers, and `UNAVAILABLE` rows for non-responding part-timers.

**Relationships:** `qualifications` (M2M via `teacher_subjects`), `standard_availability`
(1-M `teacher_standard_availability`), `availabilities` (1-M `teacher_availability`),
`owned_batch_subjects` (1-M `batch_subjects` as owner), `schedule_entries` (1-M),
`notifications` (1-M).

### 2.5 `teacher_standard_availability` — full-timer default weekly template

The recurring availability a FULL_TIME teacher falls back to at cutoff when they don't respond.
Kept separate from per-date availability so the solver never reads recurring rows — only the
materialized per-date rows (clean contract boundary).

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `teacher_id` | `BigInteger` FK→`teachers.id` `ON DELETE CASCADE` | no | — | composite index `ix_teacher_standard_availability_teacher_id_weekday (teacher_id, weekday)` |
| `weekday` | `Weekday` enum | no | — | recurring day |
| `window_start` | `Time` (naive IST) | no | — | |
| `window_end` | `Time` (naive IST) | no | — | `CheckConstraint("window_end > window_start")` |
| `is_active` | `Boolean` | no | `True` | |

### 2.6 `teacher_subjects` — M2M teacher ↔ subject qualification (association object)

Who may teach what (hard constraint: only qualified subjects). Explicit mapped class (not a bare
`Table`) because it carries `proficiency`; exposed via `relationship(secondary=...)` on both sides
**and** as a direct class for the loader to iterate.

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `teacher_id` | `BigInteger` FK→`teachers.id` `ON DELETE CASCADE` | no | — | part of composite PK |
| `subject_id` | `BigInteger` FK→`subjects.id` `ON DELETE CASCADE` | no | — | part of composite PK; index `ix_teacher_subjects_subject_id` (reverse lookup "who teaches X") |
| `proficiency` | `SmallInteger` | no | `3` | optional 1–5 future tie-breaker; `CheckConstraint("proficiency BETWEEN 1 AND 5")` |
| `created_at` | `DateTime(tz)` **UTC** | no | now | when qualified |

`PrimaryKeyConstraint(teacher_id, subject_id)` makes a duplicate qualification unrepresentable.

### 2.7 `batch_subjects` — per-(batch, subject) weekly target + owner/primary teacher

The unit of the debt computation **and** the carrier of the owner teacher the soft objective prefers.

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `batch_id` | `BigInteger` FK→`batches.id` `ON DELETE CASCADE` | no | — | part of **unique** `uq_batch_subjects_batch_id_subject_id`; index |
| `subject_id` | `BigInteger` FK→`subjects.id` `ON DELETE RESTRICT` | no | — | part of unique above |
| `weekly_target` | `SmallInteger` | no | — | lectures/week; `CheckConstraint("weekly_target >= 0")` |
| `owner_teacher_id` | `BigInteger` FK→`teachers.id` `ON DELETE SET NULL` | yes | NULL | owner/primary teacher → owner soft term; nullable so deleting a teacher doesn't break the curriculum row |
| `is_active` | `Boolean` | no | `True` | |

Unique `(batch_id, subject_id)` makes "a subject twice in one batch's curriculum" unrepresentable.
That the owner is actually qualified is a **validator** check (cross-row), not a DB CHECK (§5 risk).

**Relationships:** `batch`, `subject`, `owner_teacher` (→ `Teacher.owned_batch_subjects`).

### 2.8 `batch_slots` — the slot/period grid (per weekday, fixed durations)

One row = one period definition for a batch on a given weekday. Fixed `(start_time, end_time)`
guarantees fixed durations (README hard constraint); duration is implicit (end − start), not stored.

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | stable surrogate; echoed to/from the contract as `slot_id` |
| `batch_id` | `BigInteger` FK→`batches.id` `ON DELETE CASCADE` | no | — | composite index `ix_batch_slots_batch_id_weekday (batch_id, weekday)` (loader's "slots active on target weekday") |
| `weekday` | `Weekday` enum | no | — | which civil weekday this period is active |
| `period_index` | `SmallInteger` | no | — | 1-based ordinal within the day; `CheckConstraint("period_index >= 1")` |
| `start_time` | `Time` (naive IST) | no | — | wall-clock period start |
| `end_time` | `Time` (naive IST) | no | — | wall-clock period end; `CheckConstraint("end_time > start_time")` |
| `is_active` | `Boolean` | no | `True` | inactive ⇒ skipped that weekday |

**Unique** `uq_batch_slots_batch_id_weekday_period_index (batch_id, weekday, period_index)` — one
period index per batch per weekday.

> **Slot identity decision:** the contract uses the **stable surrogate `batch_slots.id`** as
> `slot_id` (Proposals 1/2), **not** the logical `(batch_id, period_index)` pair (Proposal 3). The
> persister maps a returned assignment straight back to a grid cell with no re-derivation; fixtures
> just use small integer ids. The slot also carries `batch_id` and `period_index` in the contract so
> the solver can reason about within-batch ordering (gap term) without a DB lookup.

### 2.9 `teacher_availability` — per teacher per date response header

One row per teacher per target date: status, whether it was a real reply or a cutoff default, and
when the teacher tapped.

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `teacher_id` | `BigInteger` FK→`teachers.id` `ON DELETE CASCADE` | no | — | part of unique below |
| `availability_date` | `Date` (IST civil date) | no | — | the day this availability is *for* (= target date); part of unique; composite index `ix_teacher_availability_date_status (availability_date, status)` |
| `status` | `AvailabilityStatus` enum | no | — | `AVAILABLE_ALL_DAY` / `PARTIAL` / `UNAVAILABLE` |
| `is_default` | `Boolean` | no | `False` | True ⇒ auto-applied at cutoff (not teacher-submitted); index |
| `responded_at` | `DateTime(tz)` **UTC** | yes | NULL | when the teacher tapped a poll option; NULL if never responded (reminder-stop signal; stays NULL when defaulted) |
| `source` | `AvailabilitySource` enum | no | `TELEGRAM` | provenance: TELEGRAM / ADMIN / DEFAULT |
| `source_chat_id` | `BigInteger` | yes | NULL | which chat the response came from (idempotency aid for Telegram retries) |
| `notes` | `Text` | yes | NULL | |

**Unique** `uq_teacher_availability_teacher_id_availability_date (teacher_id, availability_date)` —
exactly one record per teacher per day; poll re-taps **upsert** in place (idempotent handlers).

**`is_default` + `responded_at` interplay:** real reply ⇒ `is_default=False`,
`source=TELEGRAM`, `responded_at` set. Cutoff with no reply ⇒ `is_default=True`, `source=DEFAULT`,
`responded_at` stays NULL (distinguishes "assumed" from "answered"; reminders stop only when
`responded_at IS NOT NULL`).

**`status` ↔ windows coherence (validator-enforced, §5 risk):** `PARTIAL` ⇒ ≥1 window;
`AVAILABLE_ALL_DAY` and `UNAVAILABLE` ⇒ 0 windows. `UNAVAILABLE` teachers are omitted from the
`SolverInput` entirely (variable filtering at source).

**Relationships:** `teacher`, `windows` (1-M `availability_windows`, `cascade="all, delete-orphan"`).

### 2.10 `availability_windows` — concrete free ranges for a PARTIAL day

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `availability_id` | `BigInteger` FK→`teacher_availability.id` `ON DELETE CASCADE` | no | — | index |
| `window_start` | `Time` (naive IST) | no | — | wall-clock start |
| `window_end` | `Time` (naive IST) | no | — | wall-clock end; `CheckConstraint("window_end > window_start")` |

No `date` here — it lives on the parent. Multiple non-overlapping rows allowed (split availability).

> **`AVAILABLE_ALL_DAY` representation decision:** store **no** window rows for all-day (Proposals
> 1/2), rather than synthesizing a full-day window row in the DB (Proposal 3). The *loader* projects
> all-day into the contract as an empty window list, and the solver interprets an empty list as "the
> full civil day, contains every slot." This avoids a sentinel `[00:00, 23:59:59]` literal that
> mis-compares at boundaries and avoids persisting derived data. (See §3 B.0.)

### 2.11 `schedules` — per-date timetable header (lifecycle + solver metadata)

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `schedule_date` | `Date` (IST civil date) | no | — | part of **unique** `uq_schedules_date_version (schedule_date, version)`; index |
| `version` | `SmallInteger` | no | `1` | re-generation bumps version; prior → `ARCHIVED` |
| `status` | `ScheduleStatus` enum | no | `DRAFT` | `DRAFT → APPROVED → PUBLISHED`; superseded → `ARCHIVED`; index |
| `solver_status` | `SolverStatus` enum | no | `UNKNOWN` | mirrors `SolverResult.status` |
| `objective_value` | `Float` | yes | NULL | weighted objective; NULL when infeasible/error |
| `solve_time_ms` | `Integer` | yes | NULL | observability |
| `num_unfilled` | `SmallInteger` | no | `0` | denormalized for dashboards |
| `solver_seed` | `Integer` | yes | NULL | reproducibility |
| `contract_version` | `String(16)` | no | `'1'` | which `SolverInput` schema version produced this |
| `solver_input_snapshot` | `JSONB` | yes | NULL | the exact `SolverInput` used — audit/replay/version-migration |
| `input_size` | `JSONB` | yes | NULL | observability: #vars, #batches, #demands |
| `generated_at` | `DateTime(tz)` **UTC** | yes | NULL | when solve ran |
| `approved_at` | `DateTime(tz)` **UTC** | yes | NULL | lifecycle stamp |
| `approved_by_user_id` | `BigInteger` FK→`users.id` `ON DELETE SET NULL` | yes | NULL | who approved |
| `published_at` | `DateTime(tz)` **UTC** | yes | NULL | lifecycle stamp; triggers notifications |
| `published_by_user_id` | `BigInteger` FK→`users.id` `ON DELETE SET NULL` | yes | NULL | who published |
| `notes` | `Text` | yes | NULL | |

**Relationships:** `entries` (1-M `schedule_entries`, `cascade="all, delete-orphan"`),
`approved_by`, `published_by` (→ `users`).

> Lifecycle transitions (`DRAFT→APPROVED→PUBLISHED`; supersede→`ARCHIVED`) are forward-only,
> enforced in the service. Re-generation deletes+recreates entries within one transaction
> (Phase-2 transaction-safety pitfall), or creates a new `version` and archives the old.

### 2.12 `schedule_entries` — one grid cell: (batch, slot, subject, teacher?) + conducted/cancelled

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `schedule_id` | `BigInteger` FK→`schedules.id` `ON DELETE CASCADE` | no | — | part of unique below; index |
| `batch_id` | `BigInteger` FK→`batches.id` `ON DELETE RESTRICT` | no | — | denormalized for the debt query (validator: must equal `batch_slot.batch_id`) |
| `batch_slot_id` | `BigInteger` FK→`batch_slots.id` `ON DELETE SET NULL` | yes | — | the concrete grid cell (SET NULL: a slot may be deactivated/archived later) |
| `period_index` | `SmallInteger` | no | — | denormalized for stability if the slot row changes |
| `subject_id` | `BigInteger` FK→`subjects.id` `ON DELETE RESTRICT` | no | — | what's taught this cell |
| `teacher_id` | `BigInteger` FK→`teachers.id` `ON DELETE SET NULL` | **yes** | NULL | **NULL ⇒ unfilled slot** |
| `status` | `EntryStatus` enum | no | `PLANNED` | `PLANNED / CONDUCTED / CANCELLED`; debt counts only `CONDUCTED`; index |
| `is_locked` | `Boolean` | no | `False` | admin pinned this cell; re-solve must respect (Phase 4) |
| `start_time` | `Time` (naive IST) | no | — | **snapshot** of slot start (immutable vs later grid edits) |
| `end_time` | `Time` (naive IST) | no | — | snapshot of slot end |
| `cancelled_reason` | `Text` | yes | NULL | |
| `conducted_at` | `DateTime(tz)` **UTC** | yes | NULL | when marked conducted |

**Unique** `uq_schedule_entries_schedule_id_batch_slot_id (schedule_id, batch_slot_id)` — one entry
per grid cell per schedule. (Because `batch_slot_id` is nullable for archived slots, an additional
unique `(schedule_id, batch_id, period_index)` guards the "one subject+teacher per batch-period
cell" hard constraint even after a slot row is nulled.)

**Debt-query index:** `ix_schedule_entries_debt (batch_id, subject_id, status)`. Week-to-date debt:

```sql
SELECT se.batch_id, se.subject_id, COUNT(*) AS conducted
FROM schedule_entries se
JOIN schedules s ON s.id = se.schedule_id
WHERE se.status = 'CONDUCTED'
  AND s.status <> 'ARCHIVED'
  AND s.schedule_date >= :week_start_date   -- computed in IST from week_start_day
  AND s.schedule_date <  :target_date
GROUP BY se.batch_id, se.subject_id;
```

`remaining = max(0, weekly_target − conducted)`, clamped, computed in the loader. `CANCELLED` and
unfilled (NULL teacher) never count; `PLANNED` does not count until it becomes `CONDUCTED`. The
debt sums across all non-`ARCHIVED` schedule versions in the IST week (§4 / §5).

> **Decisions:** snapshot `start_time`/`end_time` + `period_index` onto the entry (Proposals 2/3) so
> a published timetable is immutable evidence regardless of later grid edits. `EntryStatus` is a
> first-class column (all three proposals), not inferred from `teacher_id`, because conducted ≠
> filled (a no-show is filled-but-cancelled).

### 2.13 `notification_log` — every send + every failure

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `teacher_id` | `BigInteger` FK→`teachers.id` `ON DELETE SET NULL` | yes | NULL | recipient (NULL for broadcast/admin); index `ix_notification_log_teacher_id` |
| `schedule_id` | `BigInteger` FK→`schedules.id` `ON DELETE SET NULL` | yes | NULL | context for assignment/publish msgs; index |
| `availability_id` | `BigInteger` FK→`teacher_availability.id` `ON DELETE SET NULL` | yes | NULL | context for poll/reminder/cutoff-default |
| `kind` | `NotificationKind` enum | no | — | POLL_OPEN / REMINDER / CUTOFF_DEFAULT / ASSIGNMENT / NO_ASSIGNMENT / SCHEDULE_PUBLISHED / ONBOARDING; composite index `ix_notification_log_kind_status (kind, status)` |
| `status` | `NotificationStatus` enum | no | `QUEUED` | QUEUED / SENT / FAILED / SKIPPED_NO_CHAT |
| `target_date` | `Date` | yes | NULL | which night this relates to; index |
| `telegram_chat_id` | `BigInteger` | yes | NULL | snapshot at send time |
| `telegram_message_id` | `BigInteger` | yes | NULL | returned id, for later edits |
| `payload` | `JSONB` | yes | NULL | rendered message / inline keyboard (audit) |
| `error_detail` | `Text` | yes | NULL | failure reason (blocked bot, rate limit) — failures recorded, not swallowed |
| `attempt` | `SmallInteger` | no | `1` | retry count |
| `dedupe_key` | `String(120)` | yes | NULL | **unique** `uq_notification_log_dedupe_key`; idempotency under Telegram retries (e.g. `"{kind}:{teacher_id}:{target_date}:{schedule_id}"`) |
| `sent_at` | `DateTime(tz)` **UTC** | yes | NULL | the instant |

> **Idempotency decision:** a **unique `dedupe_key`** (Proposal 3) over a service-only dedupe
> (Proposal 1). The key is derived per *logical* notification event, so legitimate re-sends (a second
> reminder offset) get distinct keys while a Telegram retry of the *same* event collides and is
> skipped. This makes "handlers must be idempotent" enforceable at the DB and prevents double-fired
> reminders across job replicas (cross-cutting: single active job instance).

### 2.14 `users` — web dashboard auth (Phase 4)

| Column | Type | Null | Default | Constraints / notes |
|---|---|---|---|---|
| `id` | `BigInteger` PK | no | identity | |
| `email` | `String(254)` | no | — | **unique** `uq_users_email` (store lowercased) |
| `hashed_password` | `String(255)` | no | — | argon2/bcrypt hash |
| `full_name` | `String(120)` | yes | NULL | |
| `role` | `UserRole` enum | no | `MANAGER` | ADMIN / MANAGER / VIEWER (RBAC) |
| `is_active` | `Boolean` | no | `True` | |
| `last_login_at` | `DateTime(tz)` **UTC** | yes | NULL | |

**Relationships:** `approved_schedules`, `published_schedules` (back-populated from `Schedule`).

### 2.15 Relationship map

```
InstitutionSettings 0..1 ── Batch                         (per-batch override; one GLOBAL singleton)
Subject       *──* Teacher        via TeacherSubject (assoc-object, +proficiency)
Subject       1──* SubjectPreferredWindow
Subject       1──* BatchSubject
Batch         1──* BatchSlot
Batch         1──* BatchSubject *──0..1 Teacher (owner)
Teacher       1──* TeacherStandardAvailability             (full-timer default template)
Teacher       1──* TeacherAvailability 1──* AvailabilityWindow
Schedule      1──* ScheduleEntry  (entry → Batch, BatchSlot?, Subject, Teacher?)
Schedule      *──0..1 User (approved_by / published_by)
NotificationLog *──0..1 {Teacher, Schedule, TeacherAvailability}
```

**Master data:** `institution_settings, subjects, subject_preferred_windows, teachers,
teacher_standard_availability, teacher_subjects, batches, batch_subjects, batch_slots`.
**Operational:** `teacher_availability, availability_windows, schedules, schedule_entries,
notification_log`. **Auth:** `users`.

---

## 3. Pydantic v2 contract — `SolverInput` / `SolverResult` (`app/schemas.py`)

**Zero SQLAlchemy imports.** Both Phase-1 fixtures and the Phase-2 loader construct identical
`SolverInput` objects; the solver imports only these. All models
`model_config = ConfigDict(frozen=True, extra="forbid")` (immutable, strict, hashable, cacheable).
Both top-level models carry `contract_version` (README principle 4).

### B.0 Time representation decision — **naive local (IST) `datetime.time`** (and why)

Windows, slot times, preferred hours, and subject preferred windows are all `datetime.time`,
**naive, IST wall-clock**. The single solve date is `SolverInput.target_date: datetime.date` (IST
civil date). **No timezone-bearing field reaches the solver.** Rationale:

1. The solver's only temporal operation is **interval overlap within one day** — containment
   (`window.start <= slot.start and slot.end <= window.end`) and wall-clock conflict
   (`a.start < b.end and b.start < a.end`). These are pure same-day `time` comparisons.
2. `Asia/Kolkata` is a fixed +05:30 offset with no DST, so wall-clock == what teachers/admins mean,
   unambiguously. Converting to UTC would shift evenings across the UTC date boundary and reintroduce
   the date-rollover trap for no benefit.
3. It mirrors the DB exactly (`batch_slots.start_time`, `availability_windows.window_start` are naive
   IST `Time`), so the loader is a pass-through and the Phase-1↔Phase-2 parity test is meaningful.
4. The only UTC values in the whole flow are *instants* (`responded_at`, `generated_at`, …), none of
   which enter `SolverInput`. This is "UTC in, IST out" at the right granularity: instants in UTC,
   calendar/wall-clock in local. The loader converts UTC-now → IST → `target_date` once.

`AVAILABLE_ALL_DAY` ⇒ empty `windows` list, interpreted by the solver as the full civil day.

### B.1 Leaf / shared models

```python
from datetime import date, time
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1"

class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

# Contract-local enums (str values; decoupled from ORM enums)
class CBoard(str, Enum):        SSC = "SSC"; ICSE = "ICSE"
class CTeacherType(str, Enum):  FULL_TIME = "FULL_TIME"; PART_TIME = "PART_TIME"
class CSolverStatus(str, Enum):
    OPTIMAL = "OPTIMAL"; FEASIBLE = "FEASIBLE"; INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"; MODEL_INVALID = "MODEL_INVALID"; ERROR = "ERROR"

class TimeWindow(_Frozen):
    start: time          # naive IST wall-clock
    end: time
    @model_validator(mode="after")
    def _check(self):
        if self.end <= self.start:
            raise ValueError("window end must be after start")
        return self

class BatchIn(_Frozen):
    id: int
    name: str
    grade: int
    board: CBoard

class SubjectIn(_Frozen):
    id: int
    code: str
    name: str
    is_difficult: bool = False
    preferred_windows: tuple[TimeWindow, ...] = ()   # subject_preferred_windows for the target weekday

class SlotIn(_Frozen):
    """One batch_slot active on the target weekday."""
    id: int                  # == batch_slots.id (stable slot/period identity)
    batch_id: int
    period_index: int        # 1-based; used by the gap soft term
    start: time              # naive IST
    end: time

class TeacherIn(_Frozen):
    """An AVAILABLE teacher for the target date (UNAVAILABLE teachers are omitted)."""
    id: int
    full_name: str
    teacher_type: CTeacherType
    max_lectures_per_day: int
    qualified_subject_ids: frozenset[int]            # from teacher_subjects
    windows: tuple[TimeWindow, ...]                  # resolved for the date; empty ⇒ all-day
    preferred_hours: TimeWindow | None = None        # soft preferred-hours band

class BatchSubjectDemand(_Frozen):
    """Per-(batch, subject) remaining weekly target + owner."""
    batch_id: int
    subject_id: int
    remaining_target: int        # max(0, weekly_target − week-to-date CONDUCTED)
    weekly_target: int           # carried for diagnostics / near-week-end hardening
    week_days_remaining: int     # days left until week_start_day boundary; "harden near end of week"
    owner_teacher_id: int | None = None
```

### B.2 Soft-constraint weights — maps 1:1 to the README's five soft terms (+ debt)

```python
class SolverWeights(_Frozen):
    fill_slot: int = 1000        # base reward for filling any slot (dominates softs)
    w_owner_teacher: int = 100   # prefer subject's owner/primary teacher (continuity, anti-substitution)
    w_preferred_hours: int = 30  # honour teacher preferred hours
    w_workload_balance: int = 40 # balance lecture load across teachers
    w_avoid_gaps: int = 25       # minimise idle gaps between a batch's lectures
    w_difficult_window: int = 50 # place DIFFICULT subjects in their preferred windows
    w_remaining_target: int = 60 # debt-weighted: prefer filling demands with higher remaining_target
```

> `weights.py` provides `DEFAULT_WEIGHTS = SolverWeights()`. Defaults are separated by order of
> magnitude (`fill_slot` ≫ soft band) so each can be tested in isolation (Phase-1 DoD: "test each
> soft term so they don't mask each other"). The debt term is a soft objective contribution, never a
> hard rule.

### B.3 `SolverInput` — the load-bearing input

```python
class SolverInput(_Frozen):
    contract_version: str = CONTRACT_VERSION
    target_date: date                 # IST civil day being scheduled (UTC never enters here)
    weekday: int                      # 0=Mon..6=Sun; validated == target_date.weekday()
    timezone: str = "Asia/Kolkata"    # informational; all times already local
    solver_time_limit_seconds: float = 10.0
    random_seed: int = 42             # determinism (README Phase-1 gate)
    num_workers: int = 1              # single worker in tests for determinism

    batches: tuple[BatchIn, ...]
    subjects: tuple[SubjectIn, ...]
    slots: tuple[SlotIn, ...]                  # only batch_slots active on target weekday
    teachers: tuple[TeacherIn, ...]            # only AVAILABLE teachers (+ resolved windows)
    demands: tuple[BatchSubjectDemand, ...]    # per-(batch,subject) remaining target + owner
    weights: SolverWeights = Field(default_factory=SolverWeights)
    locked_assignments: tuple["Assignment", ...] = ()   # admin-pinned cells a re-solve must keep

    @model_validator(mode="after")
    def _weekday_matches(self):
        if self.weekday != self.target_date.weekday():
            raise ValueError("weekday must equal target_date.weekday()")
        return self
```

- **Candidate decision** = `(batch_id, slot_id, subject_id, teacher_id)`; the solver creates a
  CP-SAT boolean only when the teacher is in `qualified_subject_ids`, the slot lies inside one of the
  teacher's `windows` (or `windows` is empty = all-day), and a matching demand exists — keeping the
  model small (README Phase-1 pitfall). `qualified_subject_ids` as `frozenset` makes the filter O(1).
- **Slot identity** is `SlotIn.id` (= `batch_slots.id`); returned verbatim so the persister maps each
  assignment to a grid cell with no re-derivation.
- Loader responsibilities: resolve `AVAILABLE_ALL_DAY` → empty `windows`; expand full-timer defaults;
  compute `remaining_target`, `weekly_target`, `week_days_remaining` (IST week boundary, §4).

### B.4 `SolverResult` — the load-bearing output

```python
class Assignment(_Frozen):
    batch_id: int
    slot_id: int            # == SlotIn.id / batch_slots.id
    subject_id: int
    teacher_id: int
    start: time
    end: time

class UnfilledSlot(_Frozen):
    batch_id: int
    slot_id: int
    subject_id: int | None = None    # the demand we wanted to place but couldn't
    reason: str | None = None        # e.g. "no qualified+available teacher" (aids the infeasible fixture)

class SolverResult(_Frozen):
    contract_version: str = CONTRACT_VERSION
    target_date: date
    status: CSolverStatus
    objective_value: float | None = None    # None when INFEASIBLE / UNKNOWN / ERROR
    assignments: tuple[Assignment, ...]
    unfilled_slots: tuple[UnfilledSlot, ...]
    solve_time_ms: int | None = None
    diagnostics: dict[str, int] = Field(default_factory=dict)  # {"num_booleans":.., "num_demands":..}
```

`SolverInput.model_rebuild()` resolves the forward ref to `Assignment` used in
`locked_assignments`. **Every slot in `SolverInput.slots` appears in exactly one of
`assignments`/`unfilled_slots`** — a total partition, so persistence is a clean upsert per cell.
The persister maps `assignments` → `schedule_entries` (teacher set), `unfilled_slots` →
`schedule_entries` with `teacher_id=NULL`, and writes `status`/`objective_value`/`solve_time_ms`/
`num_unfilled` onto the `schedules` row.

### B.5 Weights → soft-objective-term mapping (explicit)

| README soft term | Weight field | Source in `SolverInput` | Objective contribution (maximise) |
|---|---|---|---|
| (base) fill any slot | `fill_slot` | every candidate | `+fill_slot` per filled cell |
| Prefer owner/primary teacher | `w_owner_teacher` | `BatchSubjectDemand.owner_teacher_id` | `+w` when `teacher_id == owner_teacher_id` |
| Honour preferred hours | `w_preferred_hours` | `TeacherIn.preferred_hours` | `+w` when slot ⊆ preferred band |
| Balance workload | `w_workload_balance` | derived assignment counts | `−w · (max_load − min_load)` (or per-teacher deviation) |
| Avoid gaps | `w_avoid_gaps` | `SlotIn.period_index` per batch | `−w` per idle gap between consecutive filled periods in a batch |
| Difficult-subject windows | `w_difficult_window` | `SubjectIn.is_difficult` + `preferred_windows` | `+w` when a DIFFICULT subject's slot ⊆ a preferred window |
| Weekly target as debt (soft) | `w_remaining_target` | `BatchSubjectDemand.remaining_target` (+ `week_days_remaining` to harden late week) | `+w · remaining_target` per filled demand |

### B.6 Buildability parity (fixture P1 vs loader P2)

| `SolverInput` field | Fixture (P1) | Loader (P2) |
|---|---|---|
| `target_date`, `weekday` | literal | IST-now + `target_offset_days`; `.weekday()` |
| `batches` | literal | `batches WHERE is_active` |
| `slots` | literal | `batch_slots WHERE weekday=target AND is_active`, `selectinload(batch)` |
| `subjects` (+`preferred_windows`) | literal | `subjects WHERE is_active` + `subject_preferred_windows` for target weekday |
| `teachers` (+`windows`,`qualified_subject_ids`,`preferred_hours`) | literal | `teacher_availability WHERE date=target AND status != UNAVAILABLE`, `selectinload(windows)`, join `teacher_subjects`; ALL_DAY ⇒ `windows=()` |
| `demands.remaining_target` | literal | `batch_subjects.weekly_target − debt_query(batch,subject)`, clamped ≥0 |
| `demands.owner_teacher_id` | literal | `batch_subjects.owner_teacher_id` |
| `weights` | override or default | `weights.py` defaults (optionally tuned by `institution_settings`) |

No SQLAlchemy type leaks into the contract (loader does ORM→Pydantic projection) — satisfies README
principle 2 and the Phase-2 parity gate.

---

## 4. Completeness checklist (README feature → where it lives)

Every entity/field/behaviour mentioned across the README is mapped to a concrete table+column or
contract field. ✅ = covered; items flagged by the brief get explicit treatment.

### Phase 0 (foundations / contract)
| README item | Location |
|---|---|
| 6 batches | `batches` |
| 8 subjects | `subjects` |
| 20 teachers + qualifications | `teachers`, `teacher_subjects` |
| weekly targets | `batch_subjects.weekly_target` |
| slots | `batch_slots` |
| one institution-settings row | `institution_settings` GLOBAL singleton (partial unique index) |
| `SolverInput` (batches, slots-for-date, available teachers+windows, qualifications, per-(batch,subject) remaining target, weights) | `SolverInput.{batches, slots, teachers(+windows), teachers.qualified_subject_ids, demands.remaining_target, weights}` |
| `SolverResult` (assignments, unfilled slots, solver status, objective value) | `SolverResult.{assignments, unfilled_slots, status, objective_value}` |
| versioned contract | `contract_version` on both models; `schedules.contract_version` + `solver_input_snapshot` |

### Phase 1 (solver core)
| README item | Location |
|---|---|
| booleans only for possible (batch,period,subject,teacher) | contract pre-filters: `qualified_subject_ids`, resolved `windows`, `demands` (§3 B.3) |
| HARD: teacher not in two batches at same wall-clock time | validator (cross-row); inputs: `SlotIn.{start,end,batch_id}` |
| HARD: only qualified subjects | `TeacherIn.qualified_subject_ids` |
| HARD: only within available windows | `TeacherIn.windows` (empty = all-day) |
| HARD: max lectures/teacher/day | `TeacherIn.max_lectures_per_day` |
| HARD: one subject+teacher per batch-period cell | `schedule_entries` unique `(schedule_id, batch_slot_id)` + `(schedule_id, batch_id, period_index)`; solver: one bool true per slot |
| HARD: no overlapping lectures within a batch; fixed durations | `batch_slots` unique grid + `end_time > start_time` CHECK; validator overlap check |
| weekly target = debt-weighted objective, harden near week-end | `BatchSubjectDemand.{remaining_target, weekly_target, week_days_remaining}` + `w_remaining_target` |
| SOFT: prefer owner/primary teacher | `BatchSubjectDemand.owner_teacher_id` + `w_owner_teacher` |
| SOFT: honour preferred hours | `TeacherIn.preferred_hours` + `w_preferred_hours` |
| SOFT: balance workload | `w_workload_balance` |
| SOFT: avoid gaps | `SlotIn.period_index` + `w_avoid_gaps` |
| SOFT: difficult subjects in preferred windows | `SubjectIn.{is_difficult, preferred_windows}` + `w_difficult_window` |
| named tunable weights | `SolverWeights` / `weights.py` |
| infeasible → report + identify unfilled slots | `SolverResult.{status=INFEASIBLE, unfilled_slots(+reason)}` |
| determinism: fix seed, single worker | `SolverInput.{random_seed, num_workers}` |
| performance: solver time limit | `SolverInput.solver_time_limit_seconds` |

### Phase 2 (data/service/API)
| README item | Location |
|---|---|
| available teachers + windows | `teacher_availability` + `availability_windows` |
| batch_slots active on weekday | `batch_slots.weekday` + index |
| batch_subjects, qualifications | `batch_subjects`, `teacher_subjects` |
| **week-to-date conducted counts** | `schedule_entries.status = CONDUCTED` + debt index/query (§2.12) |
| remaining target = target − conducted | loader → `BatchSubjectDemand.remaining_target` |
| persist Schedule + entries; unfilled = null-teacher | `schedules`, `schedule_entries.teacher_id = NULL` |
| solver status + objective on schedule | `schedules.{solver_status, objective_value, solve_time_ms, num_unfilled}` |
| **debt query across week boundary, respect `week_start_day` in IST** | `institution_settings.week_start_day` + IST `schedule_date` (Date) keeps boundary in date space; query §2.12 |
| **mixed conducted/cancelled debt** | `EntryStatus.{CONDUCTED counts, CANCELLED ignored}` (no `UNFILLED` enum member; null teacher ignored) |
| transaction-safe load→solve→persist | service; entries `cascade` + versioning |
| eager loading (no N+1) | `selectinload` relationships defined throughout |
| APScheduler poll/reminder/cutoff per (per-batch OR global) windows | `institution_settings` scope discriminator (§2.1) |

### Phase 3 (Telegram bot)
| README item | Location |
|---|---|
| `/start` links `telegram_chat_id` | `teachers.telegram_chat_id` (unique, nullable) |
| poll: Available all day / Pick slots / Unavailable | `AvailabilityStatus.{AVAILABLE_ALL_DAY, PARTIAL, UNAVAILABLE}` |
| Pick slots writes AvailabilityWindow rows | `availability_windows` |
| each response writes/updates TeacherAvailability + stamps `responded_at` | `teacher_availability.{status, responded_at}` (upsert via unique) |
| reminders at configured offsets to non-responders | `institution_settings.reminder_offsets_minutes`; non-responder = `responded_at IS NULL` |
| **cutoff applies per-teacher default (`is_default=true`): full→standard, part→unavailable** | `teacher_availability.{is_default, source=DEFAULT}` from `teacher_standard_availability` (full) / `UNAVAILABLE` (part) |
| reminders stop once teacher responds | `responded_at IS NOT NULL` |
| publish → assigned teachers get schedule; unassigned get "no class tomorrow" | `NotificationKind.{ASSIGNMENT, NO_ASSIGNMENT}`; published trigger via `schedules.published_at` |
| log every send incl. failures | `notification_log.{status=FAILED, error_detail}` |
| **multi-batch: earliest cutoff among batches a teacher could be scheduled into** | per-batch `institution_settings.cutoff_time`; effective = `min()` over batches where teacher is qualified (via `teacher_subjects` ⋈ `batch_subjects`) AND demand exists (jobs layer; §5) |
| Telegram retries → idempotent handlers | `teacher_availability` upsert; `notification_log.dedupe_key` unique |
| blocked/never-onboarded surfaced | `telegram_chat_id IS NULL` → `NotificationStatus.SKIPPED_NO_CHAT` |
| reminder scheduling tz-sensitive (IST) | `institution_settings.timezone`; `Time` columns are IST |

### Phase 4 (web UI) & cross-cutting
| README item | Location |
|---|---|
| auth (login as a User) | `users` |
| RBAC roles | `users.role` (`UserRole`) |
| master-data CRUD incl. poll windows | all master tables + `institution_settings`(+BATCH overrides) |
| drag-drop calls validate endpoint; illegal moves rejected server-side | shared `validator.py`; `schedule_entries` constraints |
| review → approve → publish | `schedules.{status, approved_at, approved_by_user_id, published_at, published_by_user_id}` |
| publish triggers notifications | `schedules.published_at` → `notification_log` |
| dashboards: availability for the night | `teacher_availability` (index on date,status) |
| dashboards: weekly-target progress / syllabus completion | `batch_subjects.weekly_target` vs CONDUCTED debt query |
| pin a cell / re-generate respects it | `schedule_entries.is_locked` + `SolverInput.locked_assignments` |
| keep grid in sync after re-generation | `schedules.version` + `ARCHIVED`; entries snapshot times |
| observability: solver input size, status, objective, solve time | `schedules.{input_size, solver_status, objective_value, solve_time_ms}`; `SolverResult.diagnostics` |
| observability: bot sends/failures | `notification_log` |
| single active job instance (no double-fire) | `notification_log.dedupe_key` unique |

### Adversarially-flagged items (explicit resolutions)
| Flagged concern | Resolution |
|---|---|
| **UTC-vs-IST timestamps** | UTC `DateTime(tz)` only for instants (`created_at, updated_at, responded_at, generated_at, approved_at, published_at, conducted_at, sent_at, last_login_at`, `teacher_subjects.created_at`); `Date`/`Time` are IST civil/wall-clock; contract carries zero tz fields (§0, §3 B.0). |
| **week_start_day debt query** | `institution_settings.week_start_day` + IST `Date` keys; `:week_start_date` = most recent `week_start_day` on-or-before target; query in §2.12, sums non-`ARCHIVED` `CONDUCTED` across versions. |
| **is_default availability** | `teacher_availability.is_default` (daily flag) + `source=DEFAULT`; template in `teacher_standard_availability`; full→template, part→UNAVAILABLE (§2.4/2.9). |
| **owner/primary teacher (soft objective)** | `batch_subjects.owner_teacher_id` (SET NULL) → `BatchSubjectDemand.owner_teacher_id` + `w_owner_teacher`. |
| **unfilled-slot representation** | real `schedule_entries` row with `teacher_id = NULL` (grid always materialized); `SolverResult.unfilled_slots` (with reason); no `UNFILLED` enum member. |
| **conducted/cancelled status for debt** | `schedule_entries.status` (`EntryStatus`); only `CONDUCTED` counts; `CANCELLED`/null-teacher ignored. |
| **per-batch vs global poll windows** | single `institution_settings` table with `scope`+nullable `batch_id`; effective = BATCH else GLOBAL. |
| **multi-batch earliest-cutoff** | effective cutoff = `min(cutoff_time)` over each candidate batch's resolved settings; candidate = batches with demand the teacher is qualified for; computed in jobs layer. |

---

## 5. Design decisions & rationale (non-obvious) + open questions

### Decisions where the proposals disagreed
1. **Slot identity = surrogate `batch_slots.id`** (not `(batch_id, period_index)`). The persister maps
   assignments to cells with no re-derivation; fixtures use small ints. Logical `period_index` is
   *also* carried for the gap soft term.
2. **`EntryStatus` has no `UNFILLED` member.** Unfilled = `teacher_id IS NULL`, orthogonal to
   lifecycle. Preserves expressiveness (filled-but-cancelled vs unfilled) and a clean debt filter.
3. **Subject preferred windows = child table** (`subject_preferred_windows`), not two columns —
   supports multiple/per-weekday bands and matches the availability-window shape.
4. **All-day availability = empty window list** in the contract (no DB sentinel row), interpreted by
   the solver as the full day; avoids boundary mis-compares and persisting derived data.
5. **`schedules.version` + `ARCHIVED`** for re-generation; preserves history and one-per-date-version.
6. **`notification_log.dedupe_key` unique** for idempotency (DB-enforced) over service-only dedupe;
   distinct keys per logical event allow legitimate re-sends, identical keys block retries.
7. **Snapshot `start_time`/`end_time`/`period_index` onto `schedule_entries`** so a published
   timetable is immutable evidence independent of later grid edits.

### Non-obvious rationale (carried from the proposals)
- **Three-way time split** (`Date` civil / `Time` IST wall-clock / `DateTime(tz)` UTC instant) is the
  literal encoding of "UTC in, IST out"; UTC never reaches the solver, making tz bugs structurally
  hard.
- **Per-batch settings as a `scope` discriminator on one table** (not two tables) keeps the schema
  flat and makes earliest-cutoff a `min()` over resolved rows.
- **PG native enums** for integrity; `Weekday` as `IntEnum` Mon=0 aligns with `date.weekday()`.
- **Association *object* `teacher_subjects`** carries `proficiency` and grows cleanly while still
  exposing `secondary` relationships for ergonomic eager loading.
- **`solver_input_snapshot` (JSONB) + `contract_version`** enable replay/diff and safe version
  migration (principle 4).
- **Frozen, `extra="forbid"` contract models** are hashable/cacheable and reject drift.

### Cross-row invariants delegated to `validator.py` (one validator, two callers)
Not DB-enforceable cleanly; live in the shared validator and are exercised by the Phase-1 hard
battery: (a) teacher double-booking across batches at the same wall-clock time; (b) within-batch slot
overlap; (c) `batch_subjects.owner_teacher_id` is actually qualified for the subject;
(d) `teacher_availability.status` ↔ window-count coherence; (e) `schedule_entries.batch_id ==
batch_slot.batch_id`. **Risk:** a raw SQL write bypassing services could create an invalid state —
mitigate by routing all writes through services + a periodic integrity check.

### Residual open questions (need user input or a Phase-1 decision)
1. **Who flips `PLANNED → CONDUCTED`?** Admin UI action, a daily job, or assumed-conducted after the
   fact? This directly drives debt accuracy and is unspecified by the README. **Needs user input.**
2. **Weekly-target hardening policy.** The contract carries `weekly_target` + `week_days_remaining` so
   the solver *can* harden near week-end, but *which* day and *how hard* (and whether it can ever
   become a hard constraint) is unspecified. Keep soft for now; decide at Phase-1 optimisation tests.
3. **All-day window upper bound for difficult-subject/preferred-hours scoring.** With all-day = empty
   list, any soft term that needs an explicit span (none currently do) would need a policy bound
   (institution open/close). Confirm no soft term requires it.
4. **Multi-batch earliest-cutoff scope** = per-teacher (chosen), computed over batches with demand the
   teacher is qualified for. Confirm it is per-teacher, not per-(teacher, batch). **Needs user
   confirmation.**
5. **`objective_value` is only comparable within a single solve** (weights/slot counts vary across
   days). Dashboards must not trend it. Documented, not enforced.
6. **Locked cells during re-solve** — confirm the solver treats `locked_assignments` as fixed
   booleans (=1), not soft. Decide at Phase 1.
7. **Co-owned subjects.** `owner_teacher_id` is single-valued (README's singular "owner/primary").
   If co-owners are needed, promote to a small association table.
8. **Rooms/capacity.** No room entity (README never mentions room conflicts). First addition if
   physical rooms become scarce: a `rooms` table + a hard no-two-batches-per-room constraint.
9. **Alembic enum migration (Phase-0 pitfall).** The 12 native PG enums need explicit `CREATE TYPE`
   ordering in migration `0001`; adding values later needs `ALTER TYPE ... ADD VALUE` (non-txn).
   Plan a manual review of the first autogenerated migration. **Implementation note, not a blocker.**
```
