-- Migration: enable Row Level Security on all user-owned tables
-- Run AFTER 007_migrate_user_id_to_uuid.sql
--
-- Clerk JWT Template must be configured in the Clerk dashboard:
--   Template name: supabase
--   Claim: sub = internal users.id UUID
--   Signing key: SUPABASE_JWT_SECRET
-- auth.uid() in these policies resolves to that sub claim (users.id UUID).
--
-- Service-role key (used by Celery / webhooks) bypasses RLS automatically.

-- ──────────────────────────────────────────────
-- Auth / wallet tables  (self-read only)
-- ──────────────────────────────────────────────
ALTER TABLE users              ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions      ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_balances     ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_reads_own_profile
    ON users FOR SELECT
    USING (id = auth.uid());

CREATE POLICY user_reads_own_subscription
    ON subscriptions FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_reads_own_token_balance
    ON token_balances FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_reads_own_token_transactions
    ON token_transactions FOR ALL
    USING (user_id = auth.uid());

-- ──────────────────────────────────────────────
-- Direct-ownership tables
-- ──────────────────────────────────────────────
ALTER TABLE music_metadata   ENABLE ROW LEVEL SECURITY;
ALTER TABLE albums           ENABLE ROW LEVEL SECURITY;
ALTER TABLE editing_table    ENABLE ROW LEVEL SECURITY;
ALTER TABLE sound_generations ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects         ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_prompts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE audio_separations ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_owns_music_metadata
    ON music_metadata FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_owns_albums
    ON albums FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_owns_editing_table
    ON editing_table FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_owns_sound_generations
    ON sound_generations FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_owns_projects
    ON projects FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_owns_user_prompts
    ON user_prompts FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY user_owns_audio_separations
    ON audio_separations FOR ALL
    USING (user_id = auth.uid());

-- ──────────────────────────────────────────────
-- album_tracks  (indirect ownership via albums.user_id)
-- ──────────────────────────────────────────────
ALTER TABLE album_tracks ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_owns_album_track
    ON album_tracks FOR ALL
    USING (
        album_id IN (
            SELECT id FROM albums WHERE user_id = auth.uid()
        )
    );
