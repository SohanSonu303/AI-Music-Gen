-- Migration: convert user_id TEXT → UUID with FK to users(id)
-- Run AFTER 006_create_auth_tables.sql
-- Strategy per table:
--   1. Convert TEXT → UUID (if still TEXT)
--   2. Reassign any user_id not present in users(id) → dummy user
--   3. Add FK constraint (idempotent)

-- Dummy user UUID seeded in migration 006
-- 00000000-0000-0000-0000-000000000001

-- ══════════════════════════════════════════════
-- music_metadata
-- ══════════════════════════════════════════════
DO $$ BEGIN
  -- Step 1: TEXT → UUID conversion (only if still text)
  IF (SELECT data_type FROM information_schema.columns
      WHERE table_schema='public' AND table_name='music_metadata' AND column_name='user_id') = 'text' THEN
    UPDATE music_metadata
    SET user_id = '00000000-0000-0000-0000-000000000001'
    WHERE user_id IS NULL
       OR user_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

    ALTER TABLE music_metadata
      ALTER COLUMN user_id TYPE UUID USING user_id::UUID;
  END IF;

  -- Step 2: Reassign orphaned UUIDs → dummy user
  UPDATE music_metadata
  SET user_id = '00000000-0000-0000-0000-000000000001'
  WHERE user_id NOT IN (SELECT id FROM users);

  -- Step 3: FK (idempotent)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema='public' AND table_name='music_metadata'
      AND constraint_name='fk_music_metadata_user'
  ) THEN
    ALTER TABLE music_metadata
      ADD CONSTRAINT fk_music_metadata_user
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ══════════════════════════════════════════════
-- albums
-- ══════════════════════════════════════════════
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns
      WHERE table_schema='public' AND table_name='albums' AND column_name='user_id') = 'text' THEN
    UPDATE albums
    SET user_id = '00000000-0000-0000-0000-000000000001'
    WHERE user_id IS NULL
       OR user_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

    ALTER TABLE albums
      ALTER COLUMN user_id TYPE UUID USING user_id::UUID;
  END IF;

  UPDATE albums
  SET user_id = '00000000-0000-0000-0000-000000000001'
  WHERE user_id NOT IN (SELECT id FROM users);

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema='public' AND table_name='albums'
      AND constraint_name='fk_albums_user'
  ) THEN
    ALTER TABLE albums
      ADD CONSTRAINT fk_albums_user
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ══════════════════════════════════════════════
-- editing_table
-- ══════════════════════════════════════════════
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns
      WHERE table_schema='public' AND table_name='editing_table' AND column_name='user_id') = 'text' THEN
    UPDATE editing_table
    SET user_id = '00000000-0000-0000-0000-000000000001'
    WHERE user_id IS NULL
       OR user_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

    ALTER TABLE editing_table
      ALTER COLUMN user_id TYPE UUID USING user_id::UUID;
  END IF;

  UPDATE editing_table
  SET user_id = '00000000-0000-0000-0000-000000000001'
  WHERE user_id NOT IN (SELECT id FROM users);

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema='public' AND table_name='editing_table'
      AND constraint_name='fk_editing_table_user'
  ) THEN
    ALTER TABLE editing_table
      ADD CONSTRAINT fk_editing_table_user
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ══════════════════════════════════════════════
-- sound_generations
-- ══════════════════════════════════════════════
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns
      WHERE table_schema='public' AND table_name='sound_generations' AND column_name='user_id') = 'text' THEN
    UPDATE sound_generations
    SET user_id = '00000000-0000-0000-0000-000000000001'
    WHERE user_id IS NULL
       OR user_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

    ALTER TABLE sound_generations
      ALTER COLUMN user_id TYPE UUID USING user_id::UUID;
  END IF;

  UPDATE sound_generations
  SET user_id = '00000000-0000-0000-0000-000000000001'
  WHERE user_id NOT IN (SELECT id FROM users);

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema='public' AND table_name='sound_generations'
      AND constraint_name='fk_sound_generations_user'
  ) THEN
    ALTER TABLE sound_generations
      ADD CONSTRAINT fk_sound_generations_user
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ══════════════════════════════════════════════
-- projects
-- ══════════════════════════════════════════════
DO $$ BEGIN
  -- Only process if user_id column exists
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='projects' AND column_name='user_id'
  ) THEN
    IF (SELECT data_type FROM information_schema.columns
        WHERE table_schema='public' AND table_name='projects' AND column_name='user_id') = 'text' THEN
      UPDATE projects
      SET user_id = '00000000-0000-0000-0000-000000000001'
      WHERE user_id IS NULL
         OR user_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';

      ALTER TABLE projects
        ALTER COLUMN user_id TYPE UUID USING user_id::UUID;
    END IF;

    UPDATE projects
    SET user_id = '00000000-0000-0000-0000-000000000001'
    WHERE user_id NOT IN (SELECT id FROM users);

    IF NOT EXISTS (
      SELECT 1 FROM information_schema.table_constraints
      WHERE table_schema='public' AND table_name='projects'
        AND constraint_name='fk_projects_user'
    ) THEN
      ALTER TABLE projects
        ADD CONSTRAINT fk_projects_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
  END IF;
END $$;

-- ══════════════════════════════════════════════
-- user_prompts  (already UUID — backfill + FK)
-- ══════════════════════════════════════════════
DO $$ BEGIN
  UPDATE user_prompts
  SET user_id = '00000000-0000-0000-0000-000000000001'
  WHERE user_id IS NULL
     OR user_id NOT IN (SELECT id FROM users);

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema='public' AND table_name='user_prompts'
      AND constraint_name='fk_user_prompts_user'
  ) THEN
    ALTER TABLE user_prompts
      ADD CONSTRAINT fk_user_prompts_user
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ══════════════════════════════════════════════
-- audio_separations  (already UUID — backfill + FK)
-- ══════════════════════════════════════════════
DO $$ BEGIN
  UPDATE audio_separations
  SET user_id = '00000000-0000-0000-0000-000000000001'
  WHERE user_id IS NULL
     OR user_id NOT IN (SELECT id FROM users);

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE table_schema='public' AND table_name='audio_separations'
      AND constraint_name='fk_audio_separations_user'
  ) THEN
    ALTER TABLE audio_separations
      ADD CONSTRAINT fk_audio_separations_user
      FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
  END IF;
END $$;

-- album_tracks: NOT touched — RLS joins through albums.user_id
