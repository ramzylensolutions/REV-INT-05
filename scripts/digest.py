import argparse
import asyncio
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.db_conn import create_pool
from scripts.slack_client import SlackClient
from scripts.slack_messages import build_digest_message
from scripts.slack_settings import is_slack_enabled


# ---------- time helpers ----------

def local_now() -> datetime:
    """The current time in the digest's time zone (India by default)."""
    return datetime.now(ZoneInfo(Settings.digest_timezone))


def is_due(now: datetime) -> bool:
    """True on Monday–Friday, at or after the digest time."""
    hour, minute = map(int, Settings.digest_time.split(":"))
    return now.weekday() < 5 and now.time() >= time(hour, minute)


def since_label(since: datetime, today) -> str:
    """Turn 'when was the last digest' into words: yesterday, Friday..."""
    days = (today - since.date()).days
    if days == 0:
        return "earlier today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return since.strftime("%A")      # e.g. "Friday"
    return "the last summary"


# ---------- database steps ----------

async def claim(conn, kind: str, today):
    """Reserve today's digest. Returns its id, or None if someone else has it."""
    if kind == "manual":
        return await conn.fetchval(
            "INSERT INTO digests (digest_date, kind) VALUES ($1, 'manual') RETURNING id", today
        )

    # Only ONE scheduled digest per day: the unique index decides who wins
    digest_id = await conn.fetchval(
        """
        INSERT INTO digests (digest_date, kind) VALUES ($1, 'scheduled')
        ON CONFLICT (digest_date) WHERE kind = 'scheduled' DO NOTHING
        RETURNING id
        """,
        today,
    )
    if digest_id is not None:
        return digest_id

    # Today's row exists. Take it over only if an earlier try failed or got stuck.
    return await conn.fetchval(
        """
        UPDATE digests
        SET status = 'sending', last_attempt_at = now(), last_error = NULL
        WHERE digest_date = $1 AND kind = 'scheduled'
          AND (   (status = 'failed'  AND last_attempt_at < now() - interval '2 minutes')
               OR (status = 'sending' AND last_attempt_at < now() - interval '10 minutes'))
        RETURNING id
        """,
        today,
    )


async def collect(conn, digest_id, now: datetime) -> dict:
    """Gather the numbers for the digest."""
    # Since when? The last digest that was really sent (or 24 hours ago, the first time)
    since = await conn.fetchval(
        "SELECT max(sent_at) FROM digests WHERE status = 'sent' AND id <> $1", digest_id
    )
    if since is None:
        since = now - timedelta(hours=24)

    # Companies that became qualified since then, and are STILL qualified
    rows = await conn.fetch(
        """
        SELECT DISTINCT h.account_id
        FROM history h
        JOIN accounts a ON a.id = h.account_id
        WHERE h.event_type = 'stage_changed' AND h.stage = 'qualified'
          AND h.created_at > $1
          AND a.stage = 'qualified'
        """,
        since,
    )
    new_ids = {r["account_id"] for r in rows}

    # Top 10, in exactly the same order as GET /ranking
    top_rows = await conn.fetch(
        """
        SELECT id, name, domain, score
        FROM accounts
        WHERE stage = 'qualified'
        ORDER BY score DESC NULLS LAST, employees DESC NULLS LAST, name ASC
        LIMIT 10
        """
    )
    top = [
        {"name": r["name"], "domain": r["domain"], "score": r["score"],
         "is_new": r["id"] in new_ids}
        for r in top_rows
    ]

    waiting = await conn.fetchval("SELECT count(*) FROM accounts WHERE score IS NULL")

    return {"since": since, "new_count": len(new_ids), "waiting_count": waiting, "top": top}


# ---------- send ----------

async def send_digest(pool, slack, kind: str = "scheduled") -> dict | None:
    """Claim today's digest, build it, send it, and record what happened."""
    now = local_now()
    today = now.date()

    async with pool.acquire() as conn:
        digest_id = await claim(conn, kind, today)
        if digest_id is None:
            return None                                   # already done today (or in progress)

        if not await is_slack_enabled(conn):
            await conn.execute(
                "UPDATE digests SET status = 'skipped', last_error = 'notifications_off' WHERE id = $1",
                digest_id,
            )
            return {"outcome": "skipped", "digest": True}

        data = await collect(conn, digest_id, now)
        message = build_digest_message(
            day_label=now.strftime("%a %d %b"),           # e.g. "Tue 17 Nov"
            since_label=since_label(data["since"].astimezone(now.tzinfo), today),
            new_count=data["new_count"],
            waiting_count=data["waiting_count"],
            top=data["top"],
        )
        result = await slack.send(message)

        if result.outcome == "sent":
            details = {
                "new_count": data["new_count"],
                "waiting_count": data["waiting_count"],
                "top": [{"name": t["name"], "score": t["score"]} for t in data["top"]],
            }
            await conn.execute(
                "UPDATE digests SET status = 'sent', sent_at = now(), details = $2::jsonb WHERE id = $1",
                digest_id, json.dumps(details),
            )
            return {"outcome": "sent", "digest": True}

        await conn.execute(
            "UPDATE digests SET status = 'failed', last_error = $2, last_attempt_at = now() WHERE id = $1",
            digest_id, result.error,
        )
        return {"outcome": "failed", "digest": True, "error": result.error}


# ---------- manual command (for the demo) ----------

async def main() -> None:
    if Settings.slack_webhook_url is None:
        raise SystemExit("SLACK_WEBHOOK_URL is not set.")
    slack = SlackClient(Settings.slack_webhook_url.get_secret_value())
    pool = await create_pool()
    try:
        result = await send_digest(pool, slack, kind="manual")
        print(f"Digest: {result['outcome']}" + (f" ({result['error']})" if result.get("error") else ""))
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send the daily digest now")
    parser.add_argument("action", choices=["now"])
    parser.parse_args()
    asyncio.run(main())
    