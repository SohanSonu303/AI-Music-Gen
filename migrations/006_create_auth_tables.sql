-- Migration: create auth tables for Clerk + token wallet
-- Run this in your Supabase SQL editor BEFORE running 007 and 008

-- ──────────────────────────────────────────────
-- 1. users
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    clerk_user_id   TEXT        UNIQUE NOT NULL,
    email           TEXT        NOT NULL,
    full_name       TEXT,
    avatar_url      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────────
-- 2. subscriptions
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                 UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan                    TEXT        NOT NULL DEFAULT 'free',       -- 'free' | 'starter' | 'pro' | 'enterprise'
    status                  TEXT        NOT NULL DEFAULT 'active',     -- 'active' | 'cancelled' | 'expired'
    payment_customer_id     TEXT,                                      -- generic (Dodo / Stripe / …)
    payment_subscription_id TEXT,
    current_period_start    TIMESTAMPTZ,
    current_period_end      TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────────
-- 3. token_balances
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_balances (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID        NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    total_tokens        INT         NOT NULL DEFAULT 0,
    used_tokens         INT         NOT NULL DEFAULT 0,
    balance             INT         GENERATED ALWAYS AS (total_tokens - used_tokens) STORED,
    monthly_reset_date  TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────────
-- 4. token_transactions
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_transactions (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type          TEXT        NOT NULL,   -- 'credit' | 'debit' | 'refund' | 'monthly_reset'
    amount        INT         NOT NULL,
    balance_after INT         NOT NULL,
    reason        TEXT,                   -- 'signup_bonus' | 'music_generation' | 'refund' | …
    job_id        UUID,                   -- links to music_metadata or album_tracks
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ──────────────────────────────────────────────
-- 5. Seed dummy user (target for legacy data backfill in migration 007)
-- ──────────────────────────────────────────────
INSERT INTO users (id, clerk_user_id, email, full_name)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'legacy_dummy_user',
    'legacy@placeholder.invalid',
    'Legacy Data User'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO subscriptions (user_id, plan, status)
VALUES ('00000000-0000-0000-0000-000000000001', 'free', 'active')
ON CONFLICT DO NOTHING;

INSERT INTO token_balances (user_id, total_tokens, used_tokens)
VALUES ('00000000-0000-0000-0000-000000000001', 0, 0)
ON CONFLICT DO NOTHING;

-- ──────────────────────────────────────────────
-- 6. Atomic user-creation helper (called by get_current_user dependency)
-- ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION create_user_with_defaults(
    p_clerk_id   TEXT,
    p_email      TEXT,
    p_full_name  TEXT,
    p_avatar_url TEXT
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_user_id UUID;
BEGIN
    INSERT INTO users (clerk_user_id, email, full_name, avatar_url)
    VALUES (p_clerk_id, p_email, p_full_name, p_avatar_url)
    ON CONFLICT (clerk_user_id) DO UPDATE
        SET email      = EXCLUDED.email,
            full_name  = EXCLUDED.full_name,
            avatar_url = EXCLUDED.avatar_url,
            updated_at = now()
    RETURNING id INTO v_user_id;

    INSERT INTO subscriptions (user_id, plan, status)
    VALUES (v_user_id, 'free', 'active')
    ON CONFLICT DO NOTHING;

    INSERT INTO token_balances (user_id, total_tokens, used_tokens)
    VALUES (v_user_id, 500, 0)
    ON CONFLICT DO NOTHING;

    INSERT INTO token_transactions (user_id, type, amount, balance_after, reason)
    VALUES (v_user_id, 'credit', 500, 500, 'signup_bonus')
    ON CONFLICT DO NOTHING;

    RETURN v_user_id;
END;
$$;
