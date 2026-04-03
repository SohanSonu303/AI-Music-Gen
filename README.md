# AI-Music-Gen

FastAPI backend for an AI music generation app using Supabase (database + file storage) and MusicGPT API for generation.

---

## Installation & Setup

### Step 1 — Prerequisites

Install system dependencies before anything else.

**Python 3.12**
```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu/Debian
sudo apt-get install python3.12 python3.12-venv
```

**ffmpeg** (required for stem separation audio conversion)
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Verify
ffmpeg -version
```

---

### Step 2 — Clone the repository

```bash
git clone <repo-url>
cd AI-Music-Gen
```

---

### Step 3 — Install Python dependencies

**Option A — uv (recommended)**
```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install all dependencies into .venv
uv sync

# Activate the virtual environment
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows
```

**Option B — pip fallback**
```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Mac/Linux
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

---

### Step 4 — Environment variables

Create a `.env` file in the project root:
```
SUPABASE_URL=...
SUPABASE_KEY=...
MUSICGPT_API_KEY=...
BUCKET_NAME=music-generated
OPENROUTER_API_KEY=...
```

---

### Step 5 — Run the server

```bash
# With uv (no manual activation needed)
uv run uvicorn main:app --reload

# With activated venv
uvicorn main:app --reload
```

Server starts at `http://localhost:8000`
Interactive API docs at `http://localhost:8000/docs`

---

## Folder Structure

```
AI-Music-Gen/
├── main.py                   # FastAPI app entry point, registers all routers
├── supabase_client.py        # Supabase singleton client
├── pyproject.toml            # Project metadata and dependencies (uv)
├── requirements.txt          # pip-compatible dependency list
├── .env                      # Environment variables (gitignored)
├── .mcp.json                 # Supabase MCP server config (gitignored, contains PAT)
├── .python-version           # Pins Python 3.12
├── thirdpartyapi.md          # MusicGPT API reference
├── sample_requests.md        # Example request bodies for different music styles
├── prompts/
│   └── musicenhancerprompt.md  # Default master prompt for the prompt enhancer feature
├── models/
│   ├── project_model.py      # projectCreate, projectResponse
│   ├── music_model.py        # MusicCreate, InpaintCreate, MusicResponse, MusicType enum
│   ├── lyrics_model.py       # LyricsCreate, LyricsResponse
│   ├── separation_model.py   # SeparationResponse
│   ├── download_model.py     # DownloadTrack, DownloadResponse
│   ├── prompt_model.py       # QuickIdeaCreate, PromptEnhanceCreate, PromptResponse
│   ├── extend_model.py       # ExtendCreate
│   └── remix_model.py        # RemixCreate
├── routers/
│   ├── project_router.py     # POST /projects/, GET /projects/
│   ├── music_router.py       # POST /music/generateMusic, POST /music/remix
│   ├── inpaint_router.py     # POST /inpaint/inpaint
│   ├── lyrics_router.py      # POST /lyrics/generate
│   ├── separation_router.py  # POST /separate/
│   ├── download_router.py    # GET /download/
│   └── prompt_router.py      # POST /prompt/quick-idea, POST /prompt/enhance
└── services/
    ├── project_service.py    # Supabase CRUD for projects table
    ├── music_service.py      # MusicGPT API calls, polling, Supabase Storage upload
    ├── lyrics_service.py     # MusicGPT lyrics generation, Supabase insert
    ├── separation_service.py # Demucs stem separation, local cleanup, Supabase Storage upload
    ├── download_service.py   # Fetch both music tracks by user_id + task_id from music_metadata
    └── prompt_service.py     # OpenRouter (DeepSeek) calls for quick idea + prompt enhancer
```
