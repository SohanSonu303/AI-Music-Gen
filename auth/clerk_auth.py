import logging
import os
import time
from typing import Optional
from uuid import UUID

import httpx
import jwt
from fastapi import Header, HTTPException
from jwt.algorithms import RSAAlgorithm
from supabase import create_client, Client

from models.auth_model import UserContext
from supabase_client import supabase as _service_supabase

logger = logging.getLogger(__name__)

CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL", "")
CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# ──────────────────────────────────────────────
# JWKS cache (TTL = 5 minutes)
# ──────────────────────────────────────────────
_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 300


def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    if time.time() - _jwks_fetched_at < _JWKS_TTL and _jwks_cache:
        return _jwks_cache
    response = httpx.get(CLERK_JWKS_URL, timeout=10)
    response.raise_for_status()
    _jwks_cache = response.json()
    _jwks_fetched_at = time.time()
    return _jwks_cache


def _get_public_key(kid: str):
    jwks = _get_jwks()
    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            return RSAAlgorithm.from_jwk(key_data)
    # kid mismatch — force refresh and retry once
    global _jwks_fetched_at
    _jwks_fetched_at = 0.0
    jwks = _get_jwks()
    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            return RSAAlgorithm.from_jwk(key_data)
    raise HTTPException(status_code=401, detail="Unknown JWT key ID")


# ──────────────────────────────────────────────
# JWT verification
# ──────────────────────────────────────────────

def verify_clerk_jwt(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise HTTPException(status_code=401, detail="Malformed JWT") from exc

    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="JWT missing kid")

    public_key = _get_public_key(kid)

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            options={"verify_exp": True},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT expired")
    except jwt.InvalidIssuerError:
        raise HTTPException(status_code=401, detail="JWT issuer mismatch")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"JWT invalid: {exc}") from exc

    return claims


# ──────────────────────────────────────────────
# User upsert via Postgres function
# ──────────────────────────────────────────────

def _upsert_user(clerk_user_id: str, email: str, full_name: Optional[str], avatar_url: Optional[str]) -> UUID:
    result = _service_supabase.rpc(
        "create_user_with_defaults",
        {
            "p_clerk_id": clerk_user_id,
            "p_email": email,
            "p_full_name": full_name or "",
            "p_avatar_url": avatar_url or "",
        },
    ).execute()
    return UUID(result.data)


# ──────────────────────────────────────────────
# FastAPI dependencies
# ──────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(default=None)) -> UserContext:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must be 'Bearer <token>'")

    token = authorization.removeprefix("Bearer ").strip()
    claims = verify_clerk_jwt(token)

    clerk_user_id: str = claims["sub"]
    email: str = claims.get("email", "")
    full_name: Optional[str] = claims.get("name")
    avatar_url: Optional[str] = claims.get("image_url") or claims.get("picture")

    # Look up existing user
    try:
        row = (
            _service_supabase.table("users")
            .select("id, email, full_name")
            .eq("clerk_user_id", clerk_user_id)
            .maybe_single()
            .execute()
        )
    except Exception as exc:
        logger.error("DB lookup failed for clerk_user_id=%s: %s", clerk_user_id, exc)
        raise HTTPException(status_code=500, detail="Database error during auth. Have migrations 006-008 been run?")

    if row and row.data:
        user_id = UUID(row.data["id"])
        stored_full_name = row.data.get("full_name")
    else:
        user_id = _upsert_user(clerk_user_id, email, full_name, avatar_url)
        stored_full_name = full_name
        logger.info("New user created: clerk_user_id=%s internal_id=%s", clerk_user_id, user_id)

    return UserContext(
        id=user_id,
        clerk_user_id=clerk_user_id,
        email=email,
        full_name=stored_full_name,
        jwt=token,
    )


def get_current_user_optional(authorization: Optional[str] = Header(default=None)) -> Optional[UserContext]:
    if not authorization:
        return None
    try:
        return get_current_user(authorization)
    except HTTPException:
        return None


# ──────────────────────────────────────────────
# Per-request RLS-scoped Supabase client
# ──────────────────────────────────────────────

def get_scoped_supabase(user_ctx: UserContext) -> Client:
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    client.auth.set_session(access_token=user_ctx.jwt, refresh_token="")
    return client
