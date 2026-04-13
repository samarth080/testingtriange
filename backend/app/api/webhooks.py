"""
GitHub App webhook receiver.

Security: Every request is authenticated via HMAC-SHA256 signature verification
(X-Hub-Signature-256 header). We compare with hmac.compare_digest() to prevent
timing attacks. Requests with missing or invalid signatures are rejected 401.

Event routing: We read X-GitHub-Event and dispatch to the appropriate handler.
Unknown events are acknowledged with 200 so GitHub doesn't retry them.

Async design: Handlers enqueue Celery tasks and return immediately — webhook
requests must respond within 10 seconds or GitHub will retry. The actual
triage work happens in the background worker.
"""
import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.orm import Repo
from app.workers.ingestion_tasks import backfill_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(payload: bytes, signature_header: str | None) -> None:
    """
    Verify GitHub's HMAC-SHA256 payload signature.

    Raises HTTPException(401) if the signature is missing or does not match.
    Uses hmac.compare_digest to prevent timing attacks.
    """
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    secret = settings.github_webhook_secret
    if not secret:
        raise HTTPException(status_code=401, detail="Webhook secret not configured")

    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature — payload may have been tampered")


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> Response:
    """
    Receive and dispatch GitHub App webhook events.

    Flow:
    1. Read raw body (must happen before any JSON parsing to preserve bytes for HMAC)
    2. Verify HMAC-SHA256 signature
    3. Parse JSON body
    4. Dispatch to event handler
    5. Return quickly — handlers must not do blocking work here
    """
    # Step 1: Read raw bytes first — signature verification requires the exact bytes GitHub sent
    payload = await request.body()

    # Step 2: Verify signature before touching the payload content
    _verify_signature(payload, x_hub_signature_256)

    # Step 3: Parse body
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = x_github_event or "unknown"
    logger.info("Received GitHub event: %s", event)

    # Step 4: Dispatch
    if event == "ping":
        return Response(content='{"status":"ok"}', media_type="application/json", status_code=200)

    if event == "installation":
        return await _handle_installation(body)

    if event == "issues":
        return await _handle_issues(body)

    if event in ("pull_request", "push"):
        # Will be wired to index-update tasks in Day 2
        return Response(status_code=202)

    # Unknown events: acknowledge so GitHub stops retrying
    logger.debug("Unhandled event type: %s", event)
    return Response(status_code=200)


async def _handle_installation(body: dict) -> Response:
    """
    Handle GitHub App installation events.

    action=created → upsert Repo rows + enqueue backfill_repo for each repo
    action=deleted → log only (cleanup deferred to Day 8)
    """
    action = body.get("action")
    installation_id = body.get("installation", {}).get("id")
    repos = body.get("repositories", [])

    logger.info(
        "Installation event: action=%s installation_id=%s repos=%s",
        action,
        installation_id,
        [r.get("full_name") for r in repos],
    )

    if action == "created" and repos:
        async def _upsert_and_enqueue() -> None:
            async with AsyncSessionLocal() as session:
                for repo_data in repos:
                    owner, name = repo_data["full_name"].split("/", 1)
                    stmt = (
                        pg_insert(Repo)
                        .values(
                            github_id=repo_data["id"],
                            owner=owner,
                            name=name,
                            installation_id=installation_id,
                            backfill_status="running",
                        )
                        .on_conflict_do_update(
                            constraint="uq_repos_github_id",
                            set_={
                                "installation_id": installation_id,
                                "backfill_status": "running",
                            },
                        )
                        .returning(Repo.id)
                    )
                    result = await session.execute(stmt)
                    repo_id = result.scalar_one()
                    await session.commit()

                    backfill_repo.delay(repo_id)
                    logger.info(
                        "Enqueued backfill_repo for repo_id=%d (%s)",
                        repo_id,
                        repo_data["full_name"],
                    )

        await _upsert_and_enqueue()

    return Response(status_code=202)


async def _handle_issues(body: dict) -> Response:
    """
    Handle GitHub issues events.

    action=opened → new issue → enqueue triage task (Day 5)
    Other actions (edited, closed, etc.) → no-op for now
    """
    action = body.get("action")
    issue_number = body.get("issue", {}).get("number")
    repo_full_name = body.get("repository", {}).get("full_name")

    logger.info(
        "Issues event: action=%s issue=#%s repo=%s",
        action, issue_number, repo_full_name
    )

    if action == "opened":
        # TODO Day 5: enqueue triage_issue.delay(issue_id) after storing the issue
        pass

    return Response(status_code=202)
