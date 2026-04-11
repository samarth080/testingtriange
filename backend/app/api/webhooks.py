"""
GitHub App webhook receiver.

STUB — full implementation with HMAC-SHA256 verification added in Task 8.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github")
async def github_webhook() -> dict:
    return {"status": "stub"}
