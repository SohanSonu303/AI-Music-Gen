-- Migration: create editing_table for saved audio edits
-- Run this in your Supabase SQL editor
-- Only populated when the user explicitly clicks "Save to Cloud" in the UI

CREATE TABLE IF NOT EXISTS editing_table (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    -- operation: 'cut' | 'split' | 'fade' | 'eq' | 'loop' | 'mix' | 'overlay'
    operation TEXT NOT NULL,
    -- operation_params: operation-specific input params e.g. {"start_ms": 0, "end_ms": 10000}
    operation_params JSONB,
    source_url TEXT NOT NULL,
    output_url TEXT NOT NULL,
    output_format TEXT NOT NULL DEFAULT 'mp3',
    output_duration FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
