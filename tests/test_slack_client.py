import httpx
import pytest

from scripts.slack_client import SlackClient

FAKE_URL = "https://hooks.slack.com/services/TEST/TEST/TEST"


def client_returning(status, text="", headers=None):
    def handler(request):
        return httpx.Response(status, text=text, headers=headers or {})
    return SlackClient(FAKE_URL, transport=httpx.MockTransport(handler))


def client_raising(exc):
    def handler(request):
        raise exc
    return SlackClient(FAKE_URL, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_ok_means_sent():
    result = await client_returning(200, "ok").send({"text": "hi"})
    assert result.outcome == "sent"


@pytest.mark.asyncio
async def test_429_means_rate_limited_with_wait():
    result = await client_returning(429, headers={"Retry-After": "12"}).send({"text": "hi"})
    assert result.outcome == "rate_limited"
    assert result.retry_after == 12


@pytest.mark.asyncio
async def test_500_means_retry():
    result = await client_returning(503).send({"text": "hi"})
    assert result.outcome == "retry"


@pytest.mark.asyncio
async def test_archived_channel_means_park():
    result = await client_returning(410, "channel_is_archived").send({"text": "hi"})
    assert result.outcome == "park"
    assert "channel_is_archived" in result.error


@pytest.mark.asyncio
async def test_timeout_means_retry():
    result = await client_raising(httpx.ReadTimeout("slow")).send({"text": "hi"})
    assert result.outcome == "retry"
    assert result.error == "timeout"


@pytest.mark.asyncio
async def test_error_never_contains_the_url():
    exc = httpx.ConnectError(f"cannot connect to {FAKE_URL}")
    result = await client_raising(exc).send({"text": "hi"})
    assert result.outcome == "retry"
    assert "hooks.slack.com" not in result.error
