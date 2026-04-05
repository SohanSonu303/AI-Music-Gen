"""
LangGraph album planning agent.

Graph: analyze_script → plan_tracks → generate_prompts → generate_lyrics

All LLM calls reuse _call_openrouter() from services/prompt_service.py.
No new API keys or LLM wrappers are needed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END

from services.prompt_service import _call_openrouter

logger = logging.getLogger(__name__)

# ── Prompt file paths ─────────────────────────────────────────────────────────
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_SCRIPT_ANALYSIS_PROMPT = (_PROMPTS_DIR / "album_script_analysis.md").read_text(encoding="utf-8").strip()
_PROMPT_GENERATION_PROMPT = (_PROMPTS_DIR / "album_prompt_generation.md").read_text(encoding="utf-8").strip()
_LYRICS_GENERATION_PROMPT = (_PROMPTS_DIR / "album_lyrics_generation.md").read_text(encoding="utf-8").strip()


# ── State definition ──────────────────────────────────────────────────────────

class AlbumPlanState(TypedDict):
    album_id: str
    script: str
    num_songs: int                # total tracks
    track_composition: dict       # {songs: int, background_scores: int, instrumentals: int}
    script_analysis: str          # raw JSON string from node 1
    track_plans: list[dict]       # structured output from node 2
    album_title: str              # suggested by node 2
    style_palette: dict           # suggested by node 2
    final_tracks: list[dict]      # ready-for-DB dicts from nodes 3 + 4
    error: Optional[str]


# ── Node helpers ──────────────────────────────────────────────────────────────

def _parse_json(raw: str, context: str) -> dict | list:
    """Strip markdown fences if present and parse JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # drop first and last fence lines
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON parse failed in {context}: {exc}\nRaw output:\n{raw[:500]}") from exc


# ── Node 1: analyze_script ────────────────────────────────────────────────────

async def analyze_script(state: AlbumPlanState) -> AlbumPlanState:
    comp = state.get("track_composition", {})
    logger.info("Agent node analyze_script: album_id=%s num_songs=%d composition=%s",
                state["album_id"], state["num_songs"], comp)
    composition_hint = (
        f"Track composition requested: "
        f"{comp.get('songs', 0)} vocal song(s), "
        f"{comp.get('background_scores', 0)} background score(s), "
        f"{comp.get('instrumentals', 0)} instrumental(s). "
        f"Total: {state['num_songs']} tracks."
    )
    user_prompt = (
        f"Script:\n{state['script']}\n\n"
        f"{composition_hint}\n"
        f"Segment the script into exactly {state['num_songs']} sections."
    )
    try:
        raw = await _call_openrouter(_SCRIPT_ANALYSIS_PROMPT, user_prompt)
        parsed = _parse_json(raw, "analyze_script")
        sections = parsed.get("sections", parsed) if isinstance(parsed, dict) else parsed
        state["script_analysis"] = json.dumps({"sections": sections})
        logger.info("analyze_script done: %d sections", len(sections))
    except Exception as exc:
        logger.error("analyze_script failed: %s: %s", type(exc).__name__, exc)
        state["error"] = f"analyze_script failed: {type(exc).__name__}: {exc}"
    return state


# ── Node 2: plan_tracks ───────────────────────────────────────────────────────

_PLAN_TRACKS_SYSTEM = """You are a music director and album producer. Given a script analysis (scenes, emotional arcs, themes) and a required track composition, plan the musical identity for each track and the album as a whole.

## Track Types
- "song" — a full vocal track with lyrics; the singer tells part of the story
- "background_score" — cinematic/ambient instrumental; underscores a scene with no vocals
- "instrumental" — a structured instrumental piece (like an instrumental version of a song); has melody and arrangement but no vocals

## Output Format
Respond with ONLY valid JSON:
{
  "album_title": "...",
  "style_palette": {
    "primary_genre": "...",
    "bpm_range": "...",
    "key_signature": "...",
    "instrumentation_family": "...",
    "mood_arc": "..."
  },
  "tracks": [
    {
      "track_number": 1,
      "track_type": "song",
      "suggested_style": "...",
      "suggested_mood": "...",
      "suggested_tempo": "...",
      "make_instrumental": false,
      "energy_level": 5,
      "lyrics_theme": "..."
    }
  ]
}

## Rules
- You MUST assign exactly the number of each type specified in the composition constraint. Do not deviate.
- track_type drives make_instrumental: "song" → make_instrumental=false; "background_score" or "instrumental" → make_instrumental=true
- lyrics_theme is only meaningful for "song" tracks; leave it empty string for instrumental types.
- style_palette defines the album's sonic identity — all tracks must fit within it while allowing controlled variation.
- energy_level is 1-10 (1=quiet/ambient, 10=intense/climax). Shape a realistic energy arc across the album.
- suggested_tempo should be descriptive: e.g., "slow ballad ~65 BPM", "driving mid-tempo ~110 BPM".
- Return exactly the same number of tracks as sections in the input.
"""

async def plan_tracks(state: AlbumPlanState) -> AlbumPlanState:
    if state.get("error"):
        return state
    logger.info("Agent node plan_tracks: album_id=%s", state["album_id"])
    comp = state.get("track_composition", {})
    composition_constraint = (
        f"REQUIRED composition (you must assign exactly these counts):\n"
        f"- songs (vocal): {comp.get('songs', 0)}\n"
        f"- background_scores (cinematic instrumental): {comp.get('background_scores', 0)}\n"
        f"- instrumentals (structured no-vocal): {comp.get('instrumentals', 0)}\n"
    )
    user_prompt = f"{composition_constraint}\nScript analysis:\n{state['script_analysis']}"
    try:
        raw = await _call_openrouter(_PLAN_TRACKS_SYSTEM, user_prompt)
        parsed = _parse_json(raw, "plan_tracks")
        state["album_title"] = parsed.get("album_title", "Untitled Album")
        state["style_palette"] = parsed.get("style_palette", {})
        state["track_plans"] = parsed.get("tracks", [])
        logger.info("plan_tracks done: title=%r palette=%s", state["album_title"], state["style_palette"])
    except Exception as exc:
        logger.error("plan_tracks failed: %s", exc)
        state["error"] = f"plan_tracks failed: {exc}"
    return state


# ── Node 3: generate_prompts ──────────────────────────────────────────────────

async def generate_prompts(state: AlbumPlanState) -> AlbumPlanState:
    if state.get("error"):
        return state
    logger.info("Agent node generate_prompts: album_id=%s", state["album_id"])

    # Merge script analysis sections with track plans for richer context
    analysis = _parse_json(state["script_analysis"], "generate_prompts/analysis")
    sections = analysis.get("sections", [])
    section_map = {s["track_number"]: s for s in sections}

    enriched_tracks = []
    for plan in state["track_plans"]:
        tn = plan["track_number"]
        section = section_map.get(tn, {})
        enriched_tracks.append({**plan, **section})

    palette_hint = f"\nAlbum style palette: {json.dumps(state['style_palette'])}" if state.get("style_palette") else ""
    user_prompt = f"Track plans:{palette_hint}\n{json.dumps(enriched_tracks, indent=2)}"

    try:
        raw = await _call_openrouter(_PROMPT_GENERATION_PROMPT, user_prompt)
        parsed = _parse_json(raw, "generate_prompts")
        prompt_list = parsed.get("prompts", parsed) if isinstance(parsed, dict) else parsed
        prompt_map = {p["track_number"]: p for p in prompt_list}
    except Exception as exc:
        logger.error("generate_prompts LLM call failed: %s", exc)
        state["error"] = f"generate_prompts failed: {exc}"
        return state

    # Validate 280-char limit; retry individually for violations
    retry_needed = [p for p in prompt_list if len(p.get("prompt", "")) > 280]
    if retry_needed:
        logger.warning("generate_prompts: %d prompts exceed 280 chars, retrying", len(retry_needed))
        retry_system = _PROMPT_GENERATION_PROMPT + "\nCRITICAL: Each prompt MUST be 280 characters or fewer. Trim aggressively."
        for p in retry_needed:
            retry_user = f"Shorten this prompt to under 280 characters:\n{json.dumps(p)}"
            try:
                retry_raw = await _call_openrouter(retry_system, retry_user)
                retry_parsed = _parse_json(retry_raw, "generate_prompts/retry")
                fixed = retry_parsed.get("prompts", [retry_parsed])[0] if isinstance(retry_parsed, dict) else retry_parsed[0]
                prompt_map[fixed["track_number"]] = fixed
            except Exception:
                # Hard truncate as last resort
                p["prompt"] = p["prompt"][:277] + "..."
                prompt_map[p["track_number"]] = p

    # Build final_tracks merging plan + section + prompt data
    final_tracks = []
    for plan in state["track_plans"]:
        tn = plan["track_number"]
        section = section_map.get(tn, {})
        prompt_data = prompt_map.get(tn, {})
        track_type = plan.get("track_type", "song")
        # Ensure make_instrumental is consistent with track_type
        make_instrumental = track_type in ("background_score", "instrumental") or plan.get("make_instrumental", False)
        final_tracks.append({
            "track_number": tn,
            "track_type": track_type,
            "scene_description": section.get("scene_summary", ""),
            "script_excerpt": section.get("script_excerpt", ""),
            "suggested_style": plan.get("suggested_style", ""),
            "suggested_mood": plan.get("suggested_mood", ""),
            "suggested_tempo": plan.get("suggested_tempo", ""),
            "make_instrumental": make_instrumental,
            "energy_level": plan.get("energy_level"),
            "lyrics_theme": plan.get("lyrics_theme", ""),
            "prompt": prompt_data.get("prompt", ""),
            "music_style": prompt_data.get("music_style", ""),
            "lyrics": None,  # filled by generate_lyrics node
        })

    state["final_tracks"] = final_tracks
    logger.info("generate_prompts done: %d tracks", len(final_tracks))
    return state


# ── Node 4: generate_lyrics ───────────────────────────────────────────────────

async def generate_lyrics(state: AlbumPlanState) -> AlbumPlanState:
    if state.get("error"):
        return state
    logger.info("Agent node generate_lyrics: album_id=%s", state["album_id"])

    vocal_tracks = [t for t in state["final_tracks"] if not t.get("make_instrumental")]
    if not vocal_tracks:
        logger.info("generate_lyrics: all tracks are instrumental, skipping")
        return state

    analysis = _parse_json(state["script_analysis"], "generate_lyrics/analysis")
    sections = analysis.get("sections", [])
    section_map = {s["track_number"]: s for s in sections}

    lyrics_input = []
    for track in vocal_tracks:
        tn = track["track_number"]
        section = section_map.get(tn, {})
        lyrics_input.append({
            "track_number": tn,
            "make_instrumental": False,
            "scene_description": track.get("scene_description", ""),
            "script_excerpt": track.get("script_excerpt", ""),
            "emotional_arc": section.get("emotional_arc", ""),
            "key_themes": section.get("key_themes", []),
            "suggested_mood": track.get("suggested_mood", ""),
            "suggested_style": track.get("suggested_style", ""),
            "suggested_tempo": track.get("suggested_tempo", ""),
            "lyrics_theme": track.get("lyrics_theme", ""),
        })

    user_prompt = f"Tracks needing lyrics:\n{json.dumps(lyrics_input, indent=2)}"
    try:
        raw = await _call_openrouter(_LYRICS_GENERATION_PROMPT, user_prompt)
        parsed = _parse_json(raw, "generate_lyrics")
        lyrics_list = parsed.get("lyrics", parsed) if isinstance(parsed, dict) else parsed
        lyrics_map = {item["track_number"]: item.get("lyrics", "") for item in lyrics_list}
    except Exception as exc:
        logger.error("generate_lyrics failed: %s", exc)
        # Non-fatal: lyrics are nice-to-have, don't fail the whole album
        logger.warning("Continuing without lyrics due to error: %s", exc)
        return state

    # Attach lyrics to the corresponding final_tracks entries
    for track in state["final_tracks"]:
        if not track.get("make_instrumental"):
            track["lyrics"] = lyrics_map.get(track["track_number"])

    logger.info("generate_lyrics done: lyrics added for %d vocal tracks", len(vocal_tracks))
    return state


# ── Build graph ───────────────────────────────────────────────────────────────

def build_album_agent():
    graph = StateGraph(AlbumPlanState)
    graph.add_node("analyze_script", analyze_script)
    graph.add_node("plan_tracks", plan_tracks)
    graph.add_node("generate_prompts", generate_prompts)
    graph.add_node("generate_lyrics", generate_lyrics)

    graph.set_entry_point("analyze_script")
    graph.add_edge("analyze_script", "plan_tracks")
    graph.add_edge("plan_tracks", "generate_prompts")
    graph.add_edge("generate_prompts", "generate_lyrics")
    graph.add_edge("generate_lyrics", END)

    return graph.compile()


# Singleton compiled graph — imported by album_service
album_agent = build_album_agent()
