"""
Tests for GitHub webhook signature verification.

GitHub signs every webhook payload with HMAC-SHA256 using the webhook secret.
The signature is sent in the X-Hub-Signature-256 header as "sha256=<hex>".
We must reject requests with missing or wrong signatures with 401.
"""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

WEBHOOK_SECRET = "test-webhook-secret-for-pytest"


def _sign(payload: bytes) -> str:
    """Compute the HMAC-SHA256 signature GitHub would send."""
    mac = hmac.new(WEBHOOK_SECRET.encode("utf-8"), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


@pytest.fixture
def async_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_ping_with_valid_signature(async_client):
    """GitHub sends a 'ping' event when the App is first installed — must return 200."""
    payload = json.dumps({"zen": "Keep it logically awesome."}).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_signature(async_client):
    """Tampered payload must be rejected with 401."""
    payload = json.dumps({"action": "opened"}).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=deadbeefdeadbeef",
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 401
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(async_client):
    """Request with no X-Hub-Signature-256 header must be rejected with 401."""
    payload = json.dumps({"action": "opened"}).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_issues_opened_event_accepted(async_client):
    """A valid 'issues' opened event must be accepted (returns 202 Accepted)."""
    payload = json.dumps({
        "action": "opened",
        "issue": {"number": 42, "title": "Something is broken"},
        "repository": {"id": 1, "full_name": "owner/repo"},
        "installation": {"id": 99},
    }).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_installation_event_accepted(async_client):
    """A valid 'installation' created event must be accepted (returns 202 Accepted)."""
    payload = json.dumps({
        "action": "created",
        "installation": {"id": 99, "account": {"login": "owner"}},
        "repositories": [{"id": 1, "full_name": "owner/repo"}],
    }).encode()

    # Mock the DB session and backfill task to avoid real I/O
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 1
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.api.webhooks.AsyncSessionLocal", return_value=mock_session_cm),
        patch("app.api.webhooks.backfill_repo") as mock_task,
    ):
        async with async_client as client:
            response = await client.post(
                "/webhooks/github",
                content=payload,
                headers={
                    "X-Hub-Signature-256": _sign(payload),
                    "X-GitHub-Event": "installation",
                    "Content-Type": "application/json",
                },
            )
    assert response.status_code == 202


INSTALLATION_PAYLOAD = {
    "action": "created",
    "installation": {"id": 55555},
    "repositories": [
        {"id": 999001, "name": "myrepo", "full_name": "alice/myrepo"}
    ],
    "sender": {"login": "alice"},
}


@pytest.mark.asyncio
async def test_installation_created_enqueues_backfill(async_client):
    """Installation webhook must upsert Repo and enqueue backfill_repo task."""
    body = json.dumps(INSTALLATION_PAYLOAD).encode()
    sig = _sign(body)

    # Mock the DB session to return a fake repo_id without hitting Postgres
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = 42
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.api.webhooks.AsyncSessionLocal", return_value=mock_session_cm),
        patch("app.api.webhooks.backfill_repo") as mock_task,
    ):
        async with async_client as client:
            response = await client.post(
                "/webhooks/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "installation",
                    "Content-Type": "application/json",
                },
            )

    assert response.status_code == 202
    mock_task.delay.assert_called_once_with(42)
