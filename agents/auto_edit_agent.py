"""
Auto Edit Agent — Phase 4
=========================
Single-node LangGraph agent that selects the best trim window from candidates.

Behaviour
---------
- Short-circuits the LLM entirely when only 1 candidate exists (no API call).
- Falls back to rank-0 (highest algorithmic score) if the LLM errors or returns
  unparseable output — sets ``used_fallback=True`` in the returned tuple.
- Reuses ``_call_openrouter()`` from ``services/prompt_service`` (300 s read
  timeout, 3 retries with 5 / 10 / 15 s backoff).

Public interface
----------------
    from agents.auto_edit_agent import select_window

    chosen, reasoning, used_fallback = await select_window(candidates, energy_pref)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Optional

import numpy as np

from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from services.prompt_service import _call_openrouter

logger = logging.getLogger(__name__)


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a professional music editor AI. Given a list of candidate trim windows \
for an audio track, choose the single best window that fits the user's energy \
preference and makes musical sense.

Each candidate has:
- index            : 0-based position in the list (use this in your answer)
- start / end      : timestamps in seconds
- duration         : window length in seconds
- energy_score     : 0.0–1.0  (higher = more energetic section)
- duration_score   : 0.0–1.0  (higher = closer to the target duration)
- structural_score : 0.0–1.0  (higher = more complete musical phrases)
- total_score      : overall weighted score — use as the default tiebreaker
- segment_labels   : structural labels for sections covered by this window.
  Possible labels (v2 spectral labeling):
    intro   — quiet, sparse opening
    verse   — melodic, moderate energy, low chord-change rate
    build   — rising energy and rhythmic density
    chorus  — high energy + high harmonic activity (lots of chord changes)
    peak    — sustained high energy, less harmonic variety than chorus
    drop    — dense transients, typically low chroma variance (EDM drops)
    bridge  — mid-track low-energy section, often transitional
    outro   — quiet closing section

Energy preference guide:
- "high_energy"  → prefer windows with highest avg energy (chorus, peak, drop)
- "climax"       → prefer the window containing the highest-energy peak or drop
- "drop"         → prefer windows whose labels include drop specifically (EDM)
- "chorus"       → prefer windows with a chorus label (hook, harmonic richness)
- "verse"        → prefer windows with a verse label (melodic, narrative)
- "build"        → prefer windows with a build label (rising tension, riser)
- "chill"        → prefer low-energy windows (intro, bridge, verse, outro)
- "outro"        → prefer windows from the later/closing part of the track
- "intro_heavy"  → prefer windows starting early, ideally including intro/verse
- null           → choose the best overall musical balance (highest total_score \
                   is a good default, but consider label diversity)

If a user_description is provided, it takes precedence over the energy_preference enum \
— treat it as the primary intent signal and interpret it literally \
(e.g. "punchy drop for a DJ mix" → prefer drop/peak labels; \
"calm opening for a podcast" → prefer intro/verse labels; \
"exactly 30 seconds of the hook" → prefer chorus, weight duration_score highly).

Decision hints:
- A window containing both a verse and a chorus is usually more satisfying than \
  one containing only a peak — it tells a musical story.
- Prefer windows where the labels progress naturally \
  (e.g. intro→verse→build→chorus rather than chorus→intro).
- A "needs_loop" window means the source will be looped; prefer non-loop windows \
  unless there are no other options.

Respond with ONLY valid JSON — no markdown fences, no extra text:
{"chosen_index": <integer>, "reasoning": "<one concise sentence explaining why>"}"""


# ── LangGraph state ───────────────────────────────────────────────────────────

class AutoEditState(TypedDict):
    candidates_json: str          # JSON-serialised list of Window dicts
    energy_preference: Optional[str]
    user_description: Optional[str]   # free-text intent from the user
    chosen_index: int             # 0-based index into the candidates list
    reasoning: str                # LLM explanation or fallback note
    used_fallback: bool
    error: Optional[str]


# ── Graph node ────────────────────────────────────────────────────────────────

async def _select_window_node(state: AutoEditState) -> AutoEditState:
    pref = state.get("energy_preference")
    user_desc = state.get("user_description")
    logger.info(
        "auto_edit_agent: _select_window_node — energy_pref=%s user_description=%r",
        pref, user_desc,
    )

    candidates: list[dict] = json.loads(state["candidates_json"])

    payload: dict = {"energy_preference": pref, "candidates": []}
    if user_desc:
        payload["user_description"] = user_desc

    user_prompt = json.dumps(
        {
            **payload,
            "candidates": [
                {
                    "index": i,
                    "start": c["start"],
                    "end": c["end"],
                    "duration": c["duration"],
                    "energy_score": c["energy_score"],
                    "duration_score": c["duration_score"],
                    "structural_score": c["structural_score"],
                    "total_score": c["total_score"],
                    "segment_labels": c["segment_labels"],
                    "needs_loop": c.get("needs_loop", False),
                }
                for i, c in enumerate(candidates)
            ],
        },
        indent=2,
    )

    try:
        raw = await _call_openrouter(_SYSTEM_PROMPT, user_prompt)

        # Strip markdown fences if the model wraps output anyway
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        parsed = json.loads(cleaned)
        chosen_index = int(parsed["chosen_index"])
        # Clamp to valid range — guard against hallucinated out-of-range index
        chosen_index = max(0, min(chosen_index, len(candidates) - 1))

        state["chosen_index"] = chosen_index
        state["reasoning"] = str(parsed.get("reasoning", ""))
        state["used_fallback"] = False
        logger.info(
            "auto_edit_agent: LLM chose index=%d  reasoning=%r",
            chosen_index,
            state["reasoning"],
        )

    except Exception as exc:
        logger.warning(
            "auto_edit_agent: LLM call failed (%s: %s) — falling back to rank-0",
            type(exc).__name__,
            exc,
        )
        state["chosen_index"] = 0
        state["reasoning"] = "Algorithmic fallback — LLM selection unavailable."
        state["used_fallback"] = True
        state["error"] = f"{type(exc).__name__}: {exc}"

    return state


# ── Graph wiring ──────────────────────────────────────────────────────────────

def _build_auto_edit_agent():
    graph: StateGraph = StateGraph(AutoEditState)
    graph.add_node("select_window", _select_window_node)
    graph.set_entry_point("select_window")
    graph.add_edge("select_window", END)
    return graph.compile()


# Module-level singleton — compiled once on import
_auto_edit_graph = _build_auto_edit_agent()


# ── Public interface ──────────────────────────────────────────────────────────

_ARRANGE_SYSTEM_PROMPT = """\
You are a music editor AI. Given a list of structural segments from an audio \
track and a target duration, produce an arrangement plan that fills that duration \
by ordering (and repeating) the segments musically.

Each segment has:
- index    : 0-based position in the source track
- label    : structural label (intro / verse / build / chorus / peak / drop / bridge / outro)
- duration : segment length in seconds

Rules:
- Return a JSON array of segment indices (integers), e.g. [0, 2, 3, 2, 3, 4]
- Indices may repeat — repetition is expected and intentional
- The sum of durations of the returned indices should be ≥ target_duration
- Musical storytelling order: intro first (if present), then verse/chorus cycles, \
  outro last (if present)
- Chorus / peak / drop segments should repeat more than intro or bridge
- Never return an empty list

Respond with ONLY valid JSON — an array of integers, no commentary:
[<int>, <int>, ...]"""


async def plan_loop_arrangement(
    segments: list[dict],
    target_duration: float,
) -> list[int]:
    """
    Ask the LLM to produce a musical arrangement of segment indices that fills
    ``target_duration``.  Falls back to repeating all segments in order.

    Parameters
    ----------
    segments       : list of {index, label, duration} dicts
    target_duration: desired output length in seconds

    Returns
    -------
    list[int] — ordered segment indices (may repeat)
    """
    if not segments:
        return []

    # Short-circuit: only one segment — repeat it
    if len(segments) == 1:
        repeats = max(1, int(np.ceil(target_duration / max(segments[0]["duration"], 0.1))))
        return [0] * repeats

    user_prompt = json.dumps(
        {"target_duration": round(target_duration, 2), "segments": segments},
        indent=2,
    )

    try:
        raw = await _call_openrouter(_ARRANGE_SYSTEM_PROMPT, user_prompt)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        parsed = json.loads(cleaned)
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("LLM returned non-list or empty list")

        arrangement = [int(x) for x in parsed]
        n_segs = len(segments)
        arrangement = [max(0, min(x, n_segs - 1)) for x in arrangement]

        logger.info(
            "plan_loop_arrangement: LLM arrangement=%s (target=%.1fs)",
            arrangement, target_duration,
        )
        return arrangement

    except Exception as exc:
        logger.warning(
            "plan_loop_arrangement: LLM failed (%s: %s) — using algorithmic fallback",
            type(exc).__name__, exc,
        )
        # Algorithmic fallback: repeat all in order
        total_dur = sum(s["duration"] for s in segments)
        repeats = max(1, int(np.ceil(target_duration / max(total_dur, 0.1))))
        return list(range(len(segments))) * repeats


async def select_window(
    candidates: list,
    energy_preference: Optional[str] = None,
    user_description: Optional[str] = None,
) -> tuple:
    """
    Select the best Window from candidates using the LLM agent.

    Parameters
    ----------
    candidates        : list[Window]  — ordered by total_score descending
                        (output of ``find_candidate_windows``)
    energy_preference : "high_energy" | "climax" | "intro_heavy" | None
    user_description  : free-text intent from the user (e.g. "punchy 30s drop for my ad")
                        passed as additional context to the LLM; takes precedence over
                        energy_preference when both are provided.

    Returns
    -------
    (chosen_window, reasoning: str, used_fallback: bool)

    Notes
    -----
    - Skips the LLM entirely when ``len(candidates) == 1``.
    - Never raises — errors are caught and the rank-0 candidate is returned.
    """
    if not candidates:
        raise ValueError("select_window: candidates list must not be empty")

    # Short-circuit: only one option — no LLM call needed
    if len(candidates) == 1:
        logger.info("auto_edit_agent: single candidate — skipping LLM")
        return candidates[0], "Only one candidate window available.", False

    candidates_json = json.dumps([asdict(c) for c in candidates])

    initial: AutoEditState = {
        "candidates_json": candidates_json,
        "energy_preference": energy_preference,
        "user_description": user_description,
        "chosen_index": 0,
        "reasoning": "",
        "used_fallback": False,
        "error": None,
    }

    result = await _auto_edit_graph.ainvoke(initial)
    chosen = candidates[result["chosen_index"]]
    return chosen, result["reasoning"], result["used_fallback"]
