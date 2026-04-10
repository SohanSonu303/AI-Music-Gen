-- Migration 005: add error_message to music_metadata for failure visibility

ALTER TABLE music_metadata
    ADD COLUMN IF NOT EXISTS error_message TEXT;
