# Sample Request Bodies — Music Generation & Lyrics

---

## Lyrics Generation

All requests go to `POST /lyrics/generate`. Only `user_id`, `user_name`, and `prompt` are required. Optional fields (`style`, `mood`, `theme`, `tone`) are appended to the prompt sent to MusicGPT. Generated lyrics are stored in the `prompt` column of `lyrics_metadata`.

### Love Song Lyrics
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "a love song about missing someone across the ocean",
  "style": "pop ballad",
  "mood": "melancholic",
  "theme": "long distance love",
  "tone": "soft and emotional"
}
```

### Hip-Hop / Rap Lyrics
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "a rap about grinding and rising from nothing",
  "style": "hip-hop",
  "mood": "motivated",
  "theme": "hustle and success",
  "tone": "aggressive and confident"
}
```

### Minimal (prompt only)
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "an upbeat summer anthem about freedom"
}
```

---

## Music Generation

All requests go to `POST /music/generateMusic`. Only `project_id`, `user_id`, `user_name`, `user_email`, `type`, and `prompt` are required.

---

## Instrumental Only

### Lo-fi / Chill Study Beat
```json
{
  "project_id": "proj_001",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Relaxing lo-fi beat for studying with soft piano and vinyl crackle",
  "music_style": "lofi, chill, instrumental",
  "make_instrumental": true,
  "output_length": 120
}
```

### Cinematic / Epic Score
```json
{
  "project_id": "proj_002",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Epic cinematic background score for a battle scene with rising tension",
  "music_style": "cinematic, orchestral, epic",
  "make_instrumental": true,
  "output_length": 210
}
```

### Ambient / Background
```json
{
  "project_id": "proj_003",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Soft ambient soundscape with nature sounds and gentle pads for meditation",
  "music_style": "ambient, meditation, calm",
  "make_instrumental": true,
  "output_length": 180
}
```

### EDM / Festival Drop
```json
{
  "project_id": "proj_004",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "High-energy EDM track with a massive bass drop and euphoric synths",
  "music_style": "EDM, festival, bass-heavy",
  "make_instrumental": true,
  "output_length": 90
}
```

### Jazz / Café
```json
{
  "project_id": "proj_005",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Smooth jazz with upright bass and brushed drums for a cozy café atmosphere",
  "music_style": "jazz, smooth, upright bass",
  "make_instrumental": true,
  "output_length": 150
}
```

---

## Songs with Vocals

### Pop Song (Male Voice)
```json
{
  "project_id": "proj_006",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Catchy pop song about chasing dreams and never giving up",
  "music_style": "pop, upbeat, radio-friendly",
  "lyrics": "Verse 1: I was walking through the fire...\nChorus: I'm never gonna stop, I'm chasing every dream...",
  "gender": "male",
  "output_length": 180
}
```

### Pop Song (Female Voice)
```json
{
  "project_id": "proj_007",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Emotional pop ballad about missing someone you love",
  "music_style": "pop, ballad, emotional",
  "lyrics": "Verse 1: Every night I look up at the stars...\nChorus: I miss you more than words can say...",
  "gender": "female",
  "output_length": 200
}
```

### Hip-Hop / Rap
```json
{
  "project_id": "proj_008",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Hard-hitting hip-hop track about grinding and success",
  "music_style": "hip-hop, trap, hard",
  "lyrics": "Verse 1: Started from the bottom now we climbing every day...\nChorus: Hustle never stops, I grind until I make it...",
  "gender": "male",
  "output_length": 160
}
```

### R&B / Soul
```json
{
  "project_id": "proj_009",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Smooth R&B love song with soulful vocals and warm chords",
  "music_style": "R&B, soul, romantic",
  "lyrics": "Verse 1: From the moment I saw you I knew...\nChorus: Girl you're everything I've been searching for...",
  "gender": "male",
  "output_length": 190
}
```

### Rock Anthem
```json
{
  "project_id": "proj_010",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Powerful rock anthem with electric guitars and driving drums",
  "music_style": "rock, anthem, electric guitar",
  "lyrics": "Verse 1: We rise up when the world tries to hold us down...\nChorus: We're alive, we're burning bright tonight...",
  "gender": "male",
  "output_length": 200
}
```

---

## Vocal Only (No Music)

### Voiceover / Narration
```json
{
  "project_id": "proj_011",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "vocal",
  "prompt": "Deep authoritative male voice for a documentary intro",
  "lyrics": "In a world where technology shapes every aspect of human life...",
  "vocal_only": true,
  "gender": "male"
}
```

### Soft Female Vocal Hook
```json
{
  "project_id": "proj_012",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "vocal",
  "prompt": "Breathy, soft female vocal hook for a chill pop song",
  "lyrics": "Oh, stay a little longer with me tonight...",
  "vocal_only": true,
  "gender": "female"
}
```

```json
{
  "project_id": "1",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Gritty cinematic score with low-frequency drones, razor-edged string textures, ticking clock percussion, and escalating tension layers, evoking chaos and psychological intensity, culminating in a massive orchestral and synth-driven climax",
  "music_style": "cinematic, hybrid orchestral, dark ambient, suspense",
  "make_instrumental": true,
  "output_length": 210
}
```

```json
{
  "project_id": "1",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Jhon",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "love song about chasing dreams and never giving up",
  "music_style": "sad, romantic",
  "lyrics": "[Verse]\nThe floorboards still hold the weight of your shadow\nA ghost in the corner where the light used to bend\nI trace the cold outline of every hollow promise\nAnd wonder exactly when the beginning met the end\nThe coffee sits bitter in a cup made for two\nWhile the rain writes a ledger on the window pane\nEvery photograph is a wound that refuses to close\nAnd I am the only one left to shoulder the stain\n\n[Pre-Chorus]\nI am memorizing the silence you left behind\nTranslating the distance between your heart and mine\nThe clocks have all frozen in the heat of the fray\nWhile I try to scrub the scent of your ghost away\n\n[Chorus]\nThis is the ache of a bridge burned while standing upon it\nA slow-motion tumble through a sky painted grey\nI gave you the marrow and the breath from my lungs\nOnly to watch you just crumble and drift far away\nIt is the heavy pull of a tide that has turned\nThe salt in the stitches of a lesson unlearned\nI am drowning in the shallow end of our history\nWhile you sail on toward a brand new mystery\n\n[Verse]\nThe closet is empty but the hangers still rattle\nLike skeletal fingers reaching out for the latch\nI found a stray button from the coat that you wore\nA tiny plastic relic that I cannot detach\nThe neighbors are talking through the thin plaster walls\nAbout seasons and reason and the coming of snow\nBut they do not know the way a soul starts to fray\nWhen it has no direction and nowhere to go\n\n[Pre-Chorus]\nI am memorizing the silence you left behind\nTranslating the distance between your heart and mine\nThe clocks have all frozen in the heat of the fray\nWhile I try to scrub the scent of your ghost away\n\n[Chorus]\nThis is the ache of a bridge burned while standing upon it\nA slow-motion tumble through a sky painted grey\nI gave you the marrow and the breath from my lungs\nOnly to watch you just crumble and drift far away\nIt is the heavy pull of a tide that has turned\nThe salt in the stitches of a lesson unlearned\nI am drowning in the shallow end of our history\nWhile you sail on toward a brand new mystery\n\n[Chorus]\nThis is the ache of a bridge burned while standing upon it\nA slow-motion tumble through a sky painted grey\nI gave you the marrow and the breath from my lungs\nOnly to watch you just crumble and drift far away\nIt is the heavy pull of a tide that has turned\nThe salt in the stitches of a lesson unlearned\nI am drowning in the shallow end of our history\nWhile you sail on toward a brand new mystery\n\n[Chorus]\nThis is the ache of a bridge burned while standing upon it\nA slow-motion tumble through a sky painted grey\nI gave you the marrow and the breath from my lungs\nOnly to watch you just crumble and drift far away\nIt is the heavy pull of a tide that has turned\nThe salt in the stitches of a lesson unlearned\nI am drowning in the shallow end of our history\nWhile you sail on toward a brand new mystery\n\n[Outro]",
  "gender": "male",
  "output_length": 180
}

```
---

---

## Inpaint

All requests go to `POST /inpaint/inpaint`. Required fields: `id` (source `music_metadata` UUID), `user_id`, `audio_url`, `prompt`, `replace_start_at`, `replace_end_at`. Optional: `lyrics`, `lyrics_section_to_replace`, `gender`, `num_outputs`. Returns 2 new rows immediately with `is_cloned` set to the source `id`; background polling completes them the same way as music generation.

### Inpaint Instrumental — Replace a Section with Different Style
```json
{
  "id": "fd508668-0bda-4805-a515-93063c4b7364",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "audio_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../task-xyz-123/conv-abc-001.mp3",
  "prompt": "Replace this section with a heavier, distorted guitar breakdown",
  "replace_start_at": 30.0,
  "replace_end_at": 60.0,
  "num_outputs": 2
}
```

### Inpaint Vocal Track — Replace Chorus Lyrics and Vocalist
```json
{
  "id": "fd508668-0bda-4805-a515-93063c4b7364",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "audio_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../task-xyz-123/conv-abc-001.mp3",
  "prompt": "Replace the chorus with a softer, more emotional delivery",
  "replace_start_at": 45.0,
  "replace_end_at": 75.0,
  "lyrics": "Verse 1: Every night I look up at the stars...\nChorus: I miss you more than words can say...",
  "lyrics_section_to_replace": "I miss you more than words can say...",
  "gender": "female",
  "num_outputs": 2
}
```

---

## Stem Separation

All requests go to `POST /separate/` as `multipart/form-data`. Required fields: `file` (audio upload), `user_id`, `project_id`. Returns a job immediately with `status: PENDING`; processing runs in the background. Poll the `audio_separations` table by `id` to check progress.

On completion, four stem URLs are populated: `vocals_url`, `drums_url`, `bass_url`, `other_url`.

### cURL — Basic MP3 Separation
```bash
curl -X POST http://localhost:8000/separate/ \
  -F "file=@/path/to/song.mp3" \
  -F "user_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -F "project_id=proj_001"
```

### cURL — WAV File
```bash
curl -X POST http://localhost:8000/separate/ \
  -F "file=@/path/to/track.wav" \
  -F "user_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890" \
  -F "project_id=proj_002"
```

### cURL — Different Project
```bash
curl -X POST http://localhost:8000/separate/ \
  -F "file=@/path/to/beat.mp3" \
  -F "user_id=b9c8d7e6-f5a4-3210-fedc-ba9876543210" \
  -F "project_id=proj_remix_01"
```

### Expected Response (immediate)
```json
{
  "id": "e3f1a2b4-7c89-4d56-a012-3e4f5a6b7c8d",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "project_id": "proj_001",
  "original_filename": "song.mp3",
  "status": "PENDING",
  "vocals_url": null,
  "drums_url": null,
  "bass_url": null,
  "other_url": null,
  "error_message": null,
  "created_at": "2026-03-29T10:00:00Z"
}
```

### Expected Response (after completion)
```json
{
  "id": "e3f1a2b4-7c89-4d56-a012-3e4f5a6b7c8d",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "project_id": "proj_001",
  "original_filename": "song.mp3",
  "status": "COMPLETED",
  "vocals_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../proj_001/e3f1a2b4-.../vocals.wav",
  "drums_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../proj_001/e3f1a2b4-.../drums.wav",
  "bass_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../proj_001/e3f1a2b4-.../bass.wav",
  "other_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../proj_001/e3f1a2b4-.../other.wav",
  "error_message": null,
  "created_at": "2026-03-29T10:00:00Z"
}
```

---

## Download Music Tracks

Fetch both generated tracks for a given `task_id`. Sent as a `GET` request with query parameters.

### cURL
```bash
curl -X GET "http://localhost:8000/download/?user_id=a1b2c3d4-e5f6-7890-abcd-ef1234567890&task_id=task-xyz-123"
```

### Expected Response (tracks still processing)
```json
{
  "task_id": "task-xyz-123",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "tracks": [
    {
      "conversion_id": "conv-abc-001",
      "status": "IN_QUEUE",
      "title": null,
      "audio_url": null,
      "duration": null,
      "album_cover_path": null,
      "generated_lyrics": null
    },
    {
      "conversion_id": "conv-abc-002",
      "status": "IN_QUEUE",
      "title": null,
      "audio_url": null,
      "duration": null,
      "album_cover_path": null,
      "generated_lyrics": null
    }
  ]
}
```

### Expected Response (tracks completed)
```json
{
  "task_id": "task-xyz-123",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "tracks": [
    {
      "conversion_id": "conv-abc-001",
      "status": "COMPLETED",
      "title": "Chasing Dreams",
      "audio_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../task-xyz-123/conv-abc-001.mp3",
      "duration": 180.0,
      "album_cover_path": "https://...",
      "generated_lyrics": "Verse 1: ..."
    },
    {
      "conversion_id": "conv-abc-002",
      "status": "COMPLETED",
      "title": "Chasing Dreams (Alt)",
      "audio_url": "https://<supabase>/storage/v1/object/public/music-generated/a1b2c3d4-.../task-xyz-123/conv-abc-002.mp3",
      "duration": 182.0,
      "album_cover_path": "https://...",
      "generated_lyrics": "Verse 1: ..."
    }
  ]
}
```

---

## Remix

All requests go to `POST /music/remix`. Only `id` (source `music_metadata` UUID with a completed `audio_url`) is required. Optional `prompt` overrides the source track's prompt; if omitted, the original prompt is reused. Provide `lyrics` for vocal tracks; omit for instrumentals/background scores.

### Remix Instrumental — Style Change
```json
{
  "id": "fd508668-0bda-4805-a515-93063c4b7364",
  "prompt": "Make it sound like a dark cinematic lo-fi chill beat"
}
```

### Remix Instrumental — No Prompt Override (reuse original)
```json
{
  "id": "fd508668-0bda-4805-a515-93063c4b7364"
}
```

### Remix Vocal Track — With Lyrics and Gender
```json
{
  "id": "fd508668-0bda-4805-a515-93063c4b7364",
  "prompt": "Transform into a soft R&B ballad",
  "lyrics": "Verse 1: Every night I look up at the stars...\nChorus: I miss you more than words can say...",
  "gender": "female"
}
```

---

## Quick Idea Generation

All requests go to `POST /prompt/quick-idea`. Required fields: `user_id`, `user_name`, `prompt`. Returns an AI-generated music concept/idea stored in the `prompt` column of `user_prompts` with `feature_type: "quick_idea"`.

### Basic Idea from Short Prompt
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "a sad rainy night drive"
}
```

### Genre-Hinted Idea
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "something dark and electronic for a thriller film"
}
```

### Vibe-Only Idea
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "euphoric summer festival energy"
}
```

---

## Prompt Enhancer

All requests go to `POST /prompt/enhance`. Required fields: `user_id`, `user_name`, `prompt`. Optional: `master_prompt` — if omitted, the system uses the default master prompt from `prompts/musicenhancerprompt.md`. Returns an enhanced, detailed prompt stored in `user_prompts` with `feature_type: "prompt_enhanced"`.

### Enhance Without Master Prompt (uses default)
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "a chill lo-fi beat for studying"
}
```

### Enhance With Custom Master Prompt
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "an epic orchestral battle theme",
  "master_prompt": "You are a film score composer. Expand the user's prompt into a precise, production-ready music brief including tempo (BPM), key, instrumentation, dynamics arc, and reference composers."
}
```

### Enhance a Simple Mood
```json
{
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "prompt": "happy upbeat morning vibes"
}
```

---

## Type Values Reference

| `type` value | Use when |
|---|---|
| `music` | Full track — instrumental or song with vocals |
| `vocal` | Isolated vocals / voiceover only |
| `sfx` | Sound effects |
| `stem` | Individual stems (drums, bass, melody, etc.) |

---

---

## Album Generation

A full AI-planned album from a script. The flow has two phases: **AI Planning** (async) → **Music Generation** (Celery workers).

### User Flow

```
POST /album/create
        ↓ (returns immediately, status=PLANNING)
Poll GET /album/{album_id}
        ↓ (wait until status=PLANNED — AI agent segments script, writes prompts + lyrics)
Review track suggestions in response
        ↓ (optionally edit tracks)
PUT /album/{album_id}/approve
        ↓ (returns immediately, status=GENERATING, Celery workers start)
Poll GET /album/{album_id}/progress
        ↓ (wait until status=COMPLETED)
GET /album/{album_id}
        ↓ (full album with all tracks + audio_urls)
```

---

### Step 1 — Create Album

`POST /album/create`

#### Film Score Album (2 songs + 1 background score)
```json
{
  "project_id": "proj_001",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "script": "Act 1: A young soldier stands at the border of a war-torn city at dawn, full of hope and resolve. He writes a letter to his family. Act 2: Months later, the soldier witnesses the destruction of his hometown. He loses his closest friend in battle. The mood shifts to grief and rage. Act 3: The war ends. The soldier returns home to silence — his family gone, but a new child born in his absence. He holds the baby and finds a reason to continue.",
  "songs": 2,
  "background_scores": 1,
  "instrumentals": 0
}
```

#### Pure Instrumental Album (3 tracks)
```json
{
  "project_id": "proj_002",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "script": "Scene 1: A lone traveler walks through a vast desert at sunrise, peaceful and unhurried. Scene 2: A sudden sandstorm engulfs the path — visibility drops to zero, tension rises. Scene 3: The storm clears to reveal an ancient city buried in sand, hauntingly beautiful.",
  "songs": 0,
  "background_scores": 1,
  "instrumentals": 2
}
```

#### Mixed Album (1 song + 1 background score + 1 instrumental)
```json
{
  "project_id": "proj_003",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "script": "Opening: The city never sleeps — neon lights, crowded streets, a woman searches for someone she lost years ago. Middle: She finds a clue at an old jazz bar; a bartender remembers a name. Ending: She finds him — older, broken, but alive. They sit in silence as the rain falls outside.",
  "songs": 1,
  "background_scores": 1,
  "instrumentals": 1
}
```

**Expected response (immediate):**
```json
{
  "id": "4ecc36af-8aae-4f40-8c1b-73f79f9342fd",
  "status": "PLANNING",
  "title": null,
  "tracks": [],
  "created_at": "2026-04-04T12:00:00Z"
}
```

---

### Step 2 — Poll Until Planned

`GET /album/4ecc36af-8aae-4f40-8c1b-73f79f9342fd`

Poll every 5–10 seconds. When `status == "PLANNED"` the response includes all track suggestions:

```json
{
  "id": "4ecc36af-8aae-4f40-8c1b-73f79f9342fd",
  "title": "Echoes of the Fallen",
  "status": "PLANNED",
  "style_palette": "{\"primary_genre\":\"cinematic\",\"bpm_range\":\"60-90\",\"key_signature\":\"D minor\",\"instrumentation_family\":\"orchestral + piano\",\"mood_arc\":\"hopeful → grief → redemption\"}",
  "tracks": [
    {
      "id": "track-uuid-1",
      "track_number": 1,
      "track_type": "song",
      "scene_description": "A soldier at dawn, full of hope, writing to his family",
      "script_excerpt": "A young soldier stands at the border...",
      "suggested_style": "orchestral pop",
      "suggested_mood": "hopeful, tender",
      "suggested_tempo": "slow ballad ~70 BPM",
      "prompt": "Orchestral pop ballad, tender piano melody, soft strings, hopeful male vocals, dawn atmosphere",
      "music_style": "orchestral pop, cinematic, piano-led",
      "lyrics": "Verse 1:\nI write your name in the morning light...",
      "make_instrumental": false,
      "energy_level": 4,
      "music_metadata_id": null,
      "music_metadata_id_2": null,
      "task_id": null,
      "status": "PENDING"
    },
    {
      "id": "track-uuid-2",
      "track_number": 2,
      "track_type": "background_score",
      "scene_description": "Battle and destruction, loss of a friend",
      "suggested_style": "dark cinematic",
      "suggested_mood": "grief, tension, rage",
      "suggested_tempo": "driving mid-tempo ~100 BPM",
      "prompt": "Dark cinematic score, distorted low strings, war drums, rising tension, no vocals",
      "music_style": "cinematic, dark orchestral, percussive",
      "make_instrumental": true,
      "energy_level": 9,
      "status": "PENDING"
    },
    {
      "id": "track-uuid-3",
      "track_number": 3,
      "track_type": "song",
      "scene_description": "Soldier returns to silence, finds new life to live for",
      "suggested_mood": "bittersweet, redemptive",
      "prompt": "Bittersweet orchestral ballad, swelling strings, emotional male vocals, quiet beginning builds to hopeful climax",
      "make_instrumental": false,
      "energy_level": 6,
      "status": "PENDING"
    }
  ]
}
```

---

### Step 3 — Approve (accept as-is or edit tracks)

`PUT /album/4ecc36af-8aae-4f40-8c1b-73f79f9342fd/approve`

#### Accept all AI suggestions without changes
```json
{}
```

#### Approve with edits to specific tracks
```json
{
  "track_updates": [
    {
      "id": "track-uuid-1",
      "prompt": "Tender orchestral ballad with solo cello and soft male vocals, dawn light atmosphere",
      "gender": "male"
    },
    {
      "id": "track-uuid-3",
      "lyrics": "Verse 1:\nI came home to silence and a child I'd never met...\nChorus: But you give me a reason, you give me a reason to stay...",
      "gender": "male",
      "output_length": 210
    }
  ]
}
```

**Expected response (immediate, generation started):**
```json
{
  "id": "4ecc36af-8aae-4f40-8c1b-73f79f9342fd",
  "status": "GENERATING",
  "tracks": [
    { "track_number": 1, "status": "PENDING" },
    { "track_number": 2, "status": "PENDING" },
    { "track_number": 3, "status": "PENDING" }
  ]
}
```

---

### Step 4 — Poll Progress

`GET /album/4ecc36af-8aae-4f40-8c1b-73f79f9342fd/progress`

Poll every 15–30 seconds while `status == "GENERATING"`:

```json
{
  "album_id": "4ecc36af-8aae-4f40-8c1b-73f79f9342fd",
  "status": "GENERATING",
  "tracks_completed": 1,
  "tracks_total": 3,
  "tracks": [
    { "track_number": 1, "status": "COMPLETED" },
    { "track_number": 2, "status": "IN_QUEUE" },
    { "track_number": 3, "status": "PENDING" }
  ]
}
```

---

### Step 5 — Fetch Completed Album

`GET /album/4ecc36af-8aae-4f40-8c1b-73f79f9342fd`

When `status == "COMPLETED"`, fetch the full album. Each track has two generated versions:

| Field | Description |
|---|---|
| `music_metadata_id` | First conversion — use `task_id` with `GET /download/` to fetch both tracks |
| `music_metadata_id_2` | Second conversion — same `task_id`, different `conversion_id` |

MusicGPT always generates 2 variations per submission. Both are stored in `music_metadata` under the same `task_id`. Use `GET /download/?user_id=<id>&task_id=<task_id>` to retrieve both audio URLs at once.

---

### Step 6 (optional) — Re-plan a Track

Use while album is `PLANNED` to regenerate AI suggestions for one track.

`PUT /album/4ecc36af-8aae-4f40-8c1b-73f79f9342fd/tracks/track-uuid-2/replan`

#### Regenerate using same script section (no body needed)
```json
{}
```

#### Replan with a different script excerpt
```json
{
  "custom_script_excerpt": "He loses his closest friend in battle. The sky turns red. He screams into the void, voice breaking."
}
```

---

### Step 7 (optional) — Regenerate a Track's Audio

Use after generation has started (`GENERATING` or `COMPLETED`) to re-submit one track to MusicGPT.

`PUT /album/4ecc36af-8aae-4f40-8c1b-73f79f9342fd/tracks/track-uuid-2/regenerate`

No body required. Returns the updated track with `status: PENDING`.

---

### Retry Failed Album

If `status == "FAILED"` (e.g. due to MusicGPT rate limit or network error), re-call approve:

`PUT /album/4ecc36af-8aae-4f40-8c1b-73f79f9342fd/approve`

Only tracks that are NOT already `COMPLETED` will be re-submitted. Already completed tracks are skipped.

---

### Get All Albums for a User

`GET /album/user/a1b2c3d4-e5f6-7890-abcd-ef1234567890`

Returns a list of all albums with their tracks, ordered by `created_at` descending.
