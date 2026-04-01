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

## Type Values Reference

| `type` value | Use when |
|---|---|
| `music` | Full track — instrumental or song with vocals |
| `vocal` | Isolated vocals / voiceover only |
| `sfx` | Sound effects |
| `stem` | Individual stems (drums, bass, melody, etc.) |

---

## Sound Generation

All requests go to `POST /sound_generator/`. Only `project_id`, `user_id`, `user_name`, `user_email`, and `prompt` are required. The service stores one `music_metadata` row with `type = sfx` and processes the file asynchronously in the background.

### Temple Door Creak
```json
{
  "project_id": "proj_sfx_001",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "hemanth",
  "user_email": "hemanth@example.com",
  "prompt": "sound of an ancient temple door creaking open",
  "audio_length": 20
}
```

### Ambient Forest Night
```json
{
  "project_id": "proj_sfx_002",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "hemanth",
  "user_email": "hemanth@example.com",
  "prompt": "quiet nighttime forest ambience with insects, distant wind, and soft leaves rustling",
  "audio_length": 30
}
```

### With Webhook URL
```json
{
  "project_id": "proj_sfx_003",
  "user_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_name": "hemanth",
  "user_email": "hemanth@example.com",
  "prompt": "short sci-fi interface beep with a holographic feel",
  "webhook_url": "https://abcd.requestcatcher.com/",
  "audio_length": 5
}
```
