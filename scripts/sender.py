import json

from scripts.slack_messages import build_alert_message
from scripts.slack_settings import is_slack_enabled

MAX_ATTEMPTS = 8


def backoff_seconds(attempts: int) -> int:
    """Wait longer after each failure: 30s, 60s, 120s, 240s, then 300s (5 min)."""
    return min(30 * 2 ** (attempts - 1), 300)


async def add_history(conn, account_id, event_type: str, details: dict) -> None:
    await conn.execute(
        "INSERT INTO history (account_id, event_type, details) VALUES ($1, $2, $3::jsonb)",
        account_id, event_type, json.dumps(details),
    )


async def send_one_alert(pool, slack) -> dict | None:
    """Send the oldest waiting alert. Returns what happened, or None if nothing is waiting."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Take the oldest waiting alert, and lock it
            alert = await conn.fetchrow(
                """
                SELECT id, account_id, attempts, details
                FROM notifications
                WHERE status = 'pending' AND next_attempt_at <= now()
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
            if alert is None:
                return None

            alert_id = alert["id"]
            account_id = alert["account_id"]
            info = {"notification_id": str(alert_id)}

            # 2. Switch off → skipped
            if not await is_slack_enabled(conn):
                await conn.execute(
                    "UPDATE notifications SET status = 'skipped' WHERE id = $1", alert_id
                )
                await add_history(conn, account_id, "alert_skipped",
                                  {**info, "reason": "notifications_off"})
                return {"outcome": "skipped"}

            # 3. Send to Slack
            details = json.loads(alert["details"])
            result = await slack.send(build_alert_message(details))
            attempts = alert["attempts"] + 1

            # 4a. Delivered
            if result.outcome == "sent":
                await conn.execute(
                    """UPDATE notifications
                       SET status = 'sent', sent_at = now(), attempts = $2, last_error = NULL
                       WHERE id = $1""",
                    alert_id, attempts,
                )
                await add_history(conn, account_id, "alert_sent", {**info, "sent_as": "single"})
                return {"outcome": "sent"}

            # 4b. Too fast: wait, and don't count it as a failure
            if result.outcome == "rate_limited":
                await conn.execute(
                    """UPDATE notifications
                       SET next_attempt_at = now() + $2 * interval '1 second', last_error = $3
                       WHERE id = $1""",
                    alert_id, result.retry_after, result.error,
                )
                await add_history(conn, account_id, "alert_failed",
                                  {**info, "reason": "rate_limited",
                                   "retry_after": result.retry_after})
                return {"outcome": "rate_limited", "retry_after": result.retry_after}

            # 4c. Temporary failure: try again later
            if result.outcome == "retry" and attempts < MAX_ATTEMPTS:
                wait = backoff_seconds(attempts)
                await conn.execute(
                    """UPDATE notifications
                       SET attempts = $2, last_error = $3,
                           next_attempt_at = now() + $4 * interval '1 second'
                       WHERE id = $1""",
                    alert_id, attempts, result.error, wait,
                )
                await add_history(conn, account_id, "alert_failed",
                                  {**info, "attempt": attempts, "error": result.error,
                                   "retry_in_seconds": wait})
                return {"outcome": "retry"}

            # 4d. Give up: parked, an operator must look
            await conn.execute(
                """UPDATE notifications
                   SET status = 'parked', attempts = $2, last_error = $3
                   WHERE id = $1""",
                alert_id, attempts, result.error,
            )
            await add_history(conn, account_id, "alert_parked",
                              {**info, "attempts": attempts, "error": result.error})
            return {"outcome": "parked"}