# Python Async — From Basics to In-Depth
## Everything we discussed, with real examples from this codebase

---

## PART 1: The Foundation — What is the Event Loop?

Before understanding `def` vs `async def`, you need to understand **where your code runs**.

FastAPI is built on `asyncio` — Python's async engine. It runs on a **single thread** called the **event loop**.

Think of the event loop as **one chef in a kitchen**:

```
One Chef (Event Loop Thread)
│
├── Takes order from User A  → starts cooking
├── While food is in oven... → takes order from User B
├── While waiting for sauce... → takes order from User C
└── Food ready → serves User A
```

The chef never stops working. While waiting for one thing, they work on another.
**This only works if the chef never gets stuck (blocked).**

---

## PART 2: def vs async def — The Core Difference

### Plain `def` — Synchronous (blocking)

```python
def get_data():
    time.sleep(5)    # waits 5 seconds
    return "done"
```

This is a **normal function**. When it runs, it runs completely from start to finish.
If it sleeps for 5 seconds, it literally does nothing for 5 seconds.

### `async def` — Asynchronous (can pause and resume)

```python
async def get_data():
    await asyncio.sleep(5)    # pauses HERE, lets others run
    return "done"
```

This is a **coroutine**. It can pause at `await` points and let other code run.
The `await` keyword means: *"I'm waiting — event loop, go do something else."*

### The key rule

```
await = "I'm pausing, you're free"
no await + blocking call = "I'm frozen, nobody moves"
```

---

## PART 3: time.sleep vs asyncio.sleep

This is where most confusion happens. They look similar but behave completely differently.

### time.sleep — Blocks the thread

```python
import time

async def bad_example():
    time.sleep(5)       # NO await — freezes EVERYTHING
    return "done"
```

Even though this is `async def`, `time.sleep` is a normal blocking call.
It has NO `await`. The event loop is frozen for 5 seconds.
**All other users wait. Nobody is served.**

```
Timeline:
0s  → User A hits /generate
0s  → time.sleep(5) starts — EVENT LOOP FROZEN
1s  → User B hits /download  ← WAITING, not served
2s  → User C hits /album     ← WAITING, not served
5s  → time.sleep done
5s  → User B finally gets served (5 seconds late)
```

### asyncio.sleep — Releases the event loop

```python
import asyncio

async def good_example():
    await asyncio.sleep(5)    # pauses, loop is FREE
    return "done"
```

The `await` tells the event loop: *"I'm sleeping, go serve others."*
The event loop uses those 5 seconds to handle other requests.

```
Timeline:
0s  → User A hits /generate
0s  → await asyncio.sleep(5) — EVENT LOOP IS FREE
0s  → User B hits /download  ← served immediately
0s  → User C hits /album     ← served immediately
5s  → User A's sleep done, continues
```

### Summary table

| | `time.sleep(5)` | `await asyncio.sleep(5)` |
|---|---|---|
| Blocks the thread? | YES | NO |
| Blocks the event loop? | YES (if in async def) | NO |
| Event loop free while waiting? | NO | YES |
| Use inside `async def`? | NEVER | YES |
| Use inside plain `def`? | YES (fine) | NO (can't await) |

---

## PART 4: The 3 Scenarios — Which is Safe?

### Scenario A: `async def` + `await` = SAFE

```python
async def get_data():
    await asyncio.sleep(5)          # releases loop — SAFE
    result = await some_async_call()  # releases loop — SAFE
    return result
```

Event loop is free at every `await`. Other requests are served. This is the ideal path.

### Scenario B: `async def` + blocking call = DANGEROUS

```python
async def get_data():
    time.sleep(5)                    # NO await — FREEZES loop
    result = supabase.table(...).execute()  # NO await — FREEZES loop
    return result
```

You are INSIDE the event loop but doing a blocking call with no `await`.
The loop cannot escape. Everything stops.

**This is exactly what your code had before the fixes.**

### Scenario C: plain `def` in Thread Pool = SAFE

```python
def get_data():
    time.sleep(5)                    # blocks THIS thread only
    result = supabase.table(...).execute()  # blocks THIS thread only
    return result
```

This runs in a **separate thread** (not the event loop thread).
The event loop keeps running in its own thread, completely unaffected.
`time.sleep` here is fine because it only blocks the worker thread, not the loop.

```
Thread Pool Thread  │  Event Loop Thread
────────────────────│────────────────────
def get_data():     │  (keeps running)
  time.sleep(5) ←  │  → serves User B
  blocks here   ←  │  → serves User C
  returns        →  │  → sends result back
```

---

## PART 5: FastAPI's Rules for BackgroundTasks

This is the critical part that caused confusion in your app.

When you do `background_tasks.add_task(my_function, ...)`, FastAPI checks:

```
Is my_function defined as async def?
    YES → run it directly in the event loop (you must handle async yourself)
    NO  → automatically send it to a thread pool (blocking is safe)
```

### Before the fix — DANGEROUS

```python
# album_service.py — BEFORE

async def monitor_album_completion(album_id: str) -> None:
    while elapsed < 600:
        await asyncio.sleep(15)              # OK — releases loop
        supabase.table(...).execute()        # DANGER — sync call in event loop
        supabase.table(...).execute()        # DANGER — sync call in event loop
```

FastAPI sees `async def` → runs it IN the event loop.
Every `supabase.execute()` call freezes the loop for ~100-200ms.
This loop runs for up to 600 seconds, hitting DB every 15s.
= **40 freezes over 10 minutes, each blocking all users**

### After the fix — SAFE

```python
# album_service.py — AFTER

def monitor_album_completion(album_id: str) -> None:   # plain def now
    while elapsed < 600:
        time.sleep(15)                       # fine — only blocks this thread
        supabase.table(...).execute()        # fine — only blocks this thread
        supabase.table(...).execute()        # fine — only blocks this thread
```

FastAPI sees plain `def` → sends it to a thread pool.
The entire 600-second monitor loop runs in its own thread.
The event loop never sees it. All users served normally.

---

## PART 6: run_in_threadpool — The Bridge

Sometimes you MUST stay `async def` (because you have `await` calls inside),
but you also need to make sync DB calls. This is where `run_in_threadpool` helps.

```python
from fastapi.concurrency import run_in_threadpool

async def my_function():
    await some_async_thing()                           # must stay async def
    result = await run_in_threadpool(                  # offload sync call
        lambda: supabase.table(...).execute()
    )
    return result
```

`run_in_threadpool` says: *"Take this sync function, run it in a thread pool,
await the result back in the event loop."*

It's the bridge between async context and sync code.

```
Event Loop Thread          Thread Pool Thread
──────────────────         ──────────────────
async def my_function():
  await some_async_thing() → runs here
  await run_in_threadpool( → sends lambda here →  supabase.execute()
                           ← result back       ←  blocks here (safe)
  use result
```

### Your real example — run_album_agent

`run_album_agent` MUST be `async def` because it calls:
```python
await album_agent.ainvoke(initial_state)   # this is async — needs await
```

So it can't be made plain `def`. But it also calls supabase at the end.
Solution: keep it `async def`, wrap only the sync DB calls:

```python
# BEFORE — dangerous
async def run_album_agent(...):
    final_state = await album_agent.ainvoke(initial_state)   # async — fine
    supabase.table("album_tracks").insert(track_rows).execute()  # sync — BLOCKS loop

# AFTER — safe
async def run_album_agent(...):
    final_state = await album_agent.ainvoke(initial_state)   # async — fine
    await run_in_threadpool(                                  # offloaded — safe
        lambda: supabase.table("album_tracks").insert(track_rows).execute()
    )
```

---

## PART 7: The Decision Tree — What Should I Use?

```
Is my function called as a FastAPI BackgroundTask?
│
├── YES: Does it have any `await` calls inside?
│   ├── YES → Must be `async def`
│   │         Wrap all sync calls with run_in_threadpool
│   │         Example: run_album_agent
│   │
│   └── NO  → Make it plain `def`
│             FastAPI threads it automatically
│             Use time.sleep, not asyncio.sleep
│             Example: monitor_album_completion
│
└── NO: Is it called from an `async def` route or service?
    │
    ├── YES: Is it itself `async def` with proper `await`?
    │   ├── YES → Fine as-is (ideal path)
    │   └── NO  → Wrap call with run_in_threadpool
    │             Example: ProjectService.get_all_projects()
    │
    └── NO: Running in Celery worker?
        → Completely separate process
        → Event loop doesn't exist here
        → Sync calls are totally fine
        → Example: music_tasks.py
```

---

## PART 8: Real Examples From Your Codebase

### Example 1 — Celery tasks (music_tasks.py) — sync is FINE

```python
# tasks/music_tasks.py
@celery_app.task
def submit_and_poll_task(operation, stable_task_id, record_ids, celery_params):
    supabase.table("music_metadata").update({...}).execute()   # totally fine
    time.sleep(5)                                               # totally fine
```

Celery workers run in **completely separate processes** from FastAPI.
There is no event loop here. Sync calls, time.sleep — all fine.
This is why we never touched music_tasks.py.

### Example 2 — monitor_album_completion — was wrong, now fixed

```python
# BEFORE — async def BackgroundTask with sync calls
async def monitor_album_completion(album_id):
    await asyncio.sleep(15)           # releases loop
    supabase.table(...).execute()     # FREEZES loop — wrong

# AFTER — plain def, FastAPI threads it
def monitor_album_completion(album_id):
    time.sleep(15)                    # blocks thread — fine
    supabase.table(...).execute()     # blocks thread — fine
```

### Example 3 — run_album_agent — must stay async, so use run_in_threadpool

```python
# BEFORE
async def run_album_agent(...):
    await album_agent.ainvoke(...)              # async call — needs async def
    supabase.table("album_tracks").insert(...)  # sync call — freezes loop

# AFTER
async def run_album_agent(...):
    await album_agent.ainvoke(...)              # async call — fine
    await run_in_threadpool(                    # offloaded to thread — fine
        lambda: supabase.table("album_tracks").insert(...).execute()
    )
```

### Example 4 — project router — sync service from async route

```python
# BEFORE — sync service called directly from async route
async def fetch_projects():
    return ProjectService.get_all_projects()   # sync — blocks loop

# AFTER — offloaded to thread
async def fetch_projects():
    return await run_in_threadpool(ProjectService.get_all_projects)  # safe
```

### Example 5 — download router — already correct (no change needed)

```python
# download_router.py
def get_download(user_id, task_id):    # plain def — NOT async def
    return DownloadService.get_tracks(user_id, task_id)
```

This is `def` (not `async def`) so FastAPI already threads it. No fix needed.

---

## PART 9: The Supabase Situation

Supabase Python SDK makes **HTTP calls** (not raw TCP DB connections).
Every `.execute()` is a synchronous HTTP request that blocks until the response arrives.

```python
supabase.table("music_metadata").select("*").execute()
# ↑ this is secretly doing:
#   1. open HTTP connection
#   2. send request
#   3. WAIT for response (100-300ms)  ← this is the blocking part
#   4. parse response
#   5. return data
```

If you call this from an `async def` without `await run_in_threadpool`,
the event loop is frozen for steps 1-5.

The proper long-term fix is the async supabase client:
```python
# supabase_client.py (future)
from supabase import acreate_client, AsyncClient
supabase: AsyncClient = await acreate_client(url, key)

# then everywhere:
await supabase.table("music_metadata").select("*").execute()
# ↑ now it properly releases the event loop while waiting
```

But this requires changing every single service file — a large refactor.
The `run_in_threadpool` approach is the safe interim solution.

---

## PART 10: The Complete Mental Model

```
YOUR APP
│
├── FastAPI Event Loop Thread (ONE thread)
│   │
│   ├── async def route handlers
│   ├── async def BackgroundTasks  ← runs here if async def
│   └── await = "pause me, serve others"
│
├── Thread Pool (multiple threads, managed by FastAPI)
│   │
│   ├── def BackgroundTasks        ← FastAPI sends these here automatically
│   ├── run_in_threadpool() calls  ← manually offloaded sync work
│   └── blocking is fine here, doesn't affect event loop
│
└── Celery Worker Processes (completely separate)
    │
    ├── submit_and_poll_task
    ├── process_album_track_task
    └── sync everything is fine — no event loop exists here
```

### The Golden Rules

1. **Inside `async def` → never call blocking code without `await`**
2. **`time.sleep` in `async def` = ALWAYS wrong. Use `await asyncio.sleep`**
3. **Sync supabase calls in `async def` = ALWAYS wrong. Use `run_in_threadpool`**
4. **BackgroundTask with no `await` inside → make it plain `def`, let FastAPI thread it**
5. **BackgroundTask with `await` inside → keep `async def`, wrap sync calls with `run_in_threadpool`**
6. **Celery tasks → sync everything is fine, they're separate processes**
7. **`def` route handler (not async) → FastAPI auto-threads it, sync calls are fine**
