# Sample Request Bodies

All endpoints require a Clerk JWT in the `Authorization` header:
```
Authorization: Bearer <clerk_jwt_token>
```
Get the token on the frontend: `await window.Clerk.session.getToken()`

`user_id`, `user_name`, and `user_email` are **never sent in the request body** — they are read from the JWT automatically.

---

## Auth

### GET /auth/me
Returns the logged-in user's profile, subscription, and token balance.
```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer <token>"
```

---

## Music Generation — POST /music/generateMusic

### Instrumental (Lo-fi)
```json
{
  "project_id": "proj_001",
  "type": "music",
  "prompt": "Relaxing lo-fi beat for studying with soft piano and vinyl crackle",
  "music_style": "lofi, chill, instrumental",
  "make_instrumental": true,
  "output_length": 120
}
```

### Cinematic Score
```json
{
  "project_id": "proj_002",
  "type": "music",
  "prompt": "Epic cinematic score for a battle scene with rising tension",
  "music_style": "cinematic, orchestral, epic",
  "make_instrumental": true,
  "output_length": 210
}
```

### Pop Song (Female Voice)
```json
{
  "project_id": "proj_003",
  "type": "music",
  "prompt": "Emotional pop ballad about missing someone",
  "music_style": "pop, ballad, emotional",
  "lyrics": "Verse 1: Every night I look up at the stars...\nChorus: I miss you more than words can say...",
  "gender": "female",
  "output_length": 200
}
```

### Vocal Only (Voiceover)
```json
{
  "project_id": "proj_004",
  "type": "vocal",
  "prompt": "Deep authoritative male voice for a documentary intro",
  "lyrics": "In a world where technology shapes every aspect of human life...",
  "vocal_only": true,
  "gender": "male"
}
```

**curl:**
```bash
curl -X POST http://localhost:8000/music/generateMusic \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"project_id":"proj_001","type":"music","prompt":"Lo-fi chill beat","make_instrumental":true}'
```

---

## Remix — POST /music/remix

```json
{ "id": "<source_music_metadata_uuid>" }
```

With style change:
```json
{
  "id": "<source_music_metadata_uuid>",
  "prompt": "Make it a dark cinematic lo-fi chill beat"
}
```

With lyrics/gender:
```json
{
  "id": "<source_music_metadata_uuid>",
  "prompt": "Transform into a soft R&B ballad",
  "lyrics": "Verse 1: Every night I look up at the stars...",
  "gender": "female"
}
```

---

## Inpaint — POST /inpaint/inpaint

```json
{
  "id": "<source_music_metadata_uuid>",
  "audio_url": "https://<supabase>/storage/v1/object/public/music-generated/...",
  "prompt": "Replace this section with a heavier guitar breakdown",
  "replace_start_at": 30.0,
  "replace_end_at": 60.0,
  "num_outputs": 2
}
```

With lyrics:
```json
{
  "id": "<source_music_metadata_uuid>",
  "audio_url": "https://<supabase>/storage/v1/...",
  "prompt": "Replace chorus with softer delivery",
  "replace_start_at": 45.0,
  "replace_end_at": 75.0,
  "lyrics_section_to_replace": "I miss you more than words can say...",
  "gender": "female",
  "num_outputs": 1
}
```

---

## Extend — POST /extend/extend

```json
{ "id": "<source_music_metadata_uuid>" }
```

---

## Lyrics Generation — POST /lyrics/generate

```json
{
  "prompt": "a love song about missing someone across the ocean",
  "style": "pop ballad",
  "mood": "melancholic",
  "theme": "long distance love",
  "tone": "soft and emotional"
}
```

Minimal:
```json
{ "prompt": "an upbeat summer anthem about freedom" }
```

---

## Quick Idea — POST /prompt/quick-idea

```json
{ "prompt": "a sad rainy night drive" }
```

---

## Prompt Enhancer — POST /prompt/enhance

```json
{ "prompt": "a chill lo-fi beat for studying" }
```

With custom master prompt:
```json
{
  "prompt": "an epic orchestral battle theme",
  "master_prompt": "You are a film score composer. Expand the user's prompt into a precise music brief including tempo, key, instrumentation, and dynamics arc."
}
```

---

## Sound Generation — POST /sound_generator/

```json
{
  "project_id": "proj_001",
  "prompt": "Thunder rumbling in the distance with light rain",
  "audio_length": 10
}
```

### Get Sound — GET /sound_generator/
```bash
curl "http://localhost:8000/sound_generator/?task_id=<task_id>" \
  -H "Authorization: Bearer <token>"
```

### Sound Status — GET /sound_generator/status
```bash
curl "http://localhost:8000/sound_generator/status?task_id=<task_id>" \
  -H "Authorization: Bearer <token>"
```

---

## Stem Separation — POST /separate/

```bash
curl -X POST http://localhost:8000/separate/ \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/song.mp3" \
  -F "project_id=proj_001"
```

---

## Download — GET /download/

```bash
curl "http://localhost:8000/download/?task_id=<stable_task_id>" \
  -H "Authorization: Bearer <token>"
```

---

## User Library — GET /library/

Returns all music, sounds, albums, edits, separations, lyrics, and prompts for the logged-in user.

```bash
curl http://localhost:8000/library/ \
  -H "Authorization: Bearer <token>"
```

---

## Projects — POST /projects/ · GET /projects/

```json
{ "project_name": "My Film Score", "created_by": "Sohan" }
```

```bash
curl http://localhost:8000/projects/ \
  -H "Authorization: Bearer <token>"
```

---

## Album Generation

### Step 1 — Create Album — POST /album/create

```json
{
  "project_id": "proj_001",
  "script": "Act 1: A young soldier stands at the border at dawn, full of hope. Act 2: Months later, he witnesses the destruction of his hometown and loses his closest friend. Act 3: The war ends. He returns home to find a new child born in his absence and finds a reason to continue.",
  "songs": 2,
  "background_scores": 1,
  "instrumentals": 0
}
```

Pure instrumental:
```json
{
  "project_id": "proj_002",
  "script": "Scene 1: A lone traveler walks through a vast desert at sunrise. Scene 2: A sandstorm engulfs the path. Scene 3: The storm clears to reveal an ancient buried city.",
  "songs": 0,
  "background_scores": 1,
  "instrumentals": 2
}
```

### Step 2 — Poll — GET /album/{album_id}
Poll every 5–10s until `status == "PLANNED"`.

### Step 3 — Approve — PUT /album/{album_id}/approve

Accept as-is:
```json
{}
```

With track edits:
```json
{
  "track_updates": [
    {
      "id": "<track-uuid>",
      "prompt": "Tender orchestral ballad with solo cello",
      "gender": "male"
    }
  ]
}
```

### Step 4 — Poll Progress — GET /album/{album_id}/progress
Poll every 15–30s until `status == "COMPLETED"`.

### Step 5 — Fetch Result — GET /album/{album_id}

### Step 6 (optional) — Replan Track — PUT /album/{album_id}/tracks/{track_id}/replan
```json
{}
```
With custom excerpt:
```json
{
  "custom_script_excerpt": "He loses his closest friend. The sky turns red. He screams into the void."
}
```

### Step 7 (optional) — Regenerate Track Audio — PUT /album/{album_id}/tracks/{track_id}/regenerate
No body required.

### Retry Failed Album — PUT /album/{album_id}/approve
Same as approve — only non-COMPLETED tracks are re-submitted.

### All User Albums — GET /album/user

---

## Image-to-Song — POST /image-to-song/generate

With image URL:
```bash
curl -X POST http://localhost:8000/image-to-song/generate \
  -H "Authorization: Bearer <token>" \
  -F "project_id=proj_001" \
  -F "image_url=https://mybucket.s3.amazonaws.com/image.png" \
  -F "prompt=Generate a relaxing acoustic track inspired by this scene." \
  -F "make_instrumental=false"
```

With file upload:
```bash
curl -X POST http://localhost:8000/image-to-song/generate \
  -H "Authorization: Bearer <token>" \
  -F "project_id=proj_002" \
  -F "image_file=@/path/to/image.png" \
  -F "prompt=Cinematic track with soft strings and piano." \
  -F "make_instrumental=true"
```

---

## Audio Editing — POST /test-edit/{op}

All edit endpoints accept `file` (upload) or `url` (string form field) as audio source.

### Cut
```bash
curl -X POST http://localhost:8000/test-edit/cut \
  -H "Authorization: Bearer <token>" \
  -F "file=@track.mp3" \
  -F "start_ms=0" -F "end_ms=30000"
```

### Fade
```bash
curl -X POST http://localhost:8000/test-edit/fade \
  -H "Authorization: Bearer <token>" \
  -F "file=@track.mp3" \
  -F "fade_in_ms=1000" -F "fade_out_ms=2000"
```

### Warmth (AI Analog)
```bash
curl -X POST http://localhost:8000/test-edit/warmth \
  -H "Authorization: Bearer <token>" \
  -F "file=@track.mp3" \
  -F "intensity=0.6" -F "vocal_mode=false"
```

### Style Enhancer
```bash
curl -X POST http://localhost:8000/test-edit/enhance \
  -H "Authorization: Bearer <token>" \
  -F "file=@track.mp3" \
  -F "preset=lofi" -F "intensity=0.7"
```
Presets: `lofi` · `edm` · `cinematic` · `pop` · `chill` · `vintage`

### Save to Cloud — POST /test-edit/save
```bash
curl -X POST http://localhost:8000/test-edit/save \
  -H "Authorization: Bearer <token>" \
  -F "file=@processed.mp3" \
  -F "user_id=<uuid>" -F "project_id=proj_001" \
  -F "operation=warmth" -F "output_format=mp3"
```

---

## AIME (Auto Trim) — POST /auto-edit/...

### Analyze
```bash
curl -X POST http://localhost:8000/auto-edit/analyze \
  -H "Authorization: Bearer <token>" \
  -F "file=@track.mp3" \
  -F "target_duration=30" -F "energy_preference=drop"
```

### Suggest (natural language → params)
```bash
curl -X POST http://localhost:8000/auto-edit/suggest \
  -F "description=punchy 30 second drop for a DJ mix"
```

### Preview (find best section, no encoding)
```bash
curl -X POST http://localhost:8000/auto-edit/preview \
  -H "Authorization: Bearer <token>" \
  -F "file=@track.mp3" \
  -F "target_duration=30" -F "energy_preference=drop" \
  -F "description=punchy drop"
```

### Trim (full pipeline, returns base64 audio)
```bash
curl -X POST http://localhost:8000/auto-edit/trim \
  -H "Authorization: Bearer <token>" \
  -F "file=@track.mp3" \
  -F "target_duration=30" -F "energy_preference=drop" \
  -F "crossfade_beats=1"
```

---

## Payment

### Plans — GET /payment/plans
```bash
curl http://localhost:8000/payment/plans
```

### Checkout — POST /payment/checkout
```bash
curl -X POST http://localhost:8000/payment/checkout \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"plan_id": "pro_monthly"}'
```

### Subscription — GET /payment/subscription
```bash
curl http://localhost:8000/payment/subscription \
  -H "Authorization: Bearer <token>"
```

---

## Type Values Reference

| `type` | Use when |
|---|---|
| `music` | Full track — instrumental or song with vocals |
| `vocal` | Isolated vocals / voiceover only |
| `sfx` | Sound effects |
| `stem` | Individual stems |
