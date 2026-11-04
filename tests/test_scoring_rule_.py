# Tests for the worker's scoring handler (called directly, no queue)
import pytest

from scripts.handlers import MalformedJob, score_account


async def add_account(pool, name, domain, employees=None, country=None):
    async with pool.acquire() as connection:
        return await connection.fetchval(
            """insert into accounts (name, domain, employees, country)
               values ($1, $2, $3, $4) returning id""",
            name, domain, employees, country,
        )


async def get_account(pool, account_id):
    async with pool.acquire() as connection:
        return await connection.fetchrow("select score, stage from accounts where id = $1", account_id)


async def get_events(pool, account_id):
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            "select event_type, score from history where account_id = $1", account_id
        )
    return rows


async def test_score_and_stage_saved_in_accounts(pool):
    # Bug caught: score calculated but not saved
    account_id = await add_account(pool, "Aurora", "aurora.com", 2400, "India")

    await score_account(account_id, pool)

    account = await get_account(pool, account_id)
    assert account["score"] == 100
    assert account["stage"] == "qualified"


async def test_first_scoring_adds_scored_and_stage_changed(pool):
    # Bug caught: history missing the scored or stage_changed event
    account_id = await add_account(pool, "Aurora", "aurora.com", 2400, "India")

    await score_account(account_id, pool)

    events = sorted(row["event_type"] for row in await get_events(pool, account_id))
    assert events == ["scored", "stage_changed"]


async def test_scored_row_has_the_score(pool):
    # Bug caught: scored row saved without score
    account_id = await add_account(pool, "Aurora", "aurora.com", 2400, "India")

    await score_account(account_id, pool)

    scores = [row["score"] for row in await get_events(pool, account_id) if row["event_type"] == "scored"]
    assert scores == [100]


async def test_rescore_keeps_old_score_in_history(pool):
    # Bug caught: rescoring overwrites the old score (must ADD, not replace)
    account_id = await add_account(pool, "Bright", "bright.com", 13, "Japan")
    await score_account(account_id, pool)  # 25

    async with pool.acquire() as connection:
        await connection.execute("update accounts set employees = 1300 where id = $1", account_id)
    await score_account(account_id, pool)  # 70

    scores = sorted(row["score"] for row in await get_events(pool, account_id) if row["event_type"] == "scored")
    assert scores == [25, 70]
    assert (await get_account(pool, account_id))["stage"] == "qualified"


async def test_no_stage_changed_when_stage_is_the_same(pool):
    # Bug caught: stage_changed written even when nothing changed
    account_id = await add_account(pool, "Aurora", "aurora.com", 2400, "India")
    await score_account(account_id, pool)
    await score_account(account_id, pool)

    events = [row["event_type"] for row in await get_events(pool, account_id)]
    assert events.count("scored") == 2
    assert events.count("stage_changed") == 1


async def test_missing_data_still_scored(pool):
    # Bug caught: crash on missing employees/country
    account_id = await add_account(pool, "Alder", "alder.com")

    await score_account(account_id, pool)

    account = await get_account(pool, account_id)
    assert account["score"] == 0
    assert account["stage"] == "disqualified"


async def test_missing_account_raises_malformed_job(pool):
    # Bug caught: job for a deleted account retried forever instead of parked
    with pytest.raises(MalformedJob):
        await score_account("00000000-0000-0000-0000-000000000000", pool)