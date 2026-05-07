import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

DOC_PATH = Path(__file__).parent.parent / "functional_requirements.md"
_MODEL_NAME = "all-MiniLM-L6-v2"

# When SENTENCE_TRANSFORMERS_HOME is set (e.g. in Docker), the library resolves
# the cached model automatically via that env var.  This path is used to emit a
# clear log message so operators know the model loaded from the baked-in cache.
_MODEL_CACHE_DIR = os.environ.get("SENTENCE_TRANSFORMERS_HOME")

_MIN_CHUNK_CHARS = 100
_MAX_CHUNK_CHARS = 1500

# Module-level singletons
_model: SentenceTransformer | None = None
_cached_mtime: float | None = None
_cached_embeddings: np.ndarray | None = None
_cached_chunks: list["Chunk"] = []


@dataclass
class Chunk:
    heading: str
    category: str
    text: str
    # embedding stored separately in _cached_embeddings array
    tokens: list[str] = field(default_factory=list)  # kept for interface compat


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        if _MODEL_CACHE_DIR:
            logger.info("Loading sentence-transformer model from cache: %s", _MODEL_CACHE_DIR)
        else:
            logger.info("Loading sentence-transformer model: %s (will download if not cached)", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("Model loaded.")
    return _model


def _parse_markdown(path: Path) -> list[Chunk]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("functional_requirements.md not found at %s", path)
        return []

    chunks: list[Chunk] = []
    current_category = ""
    current_heading = ""
    current_lines: list[str] = []

    def _flush(heading: str, category: str, lines: list[str]) -> Chunk | None:
        text = "\n".join(lines).strip()
        if not text:
            return None
        return Chunk(heading=heading, category=category, text=f"### {heading}\n\n{text}")

    for line in raw.splitlines():
        if line.startswith("## "):
            if current_heading and current_lines:
                c = _flush(current_heading, current_category, current_lines)
                if c:
                    chunks.append(c)
            current_category = line[3:].strip()
            current_heading = ""
            current_lines = []
        elif line.startswith("### "):
            if current_heading and current_lines:
                c = _flush(current_heading, current_category, current_lines)
                if c:
                    chunks.append(c)
            current_heading = line[4:].strip()
            current_lines = []
        else:
            if current_heading:
                current_lines.append(line)

    if current_heading and current_lines:
        c = _flush(current_heading, current_category, current_lines)
        if c:
            chunks.append(c)

    # Merge very short chunks with the next sibling under the same category
    merged: list[Chunk] = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        if len(chunk.text) < _MIN_CHUNK_CHARS and i + 1 < len(chunks) and chunks[i + 1].category == chunk.category:
            next_c = chunks[i + 1]
            merged.append(Chunk(
                heading=f"{chunk.heading} / {next_c.heading}",
                category=chunk.category,
                text=chunk.text + "\n\n" + next_c.text,
            ))
            i += 2
        else:
            merged.append(chunk)
            i += 1

    # Split very long chunks on blank lines
    final: list[Chunk] = []
    for chunk in merged:
        if len(chunk.text) <= _MAX_CHUNK_CHARS:
            final.append(chunk)
            continue
        paragraphs = re.split(r"\n\s*\n", chunk.text)
        current_sub: list[str] = []
        sub_idx = 0
        for para in paragraphs:
            current_sub.append(para)
            candidate = "\n\n".join(current_sub)
            if len(candidate) > _MAX_CHUNK_CHARS:
                if len(current_sub) > 1:
                    flushed = "\n\n".join(current_sub[:-1])
                    sub_idx += 1
                    heading = chunk.heading if sub_idx == 1 else f"{chunk.heading} (part {sub_idx})"
                    final.append(Chunk(heading=heading, category=chunk.category, text=flushed))
                    current_sub = [para]
                else:
                    sub_idx += 1
                    heading = chunk.heading if sub_idx == 1 else f"{chunk.heading} (part {sub_idx})"
                    final.append(Chunk(heading=heading, category=chunk.category, text=para))
                    current_sub = []
        if current_sub:
            sub_idx += 1
            heading = chunk.heading if sub_idx == 1 else f"{chunk.heading} (part {sub_idx})"
            final.append(Chunk(heading=heading, category=chunk.category, text="\n\n".join(current_sub)))

    return final


def build_index(path: Path = DOC_PATH) -> None:
    global _cached_mtime, _cached_embeddings, _cached_chunks

    if not path.exists():
        logger.error("Cannot build chatbot index — doc missing: %s", path)
        _cached_chunks = []
        _cached_embeddings = None
        _cached_mtime = None
        return

    chunks = _parse_markdown(path)
    if not chunks:
        logger.warning("Chatbot index: no chunks parsed from %s", path)
        _cached_chunks = []
        _cached_embeddings = None
        _cached_mtime = os.path.getmtime(path)
        return

    model = _get_model()
    # Embed heading + text so both heading keywords and body content influence retrieval
    texts = [f"{c.heading}. {c.text}" for c in chunks]
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    _cached_embeddings = np.array(embeddings)
    _cached_chunks = chunks
    _cached_mtime = os.path.getmtime(path)
    logger.info("Chatbot index built: %d chunks from %s", len(chunks), path)


def _ensure_index(path: Path = DOC_PATH) -> None:
    global _cached_mtime

    if not path.exists():
        if _cached_embeddings is not None:
            logger.warning("Doc removed; serving stale index")
        return

    current_mtime = os.path.getmtime(path)
    if _cached_mtime is None or current_mtime != _cached_mtime:
        logger.info("Doc changed (mtime %s → %s); rebuilding index", _cached_mtime, current_mtime)
        build_index(path)


def search(query: str, top_k: int = 3, path: Path = DOC_PATH) -> list[tuple[Chunk, float]]:
    _ensure_index(path)

    if _cached_embeddings is None or not _cached_chunks:
        return []

    model = _get_model()
    query_emb = model.encode(query, normalize_embeddings=True)

    # Cosine similarity (embeddings are L2-normalised, so dot product == cosine)
    scores = (_cached_embeddings @ query_emb).tolist()
    ranked = sorted(zip(_cached_chunks, scores), key=lambda x: x[1], reverse=True)
    return ranked[:top_k]


def index_stats(path: Path = DOC_PATH) -> dict:
    _ensure_index(path)
    return {
        "indexed_chunks": len(_cached_chunks),
        "last_built_at": _cached_mtime,
        "doc_mtime": os.path.getmtime(path) if path.exists() else None,
    }
