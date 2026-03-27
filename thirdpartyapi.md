# MusicGPT Third-Party API Reference

## Base URL
```
https://api.musicgpt.com/api/public/v1
```

## Authentication
All requests require an `Authorization` header:
```
Authorization: <MUSICGPT_API_KEY>
```
Store the key in `.env` as `MUSICGPT_API_KEY`.

---

## Generate Music

**`POST /MusicAI`**

Submits a music generation job. The job is processed asynchronously — use the returned `task_id` and `conversion_id` to poll for results.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | yes | Text description of the music to generate |
| `music_style` | string | no | Style/genre (e.g. `"Pop"`, `"Jazz"`) |
| `lyrics` | string | no | Lyrics to use in the song |
| `make_instrumental` | bool | no | Generate without vocals |
| `vocal_only` | bool | no | Return only the vocal track |
| `gender` | string | no | Vocalist gender |
| `voice_id` | string | no | Specific voice preset ID |
| `output_length` | int | no | Target length in seconds |
| `webhook_url` | string | no | URL to POST results to when complete |

### Response

```json
{
  "success": true,
  "message": "Message published to queue",
  "task_id": "<uuid>",
  "conversion_id_1": "<uuid>",
  "conversion_id_2": "<uuid>",
  "eta": 154
}
```

| Field | Description |
|---|---|
| `task_id` | Identifier for the overall job — save this to poll status |
| `conversion_id_1` / `conversion_id_2` | Individual conversion IDs within the job |
| `eta` | Estimated processing time in seconds |

---

## Check Status

**`GET /byId`**

Polls the status of a conversion job.

### Query parameters

| Param | Required | Description |
|---|---|---|
| `conversionType` | yes | Must be `MUSIC_AI` for music generation. Other supported values: `TEXT_TO_SPEECH`, `VOICE_CONVERSION`, `COVER`, `EXTRACTION`, `DENOISING`, `DEECHO`, `DEREVERB`, `SOUND_GENERATOR`, `AUDIO_TRANSCRIPTION`, `AUDIO_SPEED_CHANGER`, `AUDIO_MASTERING`, `AUDIO_CUTTER`, `REMIX`, `FILE_CONVERT`, `KEY_BPM_EXTRACTION`, `AUDIO_TO_MIDI`, `EXTEND`, `INPAINT`, `SING_OVER_INSTRUMENTAL`, `LYRICS_GENERATOR`, `STEMS_SEPARATION`, `VOCAL_EXTRACTION` |
| `task_id` | yes | The `task_id` from the generate response |
| `conversion_id` | yes | The `conversion_id_1` or `conversion_id_2` from the generate response |

### Response

The response always contains the full task object with both conversions. Match `conversion_id_1`/`conversion_id_2` in the response to determine which `conversion_path_N` belongs to the conversion you're polling.

```json
{
  "success": true,
  "conversion": {
    "task_id": "<uuid>",
    "conversion_id_1": "<uuid>",
    "conversion_id_2": "<uuid>",
    "status": "COMPLETED",
    "message": "Both conversions received",
    "music_style": "cinematic, orchestral, epic",
    "title_1": "Clash of Titans",
    "title_2": "Clash of Titans",
    "conversion_path_1": "https://lalals.s3.amazonaws.com/conversions/.../<conversion_id_1>.mp3",
    "conversion_path_2": "https://lalals.s3.amazonaws.com/conversions/.../<conversion_id_2>.mp3",
    "conversion_duration_1": 209.84,
    "conversion_duration_2": 232.99,
    "album_cover_path": "https://musicgpt.s3.amazonaws.com/img-gen-pipeline/<task_id>.png",
    "album_cover_thumbnail": "https://musicgpt.s3.amazonaws.com/img-gen-pipeline/<task_id>_thumb.png",
    "lyrics_1": "[Instrumental]",
    "lyrics_2": "[Instrumental]",
    "createdAt": "2026-03-27T07:21:14Z",
    "updatedAt": "2026-03-27T07:22:47Z"
  }
}
```

### Key response fields

| Field | Description |
|---|---|
| `status` | Overall task status (applies to both conversions) |
| `conversion_id_1` / `conversion_id_2` | Match these to your tracked conversion_id to pick the right path |
| `conversion_path_1` / `conversion_path_2` | Direct MP3 download URLs — available when `status == COMPLETED` |
| `conversion_duration_1` / `conversion_duration_2` | Duration in seconds |
| `album_cover_path` | Cover art URL |

### Status values

| Value | Meaning |
|---|---|
| `IN_QUEUE` | Job is waiting to be processed |
| `COMPLETED` | Both conversions done — `conversion_path_1` and `conversion_path_2` are available |
| `ERROR` | Processing error |
| `FAILED` | Job failed |

---

## Polling Flow

1. Call `POST /MusicAI` → save `task_id`, `conversion_id_1`, `conversion_id_2`
2. Poll `GET /byId` every 5s (max 120s) until `status` is `COMPLETED`, `ERROR`, or `FAILED`
3. On `COMPLETED`, match your `conversion_id` to `conversion_id_1` or `conversion_id_2` in the response, then download from the corresponding `conversion_path_1` or `conversion_path_2`
