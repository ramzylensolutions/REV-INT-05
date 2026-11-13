import argparse
import asyncio

import asyncpg

from app.config import Settings
from scripts.slack_settings import is_slack_enabled, set_slack_enabled


async def main(action: str) -> None:
    settings = Settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        if action == "on":
            await set_slack_enabled(conn, True)
        elif action == "off":
            await set_slack_enabled(conn, False)

        enabled = await is_slack_enabled(conn)
        updated_at = await conn.fetchval(
            "SELECT updated_at FROM settings WHERE key = 'slack_enabled'"
        )
        print(f"Slack notifications: {'ON' if enabled else 'OFF'} (last changed {updated_at})")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Turn Slack notifications on or off")
    parser.add_argument("action", choices=["on", "off", "status"])
    args = parser.parse_args()
    asyncio.run(main(args.action))