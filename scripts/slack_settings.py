async def is_slack_enabled(conn) -> bool:
    value = await conn.fetchval(
        "SELECT value FROM settings WHERE key = 'slack_enabled'"
    )
    return value == "true"


async def set_slack_enabled(conn, enabled: bool) -> None:
    await conn.execute(
        """
        INSERT INTO settings (key, value, updated_at)
        VALUES ('slack_enabled', $1, now())
        ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
        """,
        "true" if enabled else "false",
    )