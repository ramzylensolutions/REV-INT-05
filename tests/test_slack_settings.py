from scripts.slack_settings import is_slack_enabled, set_slack_enabled

async def test_switch_off_and_on(pool):
    async with pool.acquire() as conn:
        await set_slack_enabled(conn, False)
        assert await is_slack_enabled(conn) is False

        await set_slack_enabled(conn, True)
        assert await is_slack_enabled(conn) is True

async def test_missing_switch_counts_as_off(pool):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM settings WHERE key = 'slack_enabled'")
        assert await is_slack_enabled(conn) is False
        await set_slack_enabled(conn, True)  # put it back for other tests