# Manual Test Cases — AI Music Gen API

**Base URL:** `http://localhost:8000`  
**Swagger UI:** `http://localhost:8000/docs`

---

## Setup Before Testing

### Prerequisites
- FastAPI server running: `uv run uvicorn main:app --reload`
- Celery worker running: `uv run celery -A celery_app worker -Q musicgpt_album --concurrency=1 --loglevel=info`
- Redis running: `redis-cli ping` → `PONG`

### Get Test Tokens
Register **two separate accounts** in Clerk (use incognito for the second):

```
User A: userA@test.com  → TOKEN_A
User B: userB@test.com  → TOKEN_B
```

Get token in browser console while logged in:
```js
await window.Clerk.session.getToken()
```

Or in Swagger UI `/docs` → click **Authorize** → paste token (no "Bearer" prefix).

---

## T-01: Authentication

### T-01-1: No token → 401
```bash
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Content-Type: application/json" \
  -d '{"project_id":"1","type":"music","prompt":"test"}'
```
**Expected:** `401 Authorization header required`

---

### T-01-2: Invalid token → 401
```bash
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Authorization: Bearer this_is_fake" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"1","type":"music","prompt":"test"}'
```
**Expected:** `401 Malformed JWT`

---

### T-01-3: Expired token → 401
Use a token from yesterday (copy from a previous session).  
**Expected:** `401 JWT expired`

---

### T-01-4: Valid token → user profile returned
```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** `200` with `id`, `clerk_user_id`, `email`, `full_name`, `subscription`, `token_balance`

---

### T-01-5: First login creates user automatically
Register a brand-new email in Clerk, get its token, hit `/auth/me`.  
**Expected:** User is created in DB with default free subscription + 500 token balance. No manual DB insert needed.

---

## T-02: Projects

### T-02-1: Create project
```bash
curl -X POST http://localhost:8000/projects/ \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"project_name":"My Test Project","created_by":"UserA"}'
```
**Expected:** `200` with project row. Note the returned `id` as `PROJECT_A_ID`.

---

### T-02-2: List only your projects
```bash
curl http://localhost:8000/projects/ \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** Only User A's projects listed. User B's projects never appear.

---

### T-02-3 [CROSS-USER]: User B cannot see User A's projects
```bash
curl http://localhost:8000/projects/ \
  -H "Authorization: Bearer $TOKEN_B"
```
**Expected:** Empty list `[]` or only User B's own projects. User A's project NOT in response.

---

## T-03: Music Generation

### T-03-1: Generate music (instrumental)
```bash
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "'$PROJECT_A_ID'",
    "type": "music",
    "prompt": "Relaxing lo-fi beat with soft piano",
    "music_style": "lofi, chill",
    "make_instrumental": true,
    "output_length": 30
  }'
```
**Expected:** `200` immediately. Note `task_id` as `TASK_A`. Status = `QUEUED`.

---

### T-03-2: Poll for completion
```bash
curl "http://localhost:8000/download/?task_id=$TASK_A" \
  -H "Authorization: Bearer $TOKEN_A"
```
Run every 10s. Progress: `QUEUED` → `IN_QUEUE` → `COMPLETED`.  
**Expected on COMPLETED:** `audio_url` populated, `title`, `duration`, `album_cover_path` present.

---

### T-03-3 [CROSS-USER]: User B cannot access User A's track
```bash
curl "http://localhost:8000/download/?task_id=$TASK_A" \
  -H "Authorization: Bearer $TOKEN_B"
```
**Expected:** `404 No tracks found` — task_id exists but user_id doesn't match.

---

### T-03-4: Prompt too long → 422
```bash
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"1","type":"music","prompt":"'$(python3 -c "print('x'*281)'")'}'
```
**Expected:** `422 prompt must be ≤ 280 characters`

---

## T-04: Remix

### T-04-1: Remix own track
After T-03-2 completes, note the music_metadata UUID from the download response as `MUSIC_A_ID`.
```bash
curl -X POST http://localhost:8000/music/remix \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"id": "'$MUSIC_A_ID'", "prompt": "Make it darker and cinematic"}'
```
**Expected:** `200` with new task_id. Queued for processing.

---

### T-04-2 [CROSS-USER]: User B cannot remix User A's track
```bash
curl -X POST http://localhost:8000/music/remix \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{"id": "'$MUSIC_A_ID'"}'
```
**Expected:** `400 Forbidden: source track does not belong to this user`

---

## T-05: Inpaint

### T-05-1: Inpaint own track
After T-03-2 completes, get `audio_url` as `AUDIO_URL_A`.
```bash
curl -X POST http://localhost:8000/inpaint/inpaint \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "'$MUSIC_A_ID'",
    "audio_url": "'$AUDIO_URL_A'",
    "prompt": "Replace with heavier bass",
    "replace_start_at": 5.0,
    "replace_end_at": 15.0
  }'
```
**Expected:** `200` with new rows queued.

---

### T-05-2 [CROSS-USER]: User B cannot inpaint User A's track
```bash
curl -X POST http://localhost:8000/inpaint/inpaint \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{
    "id": "'$MUSIC_A_ID'",
    "audio_url": "'$AUDIO_URL_A'",
    "prompt": "hack",
    "replace_start_at": 0.0,
    "replace_end_at": 10.0
  }'
```
**Expected:** `400 Forbidden: source track does not belong to this user`

---

## T-06: Extend

### T-06-1: Extend own track
```bash
curl -X POST http://localhost:8000/extend/extend \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"id": "'$MUSIC_A_ID'"}'
```
**Expected:** `200` with new task_id.

---

### T-06-2 [CROSS-USER]: User B cannot extend User A's track
```bash
curl -X POST http://localhost:8000/extend/extend \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{"id": "'$MUSIC_A_ID'"}'
```
**Expected:** `400 Forbidden: source track does not belong to this user`

---

## T-07: Lyrics Generation

### T-07-1: Generate lyrics
```bash
curl -X POST http://localhost:8000/lyrics/generate \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a love song about missing someone",
    "style": "pop ballad",
    "mood": "melancholic"
  }'
```
**Expected:** `200` with generated lyrics text. Stored in `user_prompts` table under User A's `user_id`.

---

### T-07-2 [CROSS-USER]: User B's library shows no User A lyrics
After T-07-1, log in as User B and check library.  
**Expected:** User B's `/library/` response has empty `lyrics` list.

---

## T-08: Prompt Features

### T-08-1: Quick idea
```bash
curl -X POST http://localhost:8000/prompt/quick-idea \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "sad rainy night drive"}'
```
**Expected:** `200` with a short music concept ≤ 280 chars.

---

### T-08-2: Prompt enhancer
```bash
curl -X POST http://localhost:8000/prompt/enhance \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a chill lo-fi beat for studying"}'
```
**Expected:** `200` with an enriched production-ready prompt.

---

### T-08-3: Prompt enhancer with custom master prompt
```bash
curl -X POST http://localhost:8000/prompt/enhance \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "epic battle theme",
    "master_prompt": "You are a film score composer. Expand into a detailed music brief."
  }'
```
**Expected:** `200` with expanded brief following the custom instructions.

---

## T-09: Sound Generation (SFX)

### T-09-1: Generate sound effect
```bash
curl -X POST http://localhost:8000/sound_generator/ \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "'$PROJECT_A_ID'",
    "prompt": "Thunder rumbling in the distance",
    "audio_length": 10
  }'
```
**Expected:** `200` immediately. Note `task_id` as `SFX_TASK_A`.

---

### T-09-2: Poll sound status
```bash
curl "http://localhost:8000/sound_generator/status?task_id=$SFX_TASK_A" \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** `{"is_completed": false/true, "has_audio": false/true, "ready_for_download": false/true}`

---

### T-09-3: Get sound after completion
```bash
curl "http://localhost:8000/sound_generator/?task_id=$SFX_TASK_A" \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected on complete:** `audio_url` pointing to Supabase Storage.

---

### T-09-4 [CROSS-USER]: User B cannot fetch User A's sound
```bash
curl "http://localhost:8000/sound_generator/?task_id=$SFX_TASK_A" \
  -H "Authorization: Bearer $TOKEN_B"
```
**Expected:** `404` or empty response — user_id in DB doesn't match Token B.

---

## T-10: Stem Separation

### T-10-1: Separate stems
```bash
curl -X POST http://localhost:8000/separate/ \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@/path/to/song.mp3" \
  -F "project_id=$PROJECT_A_ID"
```
**Expected:** `200` immediately with `job_id`. Status = `PENDING`.

---

### T-10-2: Poll separation status (check user library)
```bash
curl http://localhost:8000/library/ \
  -H "Authorization: Bearer $TOKEN_A"
```
Check `separations` array. Wait until `status = COMPLETED`.  
**Expected on complete:** `vocals_url`, `drums_url`, `bass_url`, `other_url` all populated.

---

## T-11: Album Generation

### T-11-1: Create album (Step 1)
```bash
curl -X POST http://localhost:8000/album/create \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "'$PROJECT_A_ID'",
    "script": "Act 1: A soldier at dawn full of hope. Act 2: War destroys his village. Act 3: He returns home to new life.",
    "songs": 1,
    "background_scores": 1,
    "instrumentals": 0
  }'
```
**Expected:** `200` immediately. Status = `PLANNING`. Note `album_id` as `ALBUM_A_ID`.

---

### T-11-2: Poll album planning (Step 2)
```bash
curl http://localhost:8000/album/$ALBUM_A_ID \
  -H "Authorization: Bearer $TOKEN_A"
```
Poll every 10s until `status == PLANNED`.  
**Expected:** Album has `tracks` with `prompt`, `music_style`, `lyrics` filled in by AI.

---

### T-11-3 [CROSS-USER]: User B cannot see User A's album
```bash
curl http://localhost:8000/album/$ALBUM_A_ID \
  -H "Authorization: Bearer $TOKEN_B"
```
**Expected:** `404 Album not found`

---

### T-11-4: Approve album (Step 3)
```bash
curl -X PUT http://localhost:8000/album/$ALBUM_A_ID/approve \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{}'
```
**Expected:** `200` with status `GENERATING`.

---

### T-11-5: Poll album progress (Step 4)
```bash
curl http://localhost:8000/album/$ALBUM_A_ID/progress \
  -H "Authorization: Bearer $TOKEN_A"
```
Poll every 20s.  
**Expected:** `{"status": "GENERATING", "total": 2, "completed": 0/1/2, "failed": 0}`  
Eventually: `status == COMPLETED`.

---

### T-11-6 [CROSS-USER]: User B cannot approve User A's album
```bash
curl -X PUT http://localhost:8000/album/$ALBUM_A_ID/approve \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{}'
```
**Expected:** `404 Album not found`

---

### T-11-7 [CROSS-USER]: User B cannot replan User A's track
Get a `track_id` from User A's album response. Call it `TRACK_A_ID`.
```bash
curl -X PUT http://localhost:8000/album/$ALBUM_A_ID/tracks/$TRACK_A_ID/replan \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{}'
```
**Expected:** `404 Album not found`

---

### T-11-8: Approve with track edits
```bash
curl -X PUT http://localhost:8000/album/$ALBUM_A_ID/approve \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{
    "track_updates": [
      {"id": "'$TRACK_A_ID'", "prompt": "Tender orchestral ballad with solo cello"}
    ]
  }'
```
**Expected:** `200` — track uses the overridden prompt.

---

### T-11-9: List all user albums
```bash
curl http://localhost:8000/album/user \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** Only User A's albums. User B's albums never appear.

---

## T-12: Audio Editing

### Setup
Save any mp3 locally as `track.mp3` for the following tests.

### T-12-1: Cut
```bash
curl -X POST http://localhost:8000/test-edit/cut \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "start_ms=0" \
  -F "end_ms=15000"
```
**Expected:** `200` audio response (~15s mp3).

---

### T-12-2: Fade
```bash
curl -X POST http://localhost:8000/test-edit/fade \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "fade_in_ms=1000" \
  -F "fade_out_ms=2000"
```
**Expected:** `200` audio with fade applied.

---

### T-12-3: AI Analog Warmth
```bash
curl -X POST http://localhost:8000/test-edit/warmth \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "intensity=0.7" \
  -F "vocal_mode=false"
```
**Expected:** `200` warmed audio. Should sound less harsh/digital.

---

### T-12-4: Warmth analyze
```bash
curl -X POST http://localhost:8000/test-edit/warmth/analyze \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "intensity=0.7"
```
**Expected:** `200` JSON with `spectral_profile`, `diagnostics`, `planned_adjustments`, `summary`.

---

### T-12-5: Style Enhancer presets list (public, no auth)
```bash
curl http://localhost:8000/test-edit/enhance/presets
```
**Expected:** `200` with 6 presets: lofi, edm, cinematic, pop, chill, vintage.

---

### T-12-6: Style Enhancer apply
```bash
curl -X POST http://localhost:8000/test-edit/enhance \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "preset=lofi" \
  -F "intensity=0.8"
```
**Expected:** `200` audio with lofi character.

---

### T-12-7: Save edit to cloud
```bash
curl -X POST http://localhost:8000/test-edit/save \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "project_id=$PROJECT_A_ID" \
  -F "operation=warmth" \
  -F "output_format=mp3"
```
**Expected:** `200` with `output_url` pointing to Supabase Storage.

---

### T-12-8 [CROSS-USER]: User B cannot save to User A's project
```bash
curl -X POST http://localhost:8000/test-edit/save \
  -H "Authorization: Bearer $TOKEN_B" \
  -F "file=@track.mp3" \
  -F "project_id=$PROJECT_A_ID" \
  -F "operation=warmth" \
  -F "output_format=mp3"
```
**Expected:** `403 Project not found or access denied`

---

## T-13: AIME (Auto Trim)

### T-13-1: Analyze audio
```bash
curl -X POST http://localhost:8000/auto-edit/analyze \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "target_duration=30" \
  -F "energy_preference=drop"
```
**Expected:** `200` with `bpm`, `segments`, `candidates` (top-3 scored windows).

---

### T-13-2: Natural language suggest
```bash
curl -X POST http://localhost:8000/auto-edit/suggest \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "description=punchy 30 second drop for a DJ mix"
```
**Expected:** `200` with `target_duration`, `energy_preference`, `strictness`, `crossfade_beats`, `explanation`.

---

### T-13-3: Preview (fast, no encoding)
```bash
curl -X POST http://localhost:8000/auto-edit/preview \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "target_duration=30" \
  -F "energy_preference=drop" \
  -F "user_description=punchy drop"
```
**Expected:** `200` with `window_start`, `window_end`, `agent_reasoning`, `candidates`. No audio bytes.

---

### T-13-4: Full trim
```bash
curl -X POST http://localhost:8000/auto-edit/trim \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "target_duration=30" \
  -F "energy_preference=drop" \
  -F "crossfade_beats=1"
```
**Expected:** `200` with `audio_b64`, `bpm`, `window_start`, `window_end`, `actual_duration`.

---

### T-13-5: Trim with manual window override
From T-13-4, pick `chosen_index=1`:
```bash
curl -X POST http://localhost:8000/auto-edit/trim \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "target_duration=30" \
  -F "chosen_window_index=1"
```
**Expected:** Uses candidate 1. `agent_reasoning` says "Manual override: candidate 1 selected by user."

---

### T-13-6: Save auto trim result
```bash
curl -X POST http://localhost:8000/auto-edit/save \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "audio_file=@trimmed.mp3" \
  -F "project_id=$PROJECT_A_ID" \
  -F "output_format=mp3"
```
**Expected:** `200` with `output_url`.

---

### T-13-7 [CROSS-USER]: User B cannot save to User A's project
```bash
curl -X POST http://localhost:8000/auto-edit/save \
  -H "Authorization: Bearer $TOKEN_B" \
  -F "audio_file=@trimmed.mp3" \
  -F "project_id=$PROJECT_A_ID"
```
**Expected:** `403 Project not found or access denied`

---

## T-14: Mastering

### T-14-1: List platforms (public)
```bash
curl http://localhost:8000/mastering/platforms
```
**Expected:** `200` list of mastering target platforms (Spotify, YouTube, etc.).

---

### T-14-2: Process mastering
```bash
curl -X POST http://localhost:8000/mastering/process \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "target_platform=spotify"
```
**Expected:** `200` with `audio_b64` and mastering report.

---

### T-14-3: Save mastered track
```bash
curl -X POST http://localhost:8000/mastering/save \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "audio_file=@mastered.mp3" \
  -F "project_id=$PROJECT_A_ID"
```
**Expected:** `200` with `output_url`.

---

### T-14-4 [CROSS-USER]: User B cannot save to User A's project
```bash
curl -X POST http://localhost:8000/mastering/save \
  -H "Authorization: Bearer $TOKEN_B" \
  -F "audio_file=@mastered.mp3" \
  -F "project_id=$PROJECT_A_ID"
```
**Expected:** `403 Project not found or access denied`

---

## T-15: Reference Track Matching

### T-15-1: Analyze reference (preview)
```bash
curl -X POST http://localhost:8000/reference-match/analyze \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "ref_file=@reference.mp3"
```
**Expected:** `200` with `reference_fingerprint` (bpm, key, mode), `projected_eq_bands`.

---

### T-15-2: Full reference match process
```bash
curl -X POST http://localhost:8000/reference-match/process \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "ref_file=@reference.mp3" \
  -F "target_file=@track.mp3"
```
**Expected:** `200` with `audio_b64` and `report` containing EQ bands applied, dynamics, stereo width.

---

### T-15-3: Vibe prompt from reference
```bash
curl -X POST http://localhost:8000/reference-match/vibe-prompt \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "ref_file=@reference.mp3"
```
**Expected:** `200` with `prompt` (MusicGPT-ready generation prompt) and `fingerprint`.

---

### T-15-4 [CROSS-USER]: User B cannot save to User A's project
```bash
curl -X POST http://localhost:8000/reference-match/save \
  -H "Authorization: Bearer $TOKEN_B" \
  -F "audio_file=@matched.mp3" \
  -F "project_id=$PROJECT_A_ID"
```
**Expected:** `403 Project not found or access denied`

---

## T-16: Podcast Producer

### T-16-1: Produce podcast episode
```bash
curl -X POST http://localhost:8000/podcast/produce \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "speech_file=@voiceover.mp3" \
  -F "music_file=@background.mp3" \
  -F "music_volume=0.25"
```
**Expected:** `200` with `audio_b64` (mixed episode).

---

### T-16-2: Save podcast
```bash
curl -X POST http://localhost:8000/podcast/save \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "audio_file=@episode.mp3" \
  -F "project_id=$PROJECT_A_ID"
```
**Expected:** `200` with `output_url`.

---

### T-16-3 [CROSS-USER]: User B cannot save to User A's project
```bash
curl -X POST http://localhost:8000/podcast/save \
  -H "Authorization: Bearer $TOKEN_B" \
  -F "audio_file=@episode.mp3" \
  -F "project_id=$PROJECT_A_ID"
```
**Expected:** `403 Project not found or access denied`

---

## T-17: Image-to-Song

### T-17-1: Generate from image URL
```bash
curl -X POST http://localhost:8000/image-to-song/generate \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "project_id=$PROJECT_A_ID" \
  -F "image_url=https://example.com/landscape.jpg" \
  -F "prompt=Calm acoustic inspired by this scene" \
  -F "make_instrumental=true"
```
**Expected:** `200` immediately with task_id. Poll `/download/` for completion.

---

### T-17-2: Generate from file upload
```bash
curl -X POST http://localhost:8000/image-to-song/generate \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "project_id=$PROJECT_A_ID" \
  -F "image_file=@photo.jpg" \
  -F "make_instrumental=false"
```
**Expected:** `200` immediately with task_id.

---

### T-17-3: Both image_url and image_file → 422
```bash
curl -X POST http://localhost:8000/image-to-song/generate \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "project_id=$PROJECT_A_ID" \
  -F "image_url=https://example.com/img.jpg" \
  -F "image_file=@photo.jpg"
```
**Expected:** `422` — cannot provide both.

---

## T-18: User Library

### T-18-1: Get full library
```bash
curl http://localhost:8000/library/ \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** `200` with all content sections:
- `tracks` — music_metadata rows
- `sounds` — sound_generations rows
- `separations` — audio_separations rows
- `albums` — albums rows
- `edits` — editing_table rows
- `lyrics` — lyrics from user_prompts
- `quick_ideas` — quick idea prompts
- `enhanced_prompts` — enhanced prompts
- `summary` — count per category

---

### T-18-2 [CROSS-USER]: User B sees only their own library
```bash
curl http://localhost:8000/library/ \
  -H "Authorization: Bearer $TOKEN_B"
```
**Expected:** User B's library is empty (or only User B's content). None of User A's tracks, albums, edits appear.

---

## T-19: Payment

### T-19-1: Plans list (public, no auth)
```bash
curl http://localhost:8000/payment/plans
```
**Expected:** `200` with free/starter/pro/unlimited plans including prices and token amounts.

---

### T-19-2: View own subscription
```bash
curl http://localhost:8000/payment/subscription \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** `200` with User A's plan, token balance, usage.

---

### T-19-3 [CROSS-USER]: User B sees own subscription only
```bash
curl http://localhost:8000/payment/subscription \
  -H "Authorization: Bearer $TOKEN_B"
```
**Expected:** User B's own subscription, NOT User A's. Different `user_id` in response.

---

### T-19-4: Checkout → 501 (not yet implemented)
```bash
curl -X POST http://localhost:8000/payment/checkout \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"plan_id": "pro_monthly"}'
```
**Expected:** `501 Not Implemented`

---

## T-20: Queue Health

### T-20-1: Health check (requires auth)
```bash
curl http://localhost:8000/queue/health \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** `200` with Redis status `ok`, Celery worker count.

---

### T-20-2: No auth → 401
```bash
curl http://localhost:8000/queue/health
```
**Expected:** `401 Authorization header required`

---

## T-21: Multi-User Concurrent Generation

### T-21-1: Two users generate simultaneously
In two terminals simultaneously:

**Terminal 1 (User A):**
```bash
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"'$PROJECT_A_ID'","type":"music","prompt":"User A track - jazz","make_instrumental":true}'
```

**Terminal 2 (User B):**
```bash
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Authorization: Bearer $TOKEN_B" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"'$PROJECT_B_ID'","type":"music","prompt":"User B track - rock","make_instrumental":true}'
```

**Expected:**
- Both return `200` instantly with different `task_id`s
- Both enter Celery queue independently
- When polled, each user only sees their own track
- Jobs process sequentially (concurrency=1) without mixing data

---

### T-21-2: Verify jobs do not mix
After both complete, poll each:

User A polls:
```bash
curl "http://localhost:8000/download/?task_id=$TASK_A" -H "Authorization: Bearer $TOKEN_A"
```
User B polls:
```bash
curl "http://localhost:8000/download/?task_id=$TASK_B" -H "Authorization: Bearer $TOKEN_B"
```

**Expected:** Each gets their own track. Cross-poll returns 404:
```bash
# User A tries to get User B's task → should 404
curl "http://localhost:8000/download/?task_id=$TASK_B" -H "Authorization: Bearer $TOKEN_A"
```

---

### T-21-3: Concurrent library reads
Both users hit `/library/` at the same time.  
**Expected:** Each sees only their own data. No bleed between responses.

---

## T-22: Token Balance

### T-22-1: Check balance before and after generation
```bash
# Before
curl http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN_A"
# note token_balance.balance

# Generate music (costs 10 tokens)
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"'$PROJECT_A_ID'","type":"music","prompt":"test","make_instrumental":true}'

# After generation completes, check balance again
curl http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** Balance decreased by 10 tokens after completion.

---

### T-22-2: Insufficient tokens → 402
Drain token balance by generating many tracks, then try again.  
**Expected:** `402 Insufficient tokens. Required: 10, available: X`

---

### T-22-3: Token refund on failure
If a generation job fails (e.g. MusicGPT returns an error), tokens should be refunded.  
Check balance before and after a failed job.  
**Expected:** Balance unchanged after failure.

---

## T-23: Edge Cases

### T-23-1: Download non-existent task_id → 404
```bash
curl "http://localhost:8000/download/?task_id=00000000-0000-0000-0000-000000000000" \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** `404 No tracks found`

---

### T-23-2: Album with non-existent album_id → 404
```bash
curl http://localhost:8000/album/00000000-0000-0000-0000-000000000000 \
  -H "Authorization: Bearer $TOKEN_A"
```
**Expected:** `404 Album not found`

---

### T-23-3: Invalid energy_preference → 422
```bash
curl -X POST http://localhost:8000/auto-edit/analyze \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@track.mp3" \
  -F "energy_preference=invalid_value"
```
**Expected:** `422` with valid options listed.

---

### T-23-4: Empty audio file → 422
```bash
curl -X POST http://localhost:8000/test-edit/cut \
  -H "Authorization: Bearer $TOKEN_A" \
  -F "file=@empty.mp3"
```
**Expected:** `422` or `500` with audio read error.

---

### T-23-5: Health check all systems
```bash
curl http://localhost:8000/health/detailed
```
**Expected:** All three checks green:
```json
{
  "status": "ok",
  "checks": {
    "database": {"status": "ok"},
    "redis": {"status": "ok"},
    "celery": {"status": "ok", "worker_count": 1}
  }
}
```

---

## Pass/Fail Tracker

| Test ID | Description | Pass | Fail | Notes |
|---------|-------------|------|------|-------|
| T-01-1 | No token → 401 | | | |
| T-01-2 | Invalid token → 401 | | | |
| T-01-3 | Expired token → 401 | | | |
| T-01-4 | Valid token → profile | | | |
| T-01-5 | First login auto-creates user | | | |
| T-02-1 | Create project | | | |
| T-02-2 | List own projects | | | |
| T-02-3 | **[CROSS]** User B can't see User A projects | | | |
| T-03-1 | Generate music | | | |
| T-03-2 | Poll to completion | | | |
| T-03-3 | **[CROSS]** User B can't access User A's track | | | |
| T-03-4 | Prompt too long → 422 | | | |
| T-04-1 | Remix own track | | | |
| T-04-2 | **[CROSS]** User B can't remix User A's track | | | |
| T-05-1 | Inpaint own track | | | |
| T-05-2 | **[CROSS]** User B can't inpaint User A's track | | | |
| T-06-1 | Extend own track | | | |
| T-06-2 | **[CROSS]** User B can't extend User A's track | | | |
| T-07-1 | Generate lyrics | | | |
| T-07-2 | **[CROSS]** User B library shows no User A lyrics | | | |
| T-08-1 | Quick idea | | | |
| T-08-2 | Prompt enhancer | | | |
| T-08-3 | Prompt enhancer custom master | | | |
| T-09-1 | Generate SFX | | | |
| T-09-2 | Poll sound status | | | |
| T-09-3 | Get sound after completion | | | |
| T-09-4 | **[CROSS]** User B can't access User A's sound | | | |
| T-10-1 | Separate stems | | | |
| T-10-2 | Poll separation status | | | |
| T-11-1 | Create album | | | |
| T-11-2 | Poll album planning | | | |
| T-11-3 | **[CROSS]** User B can't see User A's album | | | |
| T-11-4 | Approve album | | | |
| T-11-5 | Poll album progress | | | |
| T-11-6 | **[CROSS]** User B can't approve User A's album | | | |
| T-11-7 | **[CROSS]** User B can't replan User A's track | | | |
| T-11-8 | Approve with track edits | | | |
| T-11-9 | List albums (own only) | | | |
| T-12-1 | Cut | | | |
| T-12-2 | Fade | | | |
| T-12-3 | Warmth | | | |
| T-12-4 | Warmth analyze | | | |
| T-12-5 | Enhance presets (public) | | | |
| T-12-6 | Enhance apply | | | |
| T-12-7 | Save edit to cloud | | | |
| T-12-8 | **[CROSS]** User B can't save to User A's project | | | |
| T-13-1 | AIME analyze | | | |
| T-13-2 | AIME suggest | | | |
| T-13-3 | AIME preview | | | |
| T-13-4 | AIME full trim | | | |
| T-13-5 | AIME manual window override | | | |
| T-13-6 | AIME save | | | |
| T-13-7 | **[CROSS]** User B can't save AIME to User A's project | | | |
| T-14-1 | Mastering platforms (public) | | | |
| T-14-2 | Mastering process | | | |
| T-14-3 | Mastering save | | | |
| T-14-4 | **[CROSS]** User B can't save mastering to User A's project | | | |
| T-15-1 | Reference analyze | | | |
| T-15-2 | Reference match process | | | |
| T-15-3 | Reference vibe prompt | | | |
| T-15-4 | **[CROSS]** User B can't save reference match to User A's project | | | |
| T-16-1 | Podcast produce | | | |
| T-16-2 | Podcast save | | | |
| T-16-3 | **[CROSS]** User B can't save podcast to User A's project | | | |
| T-17-1 | Image-to-song URL | | | |
| T-17-2 | Image-to-song file | | | |
| T-17-3 | Both image inputs → 422 | | | |
| T-18-1 | Full library | | | |
| T-18-2 | **[CROSS]** User B sees only own library | | | |
| T-19-1 | Plans list (public) | | | |
| T-19-2 | Own subscription | | | |
| T-19-3 | **[CROSS]** User B sees own subscription only | | | |
| T-19-4 | Checkout → 501 | | | |
| T-20-1 | Queue health (auth required) | | | |
| T-20-2 | Queue health no auth → 401 | | | |
| T-21-1 | Two users generate simultaneously | | | |
| T-21-2 | Jobs don't mix data | | | |
| T-21-3 | Concurrent library reads isolated | | | |
| T-22-1 | Token balance deducted after generation | | | |
| T-22-2 | Insufficient tokens → 402 | | | |
| T-22-3 | Token refund on failure | | | |
| T-23-1 | Non-existent task_id → 404 | | | |
| T-23-2 | Non-existent album_id → 404 | | | |
| T-23-3 | Invalid energy_preference → 422 | | | |
| T-23-4 | Empty audio file → error | | | |
| T-23-5 | Health check all green | | | |

**Total:** 60 test cases — 20 are cross-user isolation tests `[CROSS]`
