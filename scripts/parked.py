import argparse
import asyncio
import json
import uuid

import asyncpg

from app.config import Settings


async def connect():
    return await asyncpg.connect(
        user=Settings.db_user,
        password=Settings.db_pass,
        database=Settings.db_name,
        host=Settings.db_host,
        port=Settings.db_port,
    )


async def list_alerts(conn) -> None:
    rows = await conn.fetch(
        """
        SELECT id, status, attempts, last_error, details->>'name' AS company
        FROM notifications
        WHERE status IN ('parked', 'skipped')
        ORDER BY created_at DESC
        LIMIT 50
        """
    )
    if not rows:
        print("No parked or skipped alerts.")
        return

    for r in rows:
        print(f"{r['id']}  {r['status']:<8} {r['company']:<25} "
              f"attempts={r['attempts']}  error={r['last_error'] or '-'}")
    print(f"\n{len(rows)} alert(s). Resend one with: python -m scripts.parked resend <id>")


async def resend(conn, alert_id: uuid.UUID) -> None:
    async with conn.transaction():
        row = await conn.fetchrow(
            """
            UPDATE notifications
            SET status = 'pending', attempts = 0, next_attempt_at = now(), last_error = NULL
            WHERE id = $1 AND status IN ('parked', 'skipped')
            RETURNING account_id, details->>'name' AS company
            """,
            alert_id,
        )
        if row is None:
            current = await conn.fetchval("SELECT status FROM notifications WHERE id = $1", alert_id)
            if current is None:
                print("No alert with that id.")
            else:
                print(f"Not resent: this alert is '{current}'. Only parked or skipped alerts can be resent.")
            return

        await conn.execute(
            "INSERT INTO history (account_id, event_type, details) VALUES ($1, 'alert_resent', $2::jsonb)",
            row["account_id"], json.dumps({"notification_id": str(alert_id)}),
        )
    print(f"Queued again: {row['company']}. The sender will send it shortly.")


async def main(args) -> None:
    conn = await connect()
    try:
        if args.command == "list":
            await list_alerts(conn)
        else:
            await resend(conn, args.alert_id)
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="See and resend parked or skipped Slack alerts")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show parked and skipped alerts")
    resend_cmd = sub.add_parser("resend", help="send one alert again")
    resend_cmd.add_argument("alert_id", type=uuid.UUID)
    asyncio.run(main(parser.parse_args()))