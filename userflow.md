# User Flow Diagrams & File Responsibilities

---

## Which file does what

```
HTTP Request arrives
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│  routers/  (e.g. music_router.py, inpaint_router.py)            │
│  • Validates request shape (Pydantic model)                     │
│  • Checks prompt length (≤280 chars)                            │
│  • Calls the matching service method                            │
│  • Calls submit_and_poll_task.apply_async() to enqueue to Redis │
│  • Returns pre-inserted DB rows to client immediately           │
└────────────────────────┬────────────────────────────────────────┘
                         │ calls
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  services/music_service.py                                      │
│  • Generates a stable UUID (task_id) for the client to track    │
│  • Pre-inserts 2 music_metadata rows: status=QUEUED             │
│  • For inpaint/extend/remix: fetches source row first           │
│  • Returns (records, celery_params) — no MusicGPT call here     │
└────────────────────────┬────────────────────────────────────────┘
                         │ insert
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Supabase DB  (music_metadata table)                            │
│  • Rows inserted with status=QUEUED, task_id=<stable UUID>      │
│  • conversion_id = placeholder (UUID_1 / UUID_2) for now        │
│  • musicgpt_task_id = NULL for now                              │
└─────────────────────────────────────────────────────────────────┘

Meanwhile, router enqueues Celery task:
                         │ apply_async → Redis
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  Redis (message broker)                                         │
│  • Holds the job in queue: musicgpt_album                       │
│  • Job payload: operation, stable_task_id, record_ids, params   │
│  • Jobs from ALL users line up here                             │
│  • FIFO order — first in, first served                          │
└────────────────────────┬────────────────────────────────────────┘
                         │ worker picks up (concurrency=N)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  tasks/music_tasks.py  → submit_and_poll_task                   │
│  STEP 1 — Submit to MusicGPT:                                   │
│    • Calls POST /MusicAI (or /inpaint, /extend, /Remix)         │
│    • Gets back: musicgpt_task_id, conv_id_1, conv_id_2          │
│  STEP 2 — Update pre-inserted rows:                             │
│    • SET conversion_id = real conv_id_1/conv_id_2               │
│    • SET musicgpt_task_id = real task_id from MusicGPT          │
│    • SET status = IN_QUEUE                                       │
│  STEP 3 — Poll MusicGPT every 5s:                               │
│    • GET /byId?task_id=musicgpt_task_id&conversion_id=...       │
│    • When COMPLETED: download MP3, upload to Supabase Storage   │
│    • Update DB row: status=COMPLETED, audio_url, title, etc.    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Single-track generation — full state flow

```
CLIENT                    FASTAPI SERVER              REDIS            CELERY WORKER         MUSICGPT API
  │                            │                        │                    │                     │
  │  POST /music/generateMusic │                        │                    │                     │
  │ ─────────────────────────► │                        │                    │                     │
  │                            │ music_service:         │                    │                     │
  │                            │ INSERT 2 rows          │                    │                     │
  │                            │ status=QUEUED          │                    │                     │
  │                            │ task_id=<UUID>         │                    │                     │
  │                            │ ──────────────────────────────────────────────────────────►      │
  │                            │                        │                    │              Supabase DB
  │                            │ apply_async(job)       │                    │                     │
  │                            │ ──────────────────────►│                    │                     │
  │  ◄─────────────────────────│ return rows instantly  │                    │                     │
  │  status=QUEUED             │  (<100ms)              │                    │                     │
  │  task_id=<UUID>            │                        │                    │                     │
  │                            │                        │  pick up job       │                     │
  │                            │                        │ ──────────────────►│                     │
  │                            │                        │                    │  POST /MusicAI      │
  │                            │                        │                    │ ───────────────────►│
  │                            │                        │                    │  ◄───────────────── │
  │                            │                        │                    │  task_id, conv_id_1 │
  │                            │                        │                    │  conv_id_2          │
  │                            │                        │                    │                     │
  │                            │                        │          UPDATE rows:                    │
  │                            │                        │          status=IN_QUEUE                 │
  │                            │                        │          musicgpt_task_id=...            │
  │                            │                        │          conversion_id=real values       │
  │                            │                        │          ──────────────────────────►     │
  │                            │                        │                                   Supabase DB
  │  GET /download/            │                        │                    │                     │
  │ ─────────────────────────► │                        │                    │                     │
  │  ◄─────────────────────────│ status=IN_QUEUE        │                    │                     │
  │  (audio_url=null)          │ (read from DB)         │                    │                     │
  │                            │                        │                    │  GET /byId (poll)   │
  │                            │                        │                    │ ───────────────────►│
  │                            │                        │                    │  ◄─────────────────-│
  │                            │                        │                    │  status=PROCESSING  │
  │                            │                        │                    │  (repeat every 5s)  │
  │                            │                        │                    │  ───────────────────►
  │                            │                        │                    │  ◄───────────────── │
  │                            │                        │                    │  status=COMPLETED   │
  │                            │                        │                    │  audio_url=...      │
  │                            │                        │                    │                     │
  │                            │                        │          Download MP3, upload to Storage │
  │                            │                        │          UPDATE rows:                    │
  │                            │                        │          status=COMPLETED                │
  │                            │                        │          audio_url=<storage URL>         │
  │                            │                        │          ──────────────────────────►     │
  │                            │                        │                                   Supabase DB
  │  GET /download/            │                        │                    │                     │
  │ ─────────────────────────► │                        │                    │                     │
  │  ◄─────────────────────────│ status=COMPLETED       │                    │                     │
  │  audio_url=<storage URL>   │ audio_url populated    │                    │                     │
```

**Status values the client sees when polling `GET /download/`:**

| Status | Meaning | audio_url |
|--------|---------|-----------|
| `QUEUED` | Job is waiting in Redis, Celery hasn't picked it up yet | null |
| `IN_QUEUE` | Job submitted to MusicGPT, Celery is polling for result | null |
| `COMPLETED` | Audio ready, uploaded to Supabase Storage | populated |
| `FAILED` | MusicGPT error, timeout, or connection failure | null |
| `ERROR` | MusicGPT returned ERROR status for this conversion | null |

---

## Multiple users — queue behaviour

```
                           REDIS queue: musicgpt_album
                           ┌──────────────────────────┐
User A  POST /generateMusic│  [Job-A: operation=music] │◄── enqueued
User B  POST /generateMusic│  [Job-B: operation=music] │◄── enqueued  (all get instant
User C  POST /remix        │  [Job-C: operation=remix] │◄── enqueued   HTTP response)
User D  POST /extend       │  [Job-D: operation=extend]│◄── enqueued
                           └──────────┬───────────────┘
                                      │
                         MUSICGPT_MAX_PARALLEL=1
                                      │
                    Celery worker (concurrency=1)
                                      │
                          ┌───────────▼───────────┐
                          │  Processing Job-A      │  ← active
                          │  status: IN_QUEUE      │
                          │  polling MusicGPT...   │
                          └───────────┬───────────┘
                                      │ done
                          ┌───────────▼───────────┐
                          │  Processing Job-B      │  ← active
                          └───────────┬───────────┘
                                      │ done
                          ┌───────────▼───────────┐
                          │  Processing Job-C      │  ← active (remix)
                          │  download audio first  │
                          │  then POST /Remix      │
                          └───────────┬───────────┘
                                      │ done
                          ┌───────────▼───────────┐
                          │  Processing Job-D      │  ← active
                          └───────────────────────┘

With MUSICGPT_MAX_PARALLEL=2  (paid plan):
  Job-A + Job-B run in parallel
  Job-C + Job-D run in parallel after A/B finish
```

---

## Album generation — full state flow

```
CLIENT                   FASTAPI SERVER                REDIS         CELERY WORKER     MUSICGPT
  │                           │                          │                 │                │
  │  POST /album/create       │                          │                 │                │
  │ ────────────────────────► │                          │                 │                │
  │                           │ INSERT albums row        │                 │                │
  │                           │ status=PLANNING          │                 │                │
  │  ◄────────────────────────│ return album_id          │                 │                │
  │                           │ (BackgroundTask starts)  │                 │                │
  │                           │                          │                 │                │
  │                           │  LangGraph agent runs:   │                 │                │
  │                           │  analyze_script →        │                 │                │
  │                           │  plan_tracks →           │                 │                │
  │                           │  generate_prompts →      │                 │                │
  │                           │  generate_lyrics         │                 │                │
  │                           │  INSERT album_tracks     │                 │                │
  │                           │  UPDATE albums           │                 │                │
  │                           │  status=PLANNED          │                 │                │
  │                           │                          │                 │                │
  │  GET /album/{id}  (poll)  │                          │                 │                │
  │ ────────────────────────► │                          │                 │                │
  │  ◄────────────────────────│ status=PLANNED ✓         │                 │                │
  │                           │                          │                 │                │
  │  PUT /album/{id}/approve  │                          │                 │                │
  │ ────────────────────────► │                          │                 │                │
  │                           │ UPDATE albums            │                 │                │
  │                           │ status=GENERATING        │                 │                │
  │                           │ enqueue 1 Celery task    │                 │                │
  │                           │ per track ──────────────►│                 │                │
  │  ◄────────────────────────│ return immediately       │                 │                │
  │                           │                          │                 │                │
  │                           │                          │ pick track-1 ──►│                │
  │                           │                          │                 │  POST /MusicAI │
  │                           │                          │                 │ ──────────────►│
  │                           │                          │                 │ ◄──────────────│
  │                           │                          │                 │ INSERT music_metadata
  │                           │                          │                 │ UPDATE album_tracks
  │                           │                          │                 │ status=IN_QUEUE
  │                           │                          │                 │  GET /byId poll│
  │                           │                          │                 │ ◄──────────────│
  │                           │                          │                 │ status=COMPLETED
  │                           │                          │                 │ upload MP3     │
  │                           │                          │                 │                │
  │  GET /album/{id}/progress │                          │                 │                │
  │ ────────────────────────► │                          │                 │                │
  │  ◄────────────────────────│ tracks_completed=1/N     │                 │                │
  │                           │                          │ pick track-2 ──►│  (next track)  │
  │                           │                          │       ...       │                │
  │                           │  monitor sees all done   │                 │                │
  │                           │  UPDATE albums           │                 │                │
  │                           │  status=COMPLETED        │                 │                │
  │                           │                          │                 │                │
  │  GET /album/{id}          │                          │                 │                │
  │ ────────────────────────► │                          │                 │                │
  │  ◄────────────────────────│ status=COMPLETED ✓       │                 │                │
  │  full tracks with audio   │                          │                 │                │
```
