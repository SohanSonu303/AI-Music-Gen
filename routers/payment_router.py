"""
Payment Router — Dodo Payments scaffold
========================================
Routes
------
  GET  /payment/plans         — public; static plan list with token allotments
  POST /payment/checkout      — 501 placeholder; will create Dodo checkout session
  POST /payment/webhook/dodo  — 501 placeholder; will verify Dodo webhook + credit tokens
  GET  /payment/subscription  — auth-protected; returns current user's subscription + balance
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from auth.clerk_auth import get_current_user
from models.auth_model import UserContext
from supabase_client import supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["Payment"])

PLANS = [
    {
        "id": "free",
        "name": "Free",
        "price_usd": 0,
        "tokens_per_month": 500,
        "description": "500 tokens/month — perfect for trying things out",
    },
    {
        "id": "starter",
        "name": "Starter",
        "price_usd": 9,
        "tokens_per_month": 2000,
        "description": "2,000 tokens/month — great for hobbyists",
    },
    {
        "id": "pro",
        "name": "Pro",
        "price_usd": 29,
        "tokens_per_month": 8000,
        "description": "8,000 tokens/month — for creators & professionals",
    },
    {
        "id": "unlimited",
        "name": "Unlimited",
        "price_usd": 79,
        "tokens_per_month": 30000,
        "description": "30,000 tokens/month — studios & power users",
    },
]


@router.get("/plans")
def list_plans():
    """Public — no auth required. Returns all available plans."""
    return JSONResponse({"plans": PLANS})


@router.post("/checkout")
async def create_checkout(
    plan_id: str,
    user: UserContext = Depends(get_current_user),
):
    """
    Initiate a Dodo Payments checkout session for the given plan.

    TODO: Replace 501 with real Dodo API call once account is set up.
    Will create a checkout session URL and return it to the client.
    """
    valid_ids = {p["id"] for p in PLANS}
    if plan_id not in valid_ids:
        raise HTTPException(status_code=422, detail=f"Unknown plan '{plan_id}'. Valid: {sorted(valid_ids)}")

    if plan_id == "free":
        raise HTTPException(status_code=400, detail="Free plan requires no checkout.")

    logger.info("Checkout requested: user_id=%s plan=%s (NOT YET IMPLEMENTED)", user.id, plan_id)
    raise HTTPException(
        status_code=501,
        detail="Payment checkout not yet implemented. Dodo Payments integration coming soon.",
    )


@router.post("/webhook/dodo")
async def dodo_webhook(request: Request):
    """
    Receive and verify Dodo Payments webhooks.

    TODO: Verify svix/Dodo signature, handle subscription.created /
    payment.completed / subscription.cancelled events, credit token_balances.
    """
    logger.info("Dodo webhook received (NOT YET IMPLEMENTED)")
    raise HTTPException(
        status_code=501,
        detail="Dodo webhook handler not yet implemented.",
    )


@router.get("/subscription")
async def get_subscription(user: UserContext = Depends(get_current_user)):
    """
    Return the current user's subscription plan and token balance.
    Works now — reads from the real DB (no Dodo account needed).
    """
    user_id = str(user.id)
    try:
        sub = (
            supabase.table("subscriptions")
            .select("plan, status, payment_customer_id, payment_subscription_id, current_period_end")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        bal = (
            supabase.table("token_balances")
            .select("total_tokens, used_tokens")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

        subscription = sub.data or {"plan": "free", "status": "active"}
        balance = bal.data or {"total_tokens": 0, "used_tokens": 0}
        remaining = balance["total_tokens"] - balance["used_tokens"]

        plan_detail = next((p for p in PLANS if p["id"] == subscription.get("plan", "free")), PLANS[0])

        return JSONResponse({
            "user_id": user_id,
            "subscription": subscription,
            "token_balance": {
                "total": balance["total_tokens"],
                "used": balance["used_tokens"],
                "remaining": remaining,
            },
            "plan": plan_detail,
        })
    except Exception as e:
        logger.error("Failed to fetch subscription: user_id=%s error=%s", user_id, e)
        raise HTTPException(status_code=500, detail=str(e))
