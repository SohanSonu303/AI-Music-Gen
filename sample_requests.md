# Sample Request Bodies — Music Generation

All requests go to `POST /music/`. Only `project_id`, `user_name`, `user_email`, `type`, and `prompt` are required.

---

## Instrumental Only

### Lo-fi / Chill Study Beat
```json
{
  "project_id": "proj_001",
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
  "user_name": "Sohan",
  "user_email": "sohan@example.com",
  "type": "music",
  "prompt": "Gritty cinematic score with low-frequency drones, razor-edged string textures, ticking clock percussion, and escalating tension layers, evoking chaos and psychological intensity, culminating in a massive orchestral and synth-driven climax",
  "music_style": "cinematic, hybrid orchestral, dark ambient, suspense",
  "make_instrumental": true,
  "output_length": 210
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
