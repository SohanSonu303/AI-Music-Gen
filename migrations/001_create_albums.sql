-- Migration: create albums and album_tracks tables
-- Run this in your Supabase SQL editor or via psql

-- albums table: stores user input + album-level lifecycle status
CREATE TABLE IF NOT EXISTS albums (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_name TEXT NOT NULL,
    user_email TEXT NOT NULL,
    title TEXT,
    script TEXT NOT NULL,
    num_songs INTEGER NOT NULL CHECK (num_songs BETWEEN 1 AND 20),
    -- track_composition: JSON string e.g. {"songs":1,"background_scores":2,"instrumentals":0}
    track_composition TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNING',
    -- style_palette: JSON string with {primary_genre, bpm_range, key_signature, instrumentation_family, mood_arc}
    style_palette TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ
);

-- album_tracks table: per-track AI planning data + links to music_metadata after generation
CREATE TABLE IF NOT EXISTS album_tracks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    album_id UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    track_number INTEGER NOT NULL,
    -- track_type: 'song' (vocal+lyrics) | 'background_score' (cinematic instrumental) | 'instrumental' (structured no-vocal)
    track_type TEXT NOT NULL DEFAULT 'song',
    scene_description TEXT,
    suggested_style TEXT,
    suggested_mood TEXT,
    suggested_tempo TEXT,
    prompt TEXT,
    music_style TEXT,
    lyrics TEXT,
    make_instrumental BOOLEAN NOT NULL DEFAULT false,
    gender TEXT,
    output_length INTEGER,
    -- populated after user approves and generation starts
    music_metadata_id UUID,
    task_id TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    -- energy_level: 1-10 intensity score for mood arc visualization
    energy_level INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
