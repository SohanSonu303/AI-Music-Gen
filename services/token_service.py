import logging
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from supabase_client import supabase

logger = logging.getLogger(__name__)


class InsufficientTokensError(Exception):
    def __init__(self, balance: int, required: int):
        self.balance = balance
        self.required = required
        super().__init__(f"Insufficient tokens: balance={balance}, required={required}")


def get_balance(user_id: str) -> int:
    row = (
        supabase.table("token_balances")
        .select("balance")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return row.data["balance"]


def debit_tokens(
    user_id: str,
    amount: int,
    reason: str,
    job_id: Optional[str] = None,
) -> int:
    try:
        result = supabase.rpc(
            "debit_tokens_atomic",
            {
                "p_user_id": user_id,
                "p_amount": amount,
                "p_reason": reason,
                "p_job_id": job_id,
            },
        ).execute()
        new_balance: int = result.data
        logger.info(
            "Token debit: user=%s amount=%d reason=%s job_id=%s new_balance=%d",
            user_id, amount, reason, job_id, new_balance,
        )
        return new_balance
    except Exception as exc:
        msg = str(exc)
        if "insufficient_tokens" in msg:
            # Parse balance/required from the Postgres exception message
            balance = 0
            try:
                part = msg.split("balance=")[1]
                balance = int(part.split(",")[0])
            except Exception:
                pass
            raise InsufficientTokensError(balance=balance, required=amount) from exc
        raise


def credit_tokens(
    user_id: str,
    amount: int,
    reason: str,
    job_id: Optional[str] = None,
) -> int:
    result = supabase.rpc(
        "credit_tokens_atomic",
        {
            "p_user_id": user_id,
            "p_amount": amount,
            "p_reason": reason,
            "p_job_id": job_id,
        },
    ).execute()
    new_balance: int = result.data
    logger.info(
        "Token credit: user=%s amount=%d reason=%s job_id=%s new_balance=%d",
        user_id, amount, reason, job_id, new_balance,
    )
    return new_balance


def refund_tokens(user_id: str, amount: int, job_id: str) -> int:
    return credit_tokens(user_id, amount, reason="refund", job_id=job_id)


def monthly_reset(user_id: str, plan: str) -> int:
    plan_allotments = {
        "free": 500,
        "starter": 2000,
        "pro": 6000,
        "enterprise": 20000,
    }
    allotment = plan_allotments.get(plan, 500)

    # Reset used_tokens to 0 and set total_tokens to plan allotment
    supabase.table("token_balances").update(
        {"used_tokens": 0, "total_tokens": allotment}
    ).eq("user_id", user_id).execute()

    supabase.table("token_transactions").insert({
        "user_id": user_id,
        "type": "monthly_reset",
        "amount": allotment,
        "balance_after": allotment,
        "reason": f"monthly_reset_{plan}",
    }).execute()

    logger.info("Monthly reset: user=%s plan=%s new_balance=%d", user_id, plan, allotment)
    return allotment


def require_tokens(user_id: str, amount: int, reason: str, job_id: Optional[str] = None) -> int:
    """Debit tokens and raise HTTP 402 if insufficient — for use in routers."""
    try:
        return debit_tokens(user_id, amount, reason, job_id)
    except InsufficientTokensError as exc:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient tokens: you have {exc.balance}, need {exc.required}.",
        ) from exc
