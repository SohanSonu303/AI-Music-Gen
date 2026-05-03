CREATE TABLE IF NOT EXISTS audio_extractions (
    id            UUID        PRIMARY KEY,
    user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id    TEXT        NOT NULL,
    original_filename TEXT    NOT NULL,
    stems         TEXT        NOT NULL,     -- JSON array of requested stems
    task_id       TEXT,                     -- MusicGPT task_id from submit response
    conversion_id TEXT,                     -- MusicGPT conversion_id from submit response
    status        TEXT        NOT NULL DEFAULT 'IN_QUEUE',  -- QUEUED / IN_QUEUE / COMPLETED / FAILED
    vocals_url    TEXT,
    drums_url     TEXT,
    bass_url      TEXT,
    piano_url     TEXT,
    guitar_url    TEXT,
    error_message TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audio_extractions_user_id_idx      ON audio_extractions (user_id);
CREATE INDEX IF NOT EXISTS audio_extractions_conversion_id_idx ON audio_extractions (conversion_id);

ALTER TABLE audio_extractions ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_owns_audio_extractions
    ON audio_extractions FOR ALL
    USING (user_id = auth.uid());
