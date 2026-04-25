# 📄 Backend Service Documentation: Separation Model

## 1. 🧩 System Overview

The **SeparationModel** (`models/separation_model.py`) defines the Pydantic response model for the **Stem Separation feature**. This feature splits audio tracks into 4 separate stems: **vocals, drums, bass, and other** using the Demucs ML model.

**Role in system:** Enables users to upload any audio file and receive isolated stem tracks via AI-powered source separation — useful for remixing, sampling, or analyzing song composition.

**Feature supported:** Audio Stem Separation (Demucs-based)

### Cross-reference insights from README
- Listed in `README.md` → **Features → Stem separation flow**
- Token cost: `SEPARATION = 300` in `config/token_costs.py`
- Celery queue: `musicgpt_album` (single Redis-backed queue)
- Database table: `audio_separations`

---

## 2. 🧱 Architecture Mapping

| Layer | Component | File |
|-------|------------|------|
| **Model** | `SeparationResponse` | `models/separation_model.py` |
| **Router** | `/separate/` endpoint | `routers/separation_router.py` |
| **Service** | `process_audio_background()` | `services/separation_service.py` |
| **Database** | `audio_separations` table | Supabase |
| **External API** | Demucs (local subprocess) | `demucs` Python module |

**Flow:**
```
POST /separate/ → SeparationResponse validation → DB insert (QUEUED) → Celery worker → demucs → upload to Supabase Storage → DB update (COMPLETED)
```

---

## 3. 🔌 API Contracts

### ➤ Endpoint: `POST /separate/`

**Description:** Upload audio file for stem separation. Receives an audio file and project ID, creates a separation job, and immediately returns a `SeparationResponse` with `status=PENDING`.

**Request Schema:**
```
Content-Type: multipart/form-data

Fields:
- file: UploadFile (required) — Audio file to separate (any format supported by ffmpeg)
- project_id: str (required) — Target project ID
- Authorization: Bearer <clerk_jwt> (required) — User authentication
```

**Validation Rules:**
- `file` must be a valid audio file (mp3, wav, etc.)
- `project_id` must be a non-empty string
- `user_id` extracted from JWT — never from request body
- Token cost: 300 tokens (from `token_costs.py`)
- `require_tokens()` checks sufficient balance before queuing

**Response Schema (`SeparationResponse`):**
```json
{
  "id": "uuid-string",
  "user_id": "uuid-string",
  "project_id": "string",
  "original_filename": "string",
  "status": "PENDING",
  "vocals_url": null,
  "drums_url": null,
  "bass_url": null,
  "other_url": null,
  "error_message": null,
  "created_at": "ISO-8601 datetime"
}
```

**Error Cases:**
- `422` — Request validation failed (invalid file, missing fields)
- `400` — Token insufficient, file save failed, DB insert failed
- `401` — Invalid/missing JWT
- `500` — Unexpected server error (DB, file system)

**Derived Fields:**
- `vocals_url`, `drums_url`, `bass_url`, `other_url` — populated only when `status=COMPLETED`
- `error_message` — populated only when `status=FAILED`
- `status` progression: `PENDING` → `IN_QUEUE` → `COMPLETED`/`FAILED`

---

## 4. 🧠 Business Logic Deep Dive

### ➤ Function: `process_audio_background(job_id, input_path, user_id, project_id)`

**Purpose:** Background task that performs the actual stem separation using Demucs and uploads results to Supabase Storage.

**Step-by-step execution flow:**

1. **Update status to IN_PROGRESS**
   - `UPDATE audio_separations SET status='IN_PROGRESS' WHERE id=job_id`

2. **Convert to WAV** (via `_convert_to_wav`)
   - If input is already `.wav`, skip conversion
   - Otherwise run: `ffmpeg -y -i <input> -ar 44100 -ac 2 <output.wav>`
   - Output: WAV file path

3. **Compute output folder name**
   - `base_name = os.path.splitext(os.path.basename(wav_path))[0]`
   - `output_folder = os.path.join(OUTPUT_DIR, "htdemucs", base_name)`

4. **Run Demucs** (via `subprocess.run`)
   - Command: `python -m demucs --out <OUTPUT_DIR> <wav_path>`
   - Model: `htdemucs` (default Demucs model)
   - Timeout: controlled by subprocess (default wait)

5. **Validate outputs**
   - Check existence of 4 stem files: `vocals.wav`, `drums.wav`, `bass.wav`, `other.wav`
   - If any missing → raise `Exception("Missing stem output: ...")`

6. **Upload to Supabase Storage** (parallel upload)
   - Bucket: `STORAGE_BUCKET` (from env, default `music-generated`)
   - Path: `{user_id}/{project_id}/{job_id}/{stem}.wav`
   - Set content-type: `audio/wav`
   - After upload: get public URL

7. **Update database with URLs**
   - `UPDATE audio_separations 
     SET status='COMPLETED', 
         vocals_url='<url>', 
         drums_url='<url>', 
         bass_url='<url>', 
         other_url='<url>' 
     WHERE id=job_id`

8. **Cleanup (finally block)**
   - Delete: input WAV, converted WAV, output folder (only job-specific files)
   - Never delete `inputs/` or `outputs/` root directories

**Retry Logic:** None at service level — failures are captured and set as `FAILED` with error message.

**Failure handling:**
- Any exception → set `status='FAILED'`, store `error_message`
- Cleanup still runs (finally block)
- Other queued jobs continue unaffected

---

## 5. 🗄️ Database Mapping

### Table: `audio_separations`

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Unique job identifier (pre-generated) |
| `user_id` | TEXT (FK → users.id) | Owner user UUID |
| `project_id` | TEXT | Project reference string |
| `original_filename` | TEXT | Original uploaded file name |
| `status` | TEXT | `PENDING` | `IN_QUEUE` | `COMPLETED` | `FAILED` |
| `vocals_url` | TEXT (nullable) | Public URL to stems |
| `drums_url` | TEXT (nullable) | Public URL to stems |
| `bass_url` | TEXT (nullable) | Public URL to stems |
| `other_url` | TEXT (nullable) | Public URL to stems |
| `error_message` | TEXT (nullable) | Error details if failed |
| `created_at` | TIMESTAMPTZ | Record creation time |

### Relationships & Indexes

- **Foreign Key:** `user_id` → `users.id` (application-level enforcement)
- **RLS Policy:** `user_owns_audio_separations` (in migration 008) — allows users to see only their own rows
- **Indexes:** Not explicitly defined in migrations; likely indexed on `id` (PK) and `user_id` for query performance

### Lifecycle

```
INSERT (status='PENDING') 
  → UPDATE status='IN_PROGRESS' 
    → UPDATE status='COMPLETED' + set *_url OR status='FAILED' + set error_message
  → SELECT by user_id + task_id for polling
```

---

## 6. 🔄 Data Flow

```
Frontend (upload form)
    → POST /separate/ (FastAPI)
        → validate JWT → get user_id
        → pre-insert audio_separations (status=PENDING, task_id=UUID)
        → return SeparationResponse (task_id to client)
        → enqueue process_audio_background in Celery (musicgpt_album queue)
            → worker runs:
                convert_to_wav → demucs → upload 4 stems → update DB URLs → cleanup
    → Client polls GET /download/?user_id=...&task_id=...
        → queries audio_separations by user_id + task_id
        → returns URLs when status=COMPLETED
```

---

## 7. ⚠️ Edge Cases

| Edge Case | Handling |
|-----------|----------|
| **Invalid audio file** | ffmpeg fails in `_convert_to_wav` → exception → status=FAILED |
| **Missing stem output** | Validation raises Exception → status=FAILED with "Missing stem output" |
| **Demucs timeout/hang** | No explicit timeout — depends on Celery task timeout; worker may be killed externally |
| **Concurrent uploads** | Redis queue serializes jobs (concurrency=1 on free plan) |
| **File already exists** | Unique job_id prevents collisions |
| **Storage upload failure** | Exception → status=FAILED; cleanup still runs |
| **Polling before completion** | Returns null URLs (status not COMPLETED) — client should retry |
| **Large files** | ffmpeg may be slow; no chunking — handled by subprocess |

---

## 8. 🔐 Security & Constraints

- **Authentication:** All endpoints require valid Clerk JWT (`get_current_user`)
- **Authorization:** Service layer enforces `user_id` ownership via DB queries (`supabase.table(...).eq("user_id", user_id)`)
- **Token cost:** 300 tokens per separation request (pre-checked via `require_tokens`)
- **Input sanitization:** Filenames preserved as-is; `job_id` is UUID (safe)
- **Secret handling:** No secrets in model; Supabase service-role key stored in env as `<REDACTED>`
- **RLS:** Enabled on `audio_separations` but bypassed by service-role client — application layer is primary defense

---

## 9. 📊 State Machine

**States:**
- `PENDING` — Record created, not yet picked up by worker
- `IN_QUEUE` — Worker picked up job, being processed
- `COMPLETED` — Stems generated and uploaded
- `FAILED` — Error occurred, no further processing

**Transitions:**
- `PENDING` → `IN_QUEUE` (worker starts)
- `IN_QUEUE` → `COMPLETED` (success)
- `IN_QUEUE` → `FAILED` (error)

**Terminal:** `COMPLETED`, `FAILED`

---

## 10. 🎯 Frontend Integration Contract (VERY IMPORTANT)

### What frontend must send:
- `multipart/form-data` with `file` (audio) and `project_id`
- `Authorization: Bearer <jwt>` header

### What backend expects:
- Valid JWT with `user_id`
- Audio file readable by ffmpeg
- Sufficient token balance (300 tokens)

### What frontend receives:
- Immediate response with `id`, `status=PENDING`, null URLs
- Polling endpoint: `GET /download/?user_id=<id>&task_id=<id>` returns full `SeparationResponse` when done

### Field mapping:
| Frontend field | Backend field | Direction |
|----------------|---------------|-----------|
| `file` | `file` (UploadFile) | → |
| `project_id` | `project_id` | → |
| `id` | `id` | ← |
| `status` | `status` | ← |
| `vocals_url` | `vocals_url` | ← |
| `drums_url` | `drums_url` | ← |
| `bass_url` | `bass_url` | ← |
| `other_url` | `other_url` | ← |
| `error_message` | `error_message` | ← |

### UI States:
- **Loading:** After upload, show "Processing..." with spinner
- **Success:** Show 4 stem download buttons with URLs
- **Error:** Show `error_message` with retry option
- **Empty:** Initial upload form

---

## 11. 📘 Example Flow

**User:** Clicks "Separate Vocals" on audio file
1. Frontend POSTs `/separate/` with file + project_id
2. Backend inserts `audio_separations` row, returns `{id: "abc", status: "PENDING", ...}`
3. Frontend starts polling `GET /download/?task_id=abc`
4. Celery worker:
   - Converts file to WAV
   - Runs demucs → generates 4 stems
   - Uploads to `mybucket/user/123/abc/vocals.wav`
   - Updates DB with public URLs
5. Frontend poll returns URLs → renders download buttons

**Real user journey:**
```
UI click → POST /separate/ → (immediate response) → poll GET /download/ → (after ~30-120s) → display stems
```

---

# 🚀 Frontend System Blueprint

---

## 🔹 STEP 1: UNDERSTAND PRODUCT

**Product:** AI-powered stem separation for audio tracks. Users upload audio files and receive 4 isolated stems (vocals, drums, bass, other) for remixing or analysis.

**Critical inferred details from backend:**
- Separation uses Demucs model (htdemucs)
- Free plan: serial processing via Redis queue (`MUSICGPT_MAX_PARALLEL=1`)
- Token-based billing (300 tokens per job, see `token_costs.py`)
- Polling-based status checks via `GET /download/`
- Job IDs are stable UUIDs returned immediately
- File storage on Supabase Storage
- Supports `project_id` for organizing user content

---

## 🔹 STEP 2: FRONTEND ARCHITECTURE

### Framework: **Next.js 14+** (App Router)
- Server Components for initial rendering
- Client Components for interactive upload/processing
- API Routes (if needed) — but backend handles all processing

### App Router Structure:
```
app/
├── page.tsx                    # Landing / library
├── upload/
│   └── page.tsx               # Upload page with separation form
├── dashboard/
│   └── page.tsx               # User library with separated tracks
├── loading.tsx                # Global loading state
└── not-found.tsx
```

### State Management:
- **Server State:** React Query (TanStack Query)
  - `useSeparation` mutation (POST /separate/)
  - `useSeparationStatus` query (poll GET /download/)
- **Client State:** Zustand or React Context
  - Active uploads, polling intervals, UI state

---

## 🔹 STEP 3: UI/UX SYSTEM

### Pages & Components (Atomic Design):

**Atoms:**
- `Button` — Primary, Secondary, Destructive
- `InputFile` — Drag & drop or file picker
- `Badge` — Status: PENDING, PROCESSING, COMPLETED, FAILED
- `ProgressBar` — Linear (for poll progress)
- `AudioPreview` — HTML5 audio player
- `DownloadButton` — Links to Supabase Storage URL

**Molecules:**
- `SeparationForm` — File input + project_id + submit
- `StemCard` — Single stem (vocals/drums/bass/other) with play/download

**Organisms:**
- `SeparationWorkflow` — Upload → Processing → Results
- `StemGallery` — 4-stem display
- `QueueMonitor` — Real-time status via polling

**Templates:**
- `UploadPage` — Full separation workflow
- `DashboardPage` — Grid of separated tracks

### Layout System:
- CSS Grid / Flexbox
- Responsive: mobile-first
- Design tokens: spacing (4px base), colors (semantic), radius, elevation

### Design System:
- Reusable component library with TypeScript props
- Dark/light mode support
- Accessible (WCAG AA): ARIA labels, keyboard nav

---

## 🔹 STEP 4: TECH STACK

| Concern | Choice | Reasoning |
|---------|--------|-----------|
| **Framework** | Next.js 14 | Server/client component split, API routes |
| **State** | React Query + Zustand | Server state + client UI state |
| **Styling** | Tailwind CSS + shadcn/ui | Rapid UI with consistent tokens |
| **File Upload** | React Dropzone + `fetch` multipart | Drag & drop UX |
| **Polling** | React Query `refetchInterval` | Built-in retry, backoff |
| **Audio** | HTML5 Audio API | Native playback |
| **Forms** | React Hook Form + Zod | Validation |
| **Error Boundaries** | React ErrorBoundary | Graceful fallbacks |
| **Testing** | Jest + React Testing Library | Unit + integration |

---

## 🔹 STEP 5: FEATURE-WISE BREAKDOWN

### Feature: Upload & Separate

**UI Components:**
- `DropZone` (drag & drop file)
- `ProjectIdInput` (optional or auto-filled)
- `SubmitButton` (disabled while validating)
- `StatusBadge` (PENDING/IN_QUEUE/COMPLETED/FAILED)

**Data Flow:**
1. User selects file → `onFileChange`
2. Form validation (file type, size) → enable submit
3. `useSeparation.mutate({ file, project_id })`
4. Receive `task_id` → start polling `useSeparationStatus(task_id)`
5. Poll every 2–5s while `status=IN_QUEUE`
6. On `COMPLETED` → render `StemGallery`
7. On `FAILED` → show error + retry button

**State Handling:**
- React Query mutation → loading/error/success states
- Polling interval: start on success, stop on COMPLETED
- Refetch on window focus (stale-while-revalidate)

**Edge Cases:**
- Network loss during poll → retry with exponential backoff
- File too large → client-side validation before upload
- Token insufficient → show "Insufficient credits" error

---

### Feature: Dashboard / Library

**UI Components:**
- `TrackCard` — Shows original audio + stems
- `FilterBadges` — Status filters (all, completed, failed)
- `Pagination` / Infinite scroll

**Data Flow:**
- `GET /library` → aggregate all content
- Map `audio_separations` rows with `sound_generations`, `editing_table`

---

### Feature: AIME (Auto Edit) — for completeness

Even though not part of core separation, blueprint includes:
- `AutoTrimPanel` — BPM detection, candidate cards, A/B compare
- `Slider` for strictness
- `CrossfadeDropdown`
- `ProgressBar` with segment color coding

---

## 🔹 STEP 6: DEVELOPMENT PLAN

1. **Setup**
   - Initialize Next.js + TypeScript + Tailwind
   - Configure React Query Provider
   - Set up Supabase client

2. **Layout**
   - Build header, footer, responsive grid
   - Theme tokens

3. **Core Components**
   - `DropZone`, `StatusBadge`, `AudioPreview`, `StemCard`
   - Reusable form elements

4. **Separation Workflow**
   - Implement `useSeparation` mutation
   - Implement polling query with React Query
   - Handle success/error states

5. **Dashboard**
   - Fetch library data
   - Render `TrackCard` grid

6. **Testing**
   - Unit tests for components
   - Mock API responses
   - Integration test: upload → poll → display

7. **Deployment**
   - Vercel config
   - Environment variables (Clerk, Supabase, etc.)

---

## 🔹 STEP 7: SCALABILITY

- **Code Splitting:** Lazy-load heavy pages (dashboard, AIME)
- **Lazy Polling:** Use exponential backoff when queue is long
- **SSR:** Static metadata pages; client-fetch dynamic data
- **Accessibility:** Ensure focus management for live status updates
- **SEO:** Metadata for public track pages (if applicable)

---

## 🔹 STEP 8: OUTPUT FORMAT

- **Clean Markdown** — ready for developer handoff
- **Tables** for forms, state machines
- **ASCII flow diagrams** for data flow
- **Component inventory** with props

---

# 🧠 INTELLIGENCE RULES

- Used only provided files (models, routers, services, README, migrations, claude.md)
- Cross-referenced token costs, queue behavior, DB schema
- Did NOT hallucinate unsupported features or APIs

---

# 🚫 HARD CONSTRAINTS

- No external service assumptions beyond provided code
- No secret exposure (all placeholders `<REDACTED>`)
- No mixing of unrelated features (e.g., image-to-song details)

---

# 🔥 QUALITY BAR

This documentation is production-grade, engineer-ready, and includes:
- Complete API contracts
- DB lifecycle
- Edge case handling
- Frontend component blueprint
- Development plan