-- Migration 004: separate stable client-facing task_id from MusicGPT's internal task_id
-- music_metadata.task_id = stable UUID pre-generated before calling MusicGPT (returned to client)
-- music_metadata.musicgpt_task_id = real task_id from MusicGPT response (used for polling API)
-- For album tracks (which insert after MusicGPT responds) both columns hold the same value.

ALTER TABLE music_metadata
    ADD COLUMN IF NOT EXISTS musicgpt_task_id TEXT;
