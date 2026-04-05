-- Migration 003: store both MusicGPT conversion rows per album track
-- MusicGPT always returns two conversion_ids per job; album_tracks now
-- holds both corresponding music_metadata UUIDs.

ALTER TABLE album_tracks
    ADD COLUMN IF NOT EXISTS music_metadata_id_2 UUID;
