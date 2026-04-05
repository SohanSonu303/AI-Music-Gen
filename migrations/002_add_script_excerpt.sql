-- Migration 002: add script_excerpt column to album_tracks
-- Run in Supabase SQL editor after 001_create_albums.sql

ALTER TABLE album_tracks
    ADD COLUMN IF NOT EXISTS script_excerpt TEXT;
