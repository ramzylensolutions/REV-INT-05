import json

from scripts.slack_messages import build_alert_message, build_summary_message
from scripts.slack_settings import is_slack_enabled

MAX_ATTEMPTS = 8
GATHER_SECONDS = 15     # wait this long so alerts from one import can pile up
SUMMARY_THRESHOLD = 3   # more than this many waiting → one summary message


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
async def send_next(pool, slack) -> dict | None:
    """Decide what to do: wait, send one alert, or send one summary."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT count(*) AS waiting,
                   coalesce(now() - min(created_at) >= $1 * interval '1 second', false) AS ready
            FROM notifications
            WHERE status = 'pending' AND next_attempt_at <= now()
            """,
            GATHER_SECONDS,
        )

    if row["waiting"] == 0 or not row["ready"]:
        return None                                   # nothing yet, or still gathering

    if row["waiting"] > SUMMARY_THRESHOLD:
        return await send_summary(pool, slack)        # many → one summary

    return await send_one_alert(pool, slack)          # a few → one by one


async def send_summary(pool, slack) -> dict | None:
    """Send ONE Slack message covering all waiting alerts."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Take ALL waiting alerts, and lock them
            alerts = await conn.fetch(
                """
                SELECT id, account_id, attempts, details
                FROM notifications
                WHERE status = 'pending' AND next_attempt_at <= now()
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                """
            )
            if len(alerts) <= SUMMARY_THRESHOLD:
                return None   # another sender took some; the next round decides again

            ids = [a["id"] for a in alerts]
            size = len(alerts)

            # 2. Switch off → all skipped
            if not await is_slack_enabled(conn):
                await conn.execute(
                    "UPDATE notifications SET status = 'skipped' WHERE id = ANY($1::uuid[])", ids
                )
                for a in alerts:
                    await add_history(conn, a["account_id"], "alert_skipped",
                                      {"notification_id": str(a["id"]),
                                       "reason": "notifications_off"})
                return {"outcome": "skipped", "count": size}

            # 3. Send ONE message
            details = [json.loads(a["details"]) for a in alerts]
            result = await slack.send(build_summary_message(details))

            # 4a. Delivered → every alert in it is sent
            if result.outcome == "sent":
                await conn.execute(
                    """UPDATE notifications
                       SET status = 'sent', sent_at = now(), attempts = attempts + 1,
                           last_error = NULL
                       WHERE id = ANY($1::uuid[])""",
                    ids,
                )
                for a in alerts:
                    await add_history(conn, a["account_id"], "alert_sent",
                                      {"notification_id": str(a["id"]),
                                       "sent_as": "summary", "summary_size": size})
                return {"outcome": "sent", "count": size}

            # 4b. Too fast → all wait, not counted as an attempt
            if result.outcome == "rate_limited":
                await conn.execute(
                    """UPDATE notifications
                       SET next_attempt_at = now() + $2 * interval '1 second', last_error = $3
                       WHERE id = ANY($1::uuid[])""",
                    ids, result.retry_after, result.error,
                )
                for a in alerts:
                    await add_history(conn, a["account_id"], "alert_failed",
                                      {"notification_id": str(a["id"]),
                                       "reason": "rate_limited", "sent_as": "summary"})
                return {"outcome": "rate_limited", "retry_after": result.retry_after,
                        "count": size}

            # 4c. Failed → retry later, or park (rejected, or too many attempts)
            give_up = result.outcome == "park"
            wait = backoff_seconds(max(a["attempts"] for a in alerts) + 1)
            updated = await conn.fetch(
                """UPDATE notifications
                   SET attempts = attempts + 1,
                       last_error = $2,
                       next_attempt_at = now() + $3 * interval '1 second',
                       status = CASE WHEN $4::boolean OR attempts + 1 >= $5
                                     THEN 'parked' ELSE 'pending' END
                   WHERE id = ANY($1::uuid[])
                   RETURNING id, account_id, status, attempts""",
                ids, result.error, wait, give_up, MAX_ATTEMPTS,
            )
            for r in updated:
                event = "alert_parked" if r["status"] == "parked" else "alert_failed"
                await add_history(conn, r["account_id"], event,
                                  {"notification_id": str(r["id"]), "attempt": r["attempts"],
                                   "error": result.error, "sent_as": "summary"})
            return {"outcome": "parked" if give_up else "retry", "count": size}