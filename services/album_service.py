"""
Album service — CRUD, agent orchestration, generation, completion monitor.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, HTTPException
from fastapi.concurrency import run_in_threadpool

from agents.album_agent import album_agent
from models.album_model import AlbumApprove, AlbumCreate
from tasks.music_tasks import process_album_track_task
from supabase_client import supabase

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"COMPLETED", "ERROR", "FAILED"}
MONITOR_INTERVAL_SECONDS = 15
MONITOR_TIMEOUT_SECONDS = 600

# Inline system prompt for single-track re-analysis (used in replan_track with custom excerpt)
_REANALYZE_SYSTEM = (
    "You are a script analyst. Given a short script excerpt, return ONLY valid JSON with keys: "
    '"scene_summary" (2-3 sentences), "emotional_arc" (start emotion → end emotion), '
    '"key_themes" (list of 2-4 strings). No markdown, no preamble.'
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_album(album_id: str, user_id: str | None = None) -> dict:
    q = supabase.table("albums").select("*").eq("id", album_id)
    if user_id:
        q = q.eq("user_id", user_id)
    resp = q.single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail=f"Album not found: {album_id}")
    return resp.data


def _fetch_tracks(album_id: str) -> list[dict]:
    resp = (
        supabase.table("album_tracks")
        .select("*")
        .eq("album_id", album_id)
        .order("track_number")
        .execute()
    )
    return resp.data or []


def _build_album_response(album: dict, tracks: list[dict]) -> dict:
    return {**album, "tracks": tracks}


# ── CRUD ──────────────────────────────────────────────────────────────────────

class AlbumService:

    @staticmethod
    async def create_album(data: AlbumCreate, background_tasks: BackgroundTasks, user_id: str, user_name: str, user_email: str) -> dict:
        composition = {
            "songs": data.songs,
            "background_scores": data.background_scores,
            "instrumentals": data.instrumentals,
        }
        record = {
            "project_id": data.project_id,
            "user_id": user_id,
            "user_name": user_name,
            "user_email": user_email,
            "script": data.script,
            "num_songs": data.total_tracks,
            "track_composition": json.dumps(composition),
            "status": "PLANNING",
        }
        resp = await run_in_threadpool(lambda: supabase.table("albums").insert(record).execute())
        album = resp.data[0]
        album_id = album["id"]
        logger.info("Album created: album_id=%s user_id=%s total=%d composition=%s",
                    album_id, user_id, data.total_tracks, composition)

        background_tasks.add_task(
            AlbumService.run_album_agent, album_id, data.script, data.total_tracks, composition
        )
        return _build_album_response(album, [])

    @staticmethod
    async def get_album(album_id: str, user_id: str) -> dict:
        album = await run_in_threadpool(_fetch_album, album_id, user_id)
        tracks = await run_in_threadpool(_fetch_tracks, album_id)
        return _build_album_response(album, tracks)

    @staticmethod
    async def get_user_albums(user_id: str) -> list[dict]:
        resp = await run_in_threadpool(
            lambda: supabase.table("albums")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        albums = resp.data or []
        result = []
        for album in albums:
            tracks = await run_in_threadpool(_fetch_tracks, album["id"])
            result.append(_build_album_response(album, tracks))
        return result

    # ── LangGraph agent runner ────────────────────────────────────────────────

    @staticmethod
    async def run_album_agent(album_id: str, script: str, num_songs: int, track_composition: dict | None = None) -> None:
        logger.info("Agent starting: album_id=%s", album_id)
        try:
            initial_state = {
                "album_id": album_id,
                "script": script,
                "num_songs": num_songs,
                "track_composition": track_composition or {"songs": num_songs, "background_scores": 0, "instrumentals": 0},
                "script_analysis": "",
                "track_plans": [],
                "album_title": "",
                "style_palette": {},
                "final_tracks": [],
                "error": None,
            }
            final_state = await album_agent.ainvoke(initial_state)

            if final_state.get("error"):
                raise RuntimeError(final_state["error"])

            # Persist tracks
            track_rows = []
            for track in final_state["final_tracks"]:
                track_rows.append({
                    "album_id": album_id,
                    "track_number": track["track_number"],
                    "track_type": track.get("track_type", "song"),
                    "scene_description": track.get("scene_description"),
                    "script_excerpt": track.get("script_excerpt", "")[:500] if track.get("script_excerpt") else None,
                    "suggested_style": track.get("suggested_style"),
                    "suggested_mood": track.get("suggested_mood"),
                    "suggested_tempo": track.get("suggested_tempo"),
                    "prompt": track.get("prompt"),
                    "music_style": track.get("music_style"),
                    "lyrics": track.get("lyrics"),
                    "make_instrumental": track.get("make_instrumental", False),
                    "energy_level": track.get("energy_level"),
                    "status": "PENDING",
                })
            await run_in_threadpool(
                lambda: supabase.table("album_tracks").insert(track_rows).execute()
            )

            style_palette_str = json.dumps(final_state["style_palette"]) if final_state.get("style_palette") else None
            await run_in_threadpool(
                lambda: supabase.table("albums").update({
                    "status": "PLANNED",
                    "title": final_state.get("album_title") or "Untitled Album",
                    "style_palette": style_palette_str,
                    "updated_at": _now_iso(),
                }).eq("id", album_id).execute()
            )

            logger.info("Agent completed: album_id=%s title=%r tracks=%d",
                        album_id, final_state.get("album_title"), len(track_rows))

        except Exception as exc:
            logger.error("Agent failed: album_id=%s error=%s", album_id, exc)
            await run_in_threadpool(
                lambda: supabase.table("albums").update({
                    "status": "FAILED",
                    "updated_at": _now_iso(),
                }).eq("id", album_id).execute()
            )

    # ── Approve & generate ────────────────────────────────────────────────────

    @staticmethod
    async def approve_and_generate(album_id: str, data: AlbumApprove, background_tasks: BackgroundTasks, user_id: str = "") -> dict:
        album = await run_in_threadpool(_fetch_album, album_id, user_id or None)
        if album["status"] not in ("PLANNED", "FAILED"):
            raise HTTPException(
                status_code=400,
                detail=f"Album must be in PLANNED or FAILED status to approve. Current status: {album['status']}",
            )

        # Apply any user edits to tracks before generating
        if data.track_updates:
            for update in data.track_updates:
                patch = {k: v for k, v in update.model_dump(exclude={"id"}).items() if v is not None}
                if patch:
                    u = update
                    await run_in_threadpool(
                        lambda: supabase.table("album_tracks").update(patch).eq("id", str(u.id)).execute()
                    )

        await run_in_threadpool(
            lambda: supabase.table("albums").update({
                "status": "GENERATING",
                "updated_at": _now_iso(),
            }).eq("id", album_id).execute()
        )

        all_tracks = await run_in_threadpool(_fetch_tracks, album_id)
        # On a retry (album was FAILED), skip tracks that already completed successfully.
        tracks = [t for t in all_tracks if t["status"] not in ("COMPLETED",)]
        logger.info("Approve & generate: album_id=%s total_tracks=%d submitting=%d", album_id, len(all_tracks), len(tracks))

        # Enqueue one Celery task per track. The submission worker's concurrency
        # (controlled by MUSICGPT_MAX_PARALLEL in .env) serialises how many are
        # sent to MusicGPT at once.
        for track in tracks:
            track_type = track.get("track_type", "song")
            if track_type == "song":
                music_type = "vocal"
            elif track_type in ("background_score", "instrumental"):
                music_type = "music"
            else:
                music_type = "music" if track.get("make_instrumental") else "vocal"

            process_album_track_task.apply_async(
                args=[
                    album_id,
                    track["id"],
                    album["project_id"],
                    album["user_id"],
                    album["user_name"],
                    album["user_email"],
                    music_type,
                    track["prompt"] or "",
                ],
                kwargs={
                    "music_style": track.get("music_style"),
                    "lyrics": track.get("lyrics"),
                    "make_instrumental": track.get("make_instrumental", False),
                    "gender": track.get("gender"),
                    "output_length": track.get("output_length"),
                },
                queue="musicgpt_album",
            )
            logger.info("Track enqueued to Celery: track_number=%d track_id=%s", track["track_number"], track["id"])

        background_tasks.add_task(AlbumService.monitor_album_completion, album_id)

        updated_album = await run_in_threadpool(_fetch_album, album_id)
        tracks = await run_in_threadpool(_fetch_tracks, album_id)
        return _build_album_response(updated_album, tracks)

    # ── Progress ──────────────────────────────────────────────────────────────

    @staticmethod
    async def get_album_progress(album_id: str, user_id: str = "") -> dict:
        album = await run_in_threadpool(_fetch_album, album_id, user_id or None)
        tracks = await run_in_threadpool(_fetch_tracks, album_id)
        completed = sum(1 for t in tracks if t["status"] in TERMINAL_STATUSES)
        return {
            "album_id": album_id,
            "status": album["status"],
            "tracks_completed": completed,
            "tracks_total": len(tracks),
            "tracks": [{"track_number": t["track_number"], "status": t["status"]} for t in tracks],
        }

    # ── Completion monitor ────────────────────────────────────────────────────

    @staticmethod
    def monitor_album_completion(album_id: str) -> None:
        logger.info("Monitor started: album_id=%s", album_id)
        elapsed = 0

        while elapsed < MONITOR_TIMEOUT_SECONDS:
            time.sleep(MONITOR_INTERVAL_SECONDS)
            elapsed += MONITOR_INTERVAL_SECONDS

            tracks = _fetch_tracks(album_id)
            if not tracks:
                continue

            # Sync IN_QUEUE tracks against their linked music_metadata status.
            # Only mark a track terminal when ALL its music_metadata rows are terminal
            # (prevents premature COMPLETED when the second conversion is still uploading).
            for track in tracks:
                if track["status"] not in TERMINAL_STATUSES and track.get("task_id"):
                    meta_resp = (
                        supabase.table("music_metadata")
                        .select("status")
                        .eq("task_id", track["task_id"])
                        .execute()
                    )
                    if meta_resp.data:
                        statuses = [r["status"] for r in meta_resp.data]
                        if all(s in TERMINAL_STATUSES for s in statuses):
                            synced_status = "COMPLETED" if any(s == "COMPLETED" for s in statuses) else "FAILED"
                            supabase.table("album_tracks").update({"status": synced_status}).eq("id", track["id"]).execute()
                            logger.info("Track synced: track_id=%s status=%s", track["id"], synced_status)

            # Re-fetch after sync to check overall album state
            tracks = _fetch_tracks(album_id)
            all_done = all(t["status"] in TERMINAL_STATUSES for t in tracks)
            if all_done:
                any_completed = any(t["status"] == "COMPLETED" for t in tracks)
                album_status = "COMPLETED" if any_completed else "FAILED"
                supabase.table("albums").update({
                    "status": album_status,
                    "updated_at": _now_iso(),
                }).eq("id", album_id).execute()
                logger.info("Album %s: album_id=%s", album_status, album_id)
                return

        # Timeout — mark as FAILED
        logger.warning("Monitor timed out: album_id=%s", album_id)
        supabase.table("albums").update({
            "status": "FAILED",
            "updated_at": _now_iso(),
        }).eq("id", album_id).execute()

    # ── Enhancement 3: Replan single track ───────────────────────────────────

    @staticmethod
    async def replan_track(album_id: str, track_id: str, custom_script_excerpt: str | None = None, user_id: str = "") -> dict:
        """
        Re-run prompt + lyrics generation for a single track.

        If custom_script_excerpt is provided, the AI re-analyses that text first to derive
        a new scene context (scene_summary, emotional_arc, key_themes) before regenerating
        the prompt and lyrics. The stored script_excerpt and scene_description are also updated.

        If no excerpt is provided, the existing stored scene context is reused (original behaviour).
        """
        album = await run_in_threadpool(_fetch_album, album_id, user_id or None)
        if album["status"] not in ("PLANNED",):
            raise HTTPException(status_code=400, detail="Can only replan tracks when album is PLANNED")

        track_resp = await run_in_threadpool(
            lambda: supabase.table("album_tracks").select("*").eq("id", track_id).single().execute()
        )
        track = track_resp.data
        if not track or track["album_id"] != album_id:
            raise HTTPException(status_code=404, detail="Track not found")

        from services.prompt_service import _call_openrouter
        import agents.album_agent as _ag

        # ── Determine effective scene context ─────────────────────────────────
        effective_scene = track.get("scene_description", "")
        effective_emotional_arc = ""
        effective_key_themes: list = []

        if custom_script_excerpt:
            logger.info("replan_track: re-analysing custom excerpt for track_id=%s", track_id)
            try:
                reanalysis_raw = await _call_openrouter(_REANALYZE_SYSTEM, custom_script_excerpt)
                reanalysis = _ag._parse_json(reanalysis_raw, "replan_track/reanalysis")
                effective_scene = reanalysis.get("scene_summary", effective_scene)
                effective_emotional_arc = reanalysis.get("emotional_arc", "")
                effective_key_themes = reanalysis.get("key_themes", [])
                logger.info("replan_track re-analysis OK: new_scene=%.80s", effective_scene)
            except Exception as exc:
                logger.warning("replan_track re-analysis failed, falling back to stored scene: %s", exc)

        # ── Generate new prompt ───────────────────────────────────────────────
        prompt_system = (
            (Path(__file__).parent.parent / "prompts" / "album_prompt_generation.md")
            .read_text(encoding="utf-8")
            .strip()
        )
        prompt_user = json.dumps([{
            "track_number": track["track_number"],
            "scene_description": effective_scene,
            "suggested_style": track.get("suggested_style", ""),
            "suggested_mood": track.get("suggested_mood", ""),
            "suggested_tempo": track.get("suggested_tempo", ""),
            "make_instrumental": track.get("make_instrumental", False),
        }])

        raw = await _call_openrouter(prompt_system, prompt_user)
        parsed = _ag._parse_json(raw, "replan_track")
        prompt_list = parsed.get("prompts", [parsed]) if isinstance(parsed, dict) else parsed
        new_prompt_data = prompt_list[0] if prompt_list else {}

        patch: dict = {}
        if new_prompt_data.get("prompt"):
            patch["prompt"] = new_prompt_data["prompt"][:280]
        if new_prompt_data.get("music_style"):
            patch["music_style"] = new_prompt_data["music_style"]

        # Sync scene context when custom excerpt was provided
        if custom_script_excerpt:
            patch["script_excerpt"] = custom_script_excerpt[:500]
            patch["scene_description"] = effective_scene

        # ── Regenerate lyrics if vocal ────────────────────────────────────────
        if not track.get("make_instrumental"):
            lyrics_system = (
                (Path(__file__).parent.parent / "prompts" / "album_lyrics_generation.md")
                .read_text(encoding="utf-8")
                .strip()
            )
            lyrics_user = json.dumps([{
                "track_number": track["track_number"],
                "make_instrumental": False,
                "scene_description": effective_scene,
                "script_excerpt": custom_script_excerpt or track.get("script_excerpt", ""),
                "emotional_arc": effective_emotional_arc or "",
                "key_themes": effective_key_themes or [],
                "suggested_mood": track.get("suggested_mood", ""),
                "suggested_style": track.get("suggested_style", ""),
            }])
            try:
                lyrics_raw = await _call_openrouter(lyrics_system, lyrics_user)
                lyrics_parsed = _ag._parse_json(lyrics_raw, "replan_track/lyrics")
                lyrics_list = lyrics_parsed.get("lyrics", [lyrics_parsed]) if isinstance(lyrics_parsed, dict) else lyrics_parsed
                patch["lyrics"] = lyrics_list[0].get("lyrics", "") if lyrics_list else ""
            except Exception as exc:
                logger.warning("replan_track lyrics generation failed: %s", exc)

        if patch:
            await run_in_threadpool(
                lambda: supabase.table("album_tracks").update(patch).eq("id", track_id).execute()
            )
            logger.info("Track replanned: track_id=%s custom_excerpt=%s", track_id, bool(custom_script_excerpt))

        updated = await run_in_threadpool(
            lambda: supabase.table("album_tracks").select("*").eq("id", track_id).single().execute()
        )
        return updated.data

    # ── Enhancement 3: Regenerate single track ────────────────────────────────

    @staticmethod
    async def regenerate_track(album_id: str, track_id: str, background_tasks: BackgroundTasks, user_id: str = "") -> dict:
        """Re-generate music for one track (after album is GENERATING or COMPLETED)."""
        album = await run_in_threadpool(_fetch_album, album_id, user_id or None)
        if album["status"] not in ("GENERATING", "COMPLETED", "FAILED"):
            raise HTTPException(status_code=400, detail="Album must be GENERATING or COMPLETED to regenerate a track")

        track_resp = await run_in_threadpool(
            lambda: supabase.table("album_tracks").select("*").eq("id", track_id).single().execute()
        )
        track = track_resp.data
        if not track or track["album_id"] != album_id:
            raise HTTPException(status_code=404, detail="Track not found")

        music_type = "music" if track.get("make_instrumental") else "vocal"

        # Mark as pending before Celery picks it up
        await run_in_threadpool(
            lambda: supabase.table("album_tracks").update({"status": "PENDING"}).eq("id", track_id).execute()
        )

        process_album_track_task.apply_async(
            args=[
                album_id,
                track_id,
                album["project_id"],
                album["user_id"],
                album["user_name"],
                album["user_email"],
                music_type,
                track["prompt"] or "",
            ],
            kwargs={
                "music_style": track.get("music_style"),
                "lyrics": track.get("lyrics"),
                "make_instrumental": track.get("make_instrumental", False),
                "gender": track.get("gender"),
                "output_length": track.get("output_length"),
            },
            queue="musicgpt_album",
        )

        # Re-arm completion monitor
        background_tasks.add_task(AlbumService.monitor_album_completion, album_id)

        # Ensure album is in GENERATING state
        await run_in_threadpool(
            lambda: supabase.table("albums").update({
                "status": "GENERATING",
                "updated_at": _now_iso(),
            }).eq("id", album_id).execute()
        )

        logger.info("Track regeneration enqueued to Celery: track_id=%s", track_id)
        updated = await run_in_threadpool(
            lambda: supabase.table("album_tracks").select("*").eq("id", track_id).single().execute()
        )
        return updated.data
