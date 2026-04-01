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

## Sound Generator

**`POST /sound_generator`**

Submits a sound-effect generation job. The request is asynchronous and returns a single `conversion_id`.

### Request body

| Field | Type | Required | Description |
|---|---|---|---|
| `prompt` | string | yes | Text description of the sound effect to generate |
| `webhook_url` | string | no | Callback URL for completion events |
| `audio_length` | int | no | Target sound duration in seconds |

### Response

```json
{
  "success": true,
  "task_id": "soundgen789",
  "conversion_id": "conv456",
  "eta": -1,
  "credit_estimate": 100.1,
  "message": "Successfully published to queue"
}
```

### Polling

Poll `GET /byId` with `conversionType=SOUND_GENERATOR`:

```
GET /byId?conversionType=SOUND_GENERATOR&task_id=<task_id>&conversion_id=<conversion_id>
```

Expected completed fields include `conversion_path`, optional `conversion_path_wav`, and `conversion_duration`.


## Inpaint

**`POST /inpaint`**

Replaces a time-ranged section of an existing audio file with AI-generated content. Submitted as `multipart/form-data` (not JSON). Returns a job immediately; poll `GET /byId` with `conversionType=INPAINT` for results.

### Request (multipart/form-data)

| Field | Type | Required | Description |
|---|---|---|---|
| `audio_url` | string | yes | Public URL of the source audio file to modify |
| `prompt` | string | yes | Description of what to generate in the replaced section |
| `replace_start_at` | float | yes | Start of the region to replace (seconds) |
| `replace_end_at` | float | yes | End of the region to replace (seconds) |
| `lyrics` | string | no | Full lyrics of the original song |
| `lyrics_section_to_replace` | string | no | New lyrics for the replaced section |
| `gender` | string | no | Vocalist gender override (`male` / `female`) |
| `num_outputs` | int | no | Number of output variants to generate (default: `1`, max: `2`) |
| `webhook_url` | string | no | URL to POST results to when complete |

### Response

```json
{
  "success": true,
  "message": "Inpaint request submitted successfully",
  "task_id": "task-xyz-123",
  "conversion_id_1": "inpaint-abc",
  "conversion_id_2": "inpaint-def",
  "eta": 40,
  "credit_estimate": 45
}
```

| Field | Description |
|---|---|
| `task_id` | Use this to poll status |
| `conversion_id_1` / `conversion_id_2` | Individual conversion IDs — poll each separately |
| `eta` | Estimated processing time in seconds |
| `credit_estimate` | Estimated credit cost |

### Polling

Poll `GET /byId` with `conversionType=INPAINT` (same flow as music generation):

```
GET /byId?conversionType=INPAINT&task_id=<task_id>&conversion_id=<conversion_id>
```

The response shape is identical to the music generation poll response — match `conversion_id_1` / `conversion_id_2` to get the correct `conversion_path_N`.

### Example

```python
import requests

url = "https://api.musicgpt.com/api/public/v1/inpaint"
headers = {"Authorization": "<API_KEY>"}

data = {
    "audio_url": "https://mybucket.s3.amazonaws.com/song.mp3",
    "prompt": "Add a soft guitar solo here",
    "replace_start_at": 12.5,
    "replace_end_at": 20.0,
    "lyrics": "This is where my story begins",
    "lyrics_section_to_replace": "New lyrics",
    "gender": "male",
    "num_outputs": 1,
}

response = requests.post(url, headers=headers, data=data)
result = response.json()
# result["task_id"], result["conversion_id_1"], result["conversion_id_2"]
```

## lyrics generator
```
curl --request GET \
  --url 'https://api.musicgpt.com/api/public/v1/prompt_to_lyrics?prompt=create%20a%20love%20song' \
  --header 'Authorization: someauth'

{
  "success": true,
  "task_id": "task-lyrics-2345",
  "message": "Lyrics generated successfully",
  "lyrics": "Under the silver moonlight we sway...\n...\n",
  "credit_estimate": 10
}

```
