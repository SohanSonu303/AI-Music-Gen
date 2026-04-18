import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from svix.webhooks import Webhook, WebhookVerificationError

from auth.clerk_auth import get_current_user
from models.auth_model import UserContext
from supabase_client import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

CLERK_WEBHOOK_SECRET = os.environ.get("CLERK_WEBHOOK_SECRET", "")


# ──────────────────────────────────────────────
# GET /auth/me
# ──────────────────────────────────────────────

@router.get("/verify")
def verify_token(user: UserContext = Depends(get_current_user)):
    return {
        "valid": True,
        "user_id": str(user.id),
        "clerk_user_id": user.clerk_user_id,
        "email": user.email,
    }


@router.get("/me")
def get_me(user: UserContext = Depends(get_current_user)):
    user_row = (
        supabase.table("users")
        .select("*")
        .eq("id", str(user.id))
        .single()
        .execute()
    )
    subscription_row = (
        supabase.table("subscriptions")
        .select("*")
        .eq("user_id", str(user.id))
        .maybe_single()
        .execute()
    )
    balance_row = (
        supabase.table("token_balances")
        .select("total_tokens, used_tokens, balance, updated_at")
        .eq("user_id", str(user.id))
        .maybe_single()
        .execute()
    )
    return {
        "user": user_row.data,
        "subscription": subscription_row.data,
        "token_balance": balance_row.data,
    }


# ──────────────────────────────────────────────
# POST /auth/webhook/clerk
# ──────────────────────────────────────────────

@router.post("/webhook/clerk", status_code=200)
async def clerk_webhook(
    request: Request,
    svix_id: str = Header(alias="svix-id"),
    svix_timestamp: str = Header(alias="svix-timestamp"),
    svix_signature: str = Header(alias="svix-signature"),
):
    payload = await request.body()

    try:
        wh = Webhook(CLERK_WEBHOOK_SECRET)
        event = wh.verify(
            payload,
            {
                "svix-id": svix_id,
                "svix-timestamp": svix_timestamp,
                "svix-signature": svix_signature,
            },
        )
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type: str = event.get("type", "")
    data: dict = event.get("data", {})

    logger.info("Clerk webhook received: type=%s", event_type)

    if event_type == "user.created":
        _sync_user(data)

    elif event_type == "user.updated":
        _sync_user(data)

    elif event_type == "user.deleted":
        clerk_user_id = data.get("id")
        if clerk_user_id:
            supabase.table("users").delete().eq("clerk_user_id", clerk_user_id).execute()
            logger.info("Clerk webhook user.deleted: clerk_user_id=%s", clerk_user_id)

    return {"status": "ok"}


def _sync_user(data: dict) -> None:
    clerk_user_id = data.get("id")
    if not clerk_user_id:
        return

    primary_email = ""
    for ea in data.get("email_addresses", []):
        if ea.get("id") == data.get("primary_email_address_id"):
            primary_email = ea.get("email_address", "")
            break

    first = data.get("first_name") or ""
    last = data.get("last_name") or ""
    full_name = f"{first} {last}".strip() or None
    avatar_url = data.get("image_url")

    existing = (
        supabase.table("users")
        .select("id")
        .eq("clerk_user_id", clerk_user_id)
        .maybe_single()
        .execute()
    )

    if existing and existing.data:
        supabase.table("users").update(
            {
                "email": primary_email,
                "full_name": full_name,
                "avatar_url": avatar_url,
                "updated_at": "now()",
            }
        ).eq("clerk_user_id", clerk_user_id).execute()
        logger.info("Clerk webhook synced user: clerk_user_id=%s", clerk_user_id)
    else:
        # user.created before any API hit — call the same atomic function
        supabase.rpc(
            "create_user_with_defaults",
            {
                "p_clerk_id": clerk_user_id,
                "p_email": primary_email,
                "p_full_name": full_name or "",
                "p_avatar_url": avatar_url or "",
            },
        ).execute()
        logger.info("Clerk webhook created user: clerk_user_id=%s", clerk_user_id)
