# Clerk + Supabase User Management + Token Wallet — Backend Plan

> **Scope:** backend only. No changes to `audio_edit_test.html` in this plan.
> **Payments:** Dodo Payment — scaffold only; full integration later.
> **Status:** Phase 1 ✅ complete · Phase 2 ✅ complete · Phase 3–6 pending

---

## Context

The FastAPI backend currently has **no authentication**. Every router accepts `user_id` as a plain string in request bodies, form fields, or query params — the client decides who they are. This blocks launch.

This change adds:
1. **Clerk** as the auth provider (sign up, sign in, JWT)
2. **4 new tables** — `users`, `subscriptions`, `token_balances`, `token_transactions`
3. **Backend JWT verification** via a FastAPI dependency
4. **Token wallet** with per-feature debits and refund-on-failure
5. **Row Level Security (RLS)** on every Supabase table using **Clerk JWT Template → native Supabase RLS** (defense-in-depth)
6. Convert all `user_id TEXT` columns to **UUID** with FK to `users.id`; backfill non-UUID rows to a **single dummy user**
7. **Dodo Payment** scaffold only — generic payment column names + 501-stub endpoints for future integration

---

## Auth flow (Clerk JWT)

**Sign-up (first-time sign-in):**
1. Frontend gets JWT from Clerk
2. Frontend sends `Authorization: Bearer <jwt>` to any API
3. Backend dependency `get_current_user` verifies JWT via Clerk JWKS
4. Extracts `sub` (clerk_user_id)
5. Looks up `users` table
6. If missing → atomically create: `users` + `subscriptions(plan=free)` + `token_balances(500)` + `token_transactions(+500, reason=signup_bonus)`
7. Returns internal `users.id` UUID to downstream route

**Sign-in (returning user):** same flow — lookup succeeds, no creation

**Clerk webhook** (`POST /auth/webhook/clerk`): syncs `user.updated` (email / name / avatar) and `user.deleted` (cascade deletes user row).

---

## New Tables (Supabase)

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clerk_user_id TEXT UNIQUE NOT NULL,
  email TEXT NOT NULL,
  full_name TEXT,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  plan TEXT NOT NULL DEFAULT 'free',          -- 'free' | 'starter' | 'pro' | 'enterprise'
  status TEXT NOT NULL DEFAULT 'active',      -- 'active' | 'cancelled' | 'expired'
  payment_customer_id TEXT,                   -- generic (Dodo / Stripe / whatever)
  payment_subscription_id TEXT,
  current_period_start TIMESTAMPTZ,
  current_period_end TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE token_balances (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE UNIQUE,
  total_tokens INT NOT NULL DEFAULT 0,
  used_tokens INT NOT NULL DEFAULT 0,
  balance INT GENERATED ALWAYS AS (total_tokens - used_tokens) STORED,
  monthly_reset_date TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE token_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL,                         -- 'credit' | 'debit' | 'refund' | 'monthly_reset'
  amount INT NOT NULL,
  balance_after INT NOT NULL,
  reason TEXT,                                -- 'signup_bonus' | 'music_generation' | 'refund' | …
  job_id UUID,                                -- link to music_metadata or album_tracks
  created_at TIMESTAMPTZ DEFAULT now()
);
```

> Column names use `payment_*` (generic) instead of `stripe_*` so Dodo plugs in without a schema change.

---

## Phase 1 — Database migrations

### 1.1 Auth tables — `migrations/006_create_auth_tables.sql`
- [x] Create `users`, `subscriptions`, `token_balances`, `token_transactions` (SQL above)
- [x] Seed one dummy user with fixed UUID `00000000-0000-0000-0000-000000000001` + dummy subscription + dummy token_balance (target for legacy data backfill)
- [x] Postgres function `create_user_with_defaults(clerk_id, email, full_name, avatar)` — atomic insert of 4 rows; returns new `users.id` UUID

### 1.2 Migrate existing `user_id` columns — `migrations/007_migrate_user_id_to_uuid.sql`
- [x] For each table: `UPDATE <t> SET user_id = '00000000-...-001' WHERE user_id !~ UUID-regex` (non-UUID values → dummy user)
- [x] `ALTER COLUMN user_id TYPE UUID USING user_id::uuid`
- [x] `ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE`
- [x] Tables converting TEXT → UUID: `music_metadata`, `albums`, `editing_table`, `sound_generations`, `projects`
- [x] Already UUID — just add FK: `user_prompts`, `audio_separations`
- [x] **NOT touched:** `album_tracks` (inherits via `album_id` → `albums.user_id`)

### 1.3 RLS policies — `migrations/008_enable_rls.sql`
- [x] `ENABLE ROW LEVEL SECURITY` on all user-owned tables
- [x] Direct ownership: `CREATE POLICY user_owns_row ON <t> FOR ALL USING (user_id = auth.uid())`
- [x] Indirect (album_tracks): `CREATE POLICY user_owns_album_track ON album_tracks FOR ALL USING (album_id IN (SELECT id FROM albums WHERE user_id = auth.uid()))`
- [x] Self-read on `users` (`id = auth.uid()`), `subscriptions`, `token_balances`, `token_transactions`
- [x] Service role bypasses RLS — Celery tasks keep using `SUPABASE_KEY` (service role)

---

## Phase 2 — Clerk integration

### 2.1 Dependencies (`pyproject.toml`)
- [x] `pyjwt[crypto]>=2.8.0` — verify Clerk JWT signature via JWKS
- [x] `svix>=1.0.0` — verify Clerk webhook signatures

### 2.2 Env vars (`.env` + new `.env.example`)
- [x] `CLERK_JWKS_URL`
- [x] `CLERK_ISSUER`
- [x] `CLERK_WEBHOOK_SECRET`
- [x] `SUPABASE_JWT_SECRET` — used by Clerk JWT Template to sign Supabase-compatible tokens
- [x] `SUPABASE_ANON_KEY` — for per-request, JWT-scoped Supabase clients (RLS path)
- [x] Keep existing `SUPABASE_KEY` as the service role key (Celery / webhooks)

### 2.3 New package — `auth/clerk_auth.py`
- [x] JWKS cache with TTL
- [x] `verify_clerk_jwt(token) -> dict` — verify signature, `iss`, `exp`
- [x] `get_current_user(authorization) -> UserContext` FastAPI dependency:
  - Parse `Authorization: Bearer <jwt>` (401 if missing / malformed)
  - Verify JWT → claims
  - Look up `users` by `clerk_user_id = claims['sub']`
  - If missing → call `create_user_with_defaults(...)` RPC
  - Return `UserContext(id=UUID, clerk_user_id, email, jwt)`
- [x] `get_current_user_optional` — returns `None` for public endpoints
- [x] `get_scoped_supabase(user_ctx) -> Client` — Supabase client bound to the user's JWT (RLS enforces ownership)
- [x] `UserContext` Pydantic model in new `models/auth_model.py`

### 2.4 Auth router — `routers/auth_router.py`
- [x] `POST /auth/webhook/clerk` — verify svix signature, handle `user.created` (idempotent sync), `user.updated` (email/name/avatar), `user.deleted` (cascade delete)
- [x] `GET /auth/me` — return `{ user, subscription, token_balance }` for current JWT
- [x] Register in `main.py`

---

## Phase 3 — Token wallet service

### 3.1 New service — `services/token_service.py`
- [x] `InsufficientTokensError(Exception)`
- [x] `get_balance(user_id) -> int`
- [x] `debit_tokens(user_id, amount, reason, job_id=None) -> int` — Postgres function for atomicity: check balance ≥ amount → update `used_tokens` + insert transaction; raises `InsufficientTokensError`
- [x] `credit_tokens(user_id, amount, reason, job_id=None) -> int`
- [x] `refund_tokens(user_id, amount, job_id) -> int` — wrapper with `reason='refund'`
- [ ] `monthly_reset(user_id, plan) -> int` — clears `used_tokens`, grants plan allotment (future cron)

### 3.2 Token cost constants — `config/token_costs.py`
- [x] `music_generation`: **10**
- [x] `remix`: **8**
- [x] `extend`: **6**
- [x] `inpaint`: **6**
- [x] `album_per_track`: **10** (pre-debit = `tracks_to_generate × 10` at approve time)
- [x] `sound_generation`: **5**
- [x] `image_to_song`: **10**
- [x] `mastering` / `enhance` / `warmth` / `reference_match` / `podcast_produce`: **2** each
- [x] `auto_edit` / `audio_edit`: **1** each
- [x] `lyrics_generate` / `quick_idea` / `prompt_enhance`: **1** each

### 3.3 Wire debits into routers (pre-debit pattern)
- [x] `music_router.generateMusic` / `remix_music` — debit BEFORE `submit_and_poll_task.apply_async`; pass `job_id=stable_task_id`
- [x] `inpaint_router`, `extend_router`, `sound_router`, `image_to_song_router` — same pattern
- [x] `album_router.approve` — debit `tracks_not_completed × album_per_track`
- [x] `audio_edit_test_router`, `auto_edit_router`, `mastering_router`, `reference_match_router`, `podcast_router` — debit per endpoint call (processing endpoints, NOT `/save`)
- [x] `lyrics_router`, `prompt_router` — debit per call
- [x] `separation_router` — debit on `POST /separate/`
- [x] Celery task `submit_and_poll_task` on terminal FAILED → call `refund_tokens`
- [ ] Album per-track `regenerate`/`replan` — debit one unit; refund on failure
- [ ] Validation failures (HTTP 422/400/503 before Celery enqueue) → do NOT debit

---

## Phase 4 — Refactor existing routers/models to source `user_id` from JWT

### 4.1 Pydantic models — remove `user_id` (and `user_name` / `user_email` where present)
- [x] `models/music_model.py` — `MusicCreate`, `InpaintCreate` (keep `user_id` only in `MusicResponse`, filled by server)
- [x] `models/album_model.py` — `AlbumCreate`
- [x] `models/project_model.py` — `projectCreate`
- [x] `models/lyrics_model.py` — both request models
- [x] `models/prompt_model.py` — all three request models
- [x] `models/sound_model.py` — `SfxRequest.user_id` + its validator
- [x] `models/image_to_song_model.py` — `user_id` + UUID validator
- [x] `models/separation_model.py` — response only; router drops Form field
- [x] Drop `user_name` / `user_email` from request bodies — fetch them from the `users` table in the service layer (single source of truth; blocks client spoofing)

### 4.2 Routers — add `user: UserContext = Depends(get_current_user)`
- [x] `routers/music_router.py` — `generateMusic`, `remix`
- [x] `routers/inpaint_router.py`
- [x] `routers/extend_router.py`
- [x] `routers/lyrics_router.py`
- [x] `routers/prompt_router.py`
- [x] `routers/download_router.py` — drop `user_id` query param; keep `task_id`
- [x] `routers/project_router.py`
- [x] `routers/album_router.py` — create, approve, progress, GET, per-track replan/regenerate
- [x] `routers/sound_router.py`
- [x] `routers/image_to_song_router.py`
- [x] `routers/separation_router.py`
- [x] `routers/audio_edit_test_router.py` — all `/test-edit/*` ops + `/save`
- [x] `routers/auto_edit_router.py`
- [x] `routers/mastering_router.py` — `/save` currently takes `user_id: Form(...)`, remove
- [x] `routers/reference_match_router.py` — same
- [x] `routers/podcast_router.py` — same
- [x] `routers/queue_router.py` — gate behind auth (or make admin-only)
- [ ] **Public endpoints (no auth):** `/`, `/health`, `/master/platforms`, `GET /test-edit/ui`, `/payment/plans`

### 4.3 Service layer
- [x] All services: `user_id` flows as `str(UUID)` from JWT → service → Supabase (UUID string accepted natively; no schema change needed)
- [x] Celery tasks in `tasks/music_tasks.py` — `user_id` in `celery_params` is now a JWT-derived UUID string; service role Supabase client unchanged
- [x] `routers/audio_edit_test_router.py::_upload_result` — receives JWT-derived UUID string via `str(user.id)`

### 4.4 Public endpoints (no auth required)
- [x] `GET /` — root welcome message (main.py)
- [x] `GET /health` — health check (main.py), returns `{"status": "ok"}`
- [x] `GET /master/platforms` — static list, no auth dep
- [x] `GET /test-edit/ui` — serves HTML test UI, no auth dep
- [x] `GET /payment/plans` — public, no auth required

---

## Phase 5 — Dodo Payment scaffold

### 5.1 New router — `routers/payment_router.py`
- [x] `GET /payment/plans` — static list of plans with monthly token allotments
- [x] `POST /payment/checkout` — HTTP **501** placeholder; signature accepts `plan_id`
- [x] `POST /payment/webhook/dodo` — HTTP **501**; placeholder for future svix-style signature verification
- [x] `GET /payment/subscription` — return current user's subscription row (auth-protected)
- [x] Register in `main.py`

### 5.2 Generic column naming
- [x] Covered by Phase 1.1 — `payment_customer_id` / `payment_subscription_id`, not `stripe_*`. Dodo plugs in without schema change.

---

## Phase 6 — Verification

### 6.1 Infrastructure checks (run `GET /health/detailed`)
- [x] `GET /health` — public ping, returns `{"status":"ok"}`
- [x] `GET /health/detailed` — checks DB + Redis + Celery; returns per-component status

### 6.2 Refund wiring (coded — ready to test)
- [x] `submit_and_poll_task` calls `_try_refund` on every early-exit FAILED path (submit error, validation error, retries exhausted, missing payload)
- [x] `_poll_and_store` returns final status string; Celery task calls `_try_refund` if primary conversion is FAILED/ERROR
- [x] `_try_refund` is non-fatal — logs error and continues if token service is unavailable

### 6.3 Manual verification steps (do these once Clerk + DB are configured)
- [ ] Run `006_*.sql`, `007_*.sql`, `008_*.sql` on a **dev Supabase project** first
- [ ] Configure Clerk JWT Template in the Clerk dashboard (template name: `supabase`, claim `sub` = internal `users.id` UUID, signing key = Supabase JWT secret)
- [ ] Sign up a new Clerk user → hit any endpoint → verify:
  - [ ] `users` row created
  - [ ] `subscriptions` row with `plan=free`
  - [ ] `token_balances` with `total_tokens=500`
  - [ ] `token_transactions` with `amount=500`, `reason=signup_bonus`
- [ ] `POST /music/generateMusic` without JWT → **401**
- [ ] `POST /music/generateMusic` with JWT → **200**; balance 500 → 490; new `debit` transaction
- [ ] Force MusicGPT failure → verify refund transaction + balance back to 500
- [ ] Sign in as **user B**, query `music_metadata` for **user A's** task_id → **empty** (RLS blocks)
- [ ] Clerk webhook `user.updated` test event → `users.full_name` updated
- [ ] Legacy data check: every orphaned pre-migration row is owned by the dummy user UUID
- [ ] `GET /payment/plans` returns 4 plans; `POST /payment/checkout` returns **501**
- [ ] `GET /payment/subscription` returns real balance + plan from DB

---

## Notes & tradeoffs

- **RLS choice (Clerk JWT Template + native RLS):** defense-in-depth. Cost: Clerk dashboard configuration + per-request scoped Supabase client. Benefit: backend code bugs cannot leak cross-user data.
- **Dummy user backfill:** matches the original plan3.md spec. A one-off SQL script can later split the dummy user into per-legacy-id users if needed before production cutover.
- **Celery tasks run outside request context** — keep using service role key (bypasses RLS).
- **`user_name` / `user_email` removal** from request bodies blocks frontend spoofing; server pulls them from `users` whenever `music_metadata` needs them.
- **`album_tracks` skipped:** correct — RLS policy joins through `albums.user_id`.
- **Two Supabase keys** in `.env`: service role (backend/Celery) + anon (per-request RLS-scoped clients).
