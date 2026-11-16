import json
import uuid

import pytest

from scripts.sender import MAX_ATTEMPTS, send_one_alert
from scripts.slack_client import SendResult
from scripts.slack_settings import set_slack_enabled
from tests.fake_slack import FakeSlack


# ---------- helpers ----------

@pytest.fixture
async def switch_on(pool):
    """Make sure Slack notifications are ON before and after every test."""
    async with pool.acquire() as conn:
        await set_slack_enabled(conn, True)
    yield
    async with pool.acquire() as conn:
        await set_slack_enabled(conn, True)


async def create_alert(pool):
    account_id = uuid.uuid4()
    details = {"name": "Acme Corp", "domain": "acme.com", "score": 85,
               "employees": 450, "country": "India"}
    await pool.execute(
        """INSERT INTO notifications (account_id, source_event_id, details)
           VALUES ($1, $2, $3::jsonb)""",
        account_id, uuid.uuid4(), json.dumps(details),
    )
    return account_id


async def get_alert(pool, account_id):
    return await pool.fetchrow(
        """SELECT status, attempts, last_error, next_attempt_at > now() AS waiting
           FROM notifications WHERE account_id = $1""",
        account_id,
    )


async def history_events(pool, account_id):
    rows = await pool.fetch(
        "SELECT event_type FROM history WHERE account_id = $1 ORDER BY created_at",
        account_id,
    )
    return [row["event_type"] for row in rows]


async def make_ready_now(pool):
    """Skip the waiting time, so the alert can be tried again immediately."""
    await pool.execute("UPDATE notifications SET next_attempt_at = now()")


# ---------- tests ----------

async def test_nothing_waiting_returns_none(pool, switch_on):
    # Bug caught: sender crashing or sending something when there's nothing to send
    assert await send_one_alert(pool, FakeSlack()) is None


async def test_slack_works_alert_is_sent_once(pool, switch_on):
    # Bug caught: alert not sent, or sent twice
    account_id = await create_alert(pool)
    slack = FakeSlack()

    result = await send_one_alert(pool, slack)

    assert result["outcome"] == "sent"
    assert len(slack.sent) == 1
    assert (await get_alert(pool, account_id))["status"] == "sent"
    assert "alert_sent" in await history_events(pool, account_id)

    # Running again sends nothing more
    assert await send_one_alert(pool, slack) is None
    assert len(slack.sent) == 1


async def test_switch_off_skips_and_posts_nothing(pool, switch_on):
    # Bug caught: messages posted while notifications are switched off
    account_id = await create_alert(pool)
    async with pool.acquire() as conn:
        await set_slack_enabled(conn, False)
    slack = FakeSlack()

    result = await send_one_alert(pool, slack)

    assert result["outcome"] == "skipped"
    assert slack.attempts == 0
    assert (await get_alert(pool, account_id))["status"] == "skipped"
    assert "alert_skipped" in await history_events(pool, account_id)


async def test_slack_down_then_back_alert_is_retried_then_sent(pool, switch_on):
    # Bug caught: alert lost when Slack is down
    account_id = await create_alert(pool)
    slack = FakeSlack()
    slack.will_return(SendResult("retry", "timeout"))

    first = await send_one_alert(pool, slack)
    alert = await get_alert(pool, account_id)
    assert first["outcome"] == "retry"
    assert alert["status"] == "pending"
    assert alert["attempts"] == 1
    assert alert["waiting"] is True  # next try is in the future

    await make_ready_now(pool)
    second = await send_one_alert(pool, slack)

    assert second["outcome"] == "sent"
    assert len(slack.sent) == 1
    assert await history_events(pool, account_id) == ["alert_failed", "alert_sent"]


async def test_slack_keeps_failing_alert_is_parked(pool, switch_on):
    # Bug caught: alert retried forever instead of parked
    account_id = await create_alert(pool)
    slack = FakeSlack()
    slack.will_return(*[SendResult("retry", "timeout")] * MAX_ATTEMPTS)

    for _ in range(MAX_ATTEMPTS):
        await send_one_alert(pool, slack)
        await make_ready_now(pool)

    alert = await get_alert(pool, account_id)
    assert alert["status"] == "parked"
    assert alert["attempts"] == MAX_ATTEMPTS
    assert len(slack.sent) == 0
    assert (await history_events(pool, account_id))[-1] == "alert_parked"


async def test_slack_rejects_alert_is_parked_immediately(pool, switch_on):
    # Bug caught: a message that can never work being retried
    account_id = await create_alert(pool)
    slack = FakeSlack()
    slack.will_return(SendResult("park", "http 410: channel_is_archived"))

    result = await send_one_alert(pool, slack)

    alert = await get_alert(pool, account_id)
    assert result["outcome"] == "parked"
    assert alert["status"] == "parked"
    assert "channel_is_archived" in alert["last_error"]


async def test_too_fast_waits_and_does_not_count_as_attempt(pool, switch_on):
    # Bug caught: busy moments wrongly pushing good alerts toward parked
    account_id = await create_alert(pool)
    slack = FakeSlack()
    slack.will_return(SendResult("rate_limited", "rate_limited", retry_after=12))

    result = await send_one_alert(pool, slack)

    alert = await get_alert(pool, account_id)
    assert result["outcome"] == "rate_limited"
    assert alert["status"] == "pending"
    assert alert["attempts"] == 0
    assert alert["waiting"] is True