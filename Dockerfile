# syntax=docker/dockerfile:1.7

# ---------- Base image ----------
# Python 3.12 (matches .python-version and pyproject requires-python>=3.12)
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HF_HUB_OFFLINE=1

# System dependencies
#   ffmpeg       — required by demucs (stem separation) + audio decoding
#   libsndfile1  — required by librosa / soundfile
#   libgomp1     — OpenMP runtime (torch / numpy / demucs)
#   build-essential, git — needed for any source builds (demucs, torchcodec, etc.)
#   curl, ca-certificates — for installing uv
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        libgomp1 \
        build-essential \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager — same one used in README)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# ---------- Dependency layer (cached) ----------
# Copy only lockfiles first so dependency install is cached when app code changes
COPY pyproject.toml uv.lock ./

# Create venv at /opt/venv and install deps from the lock file (no project source yet)
RUN uv sync --frozen --no-install-project --no-dev

# ---------- Application layer ----------
COPY . .

# Install the project itself (cheap — deps already there)
RUN uv sync --frozen --no-dev

# Pre-download the sentence-transformer model used by the chatbot indexer.
# This bakes the weights (~90 MB) into the image layer so containers start
# instantly with no network dependency at runtime.
# To update the model: change the name here AND in services/chatbot_indexer.py.
RUN HF_HUB_OFFLINE=0 python -c \
    "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" \
    && echo "Model cached."

# Runtime dirs used by stem separation (demucs writes here)
RUN mkdir -p /app/inputs /app/outputs

# Non-root user
RUN groupadd --system app && useradd --system --gid app --home /app app \
    && chown -R app:app /app /opt/venv
USER app

EXPOSE 8000

# Default: run the FastAPI server.
# docker-compose overrides this for the celery worker service.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
