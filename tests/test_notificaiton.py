import json
import uuid

import pytest

from scripts.handlers import score_account



async def create_account(pool, employees, country):
    account_id = uuid.uuid4()
    await pool.execute(
        """
        INSERT INTO accounts (id, name, domain, employees, country)
        VALUES ($1, $2, $3, $4, $5)
        """,
        account_id, "Acme Corp", "acm.com", employees, country,
    )
    return account_id


async def change_company(pool, account_id, employees, country):
    await pool.execute(
        "UPDATE accounts SET employees = $2, country = $3 WHERE id = $1",
        account_id, employees, country,
    )


async def count_alerts(pool, account_id):
    return await pool.fetchval(
        "SELECT count(*) FROM notifications WHERE account_id = $1", account_id
    )

async def test_becoming_qualified_creates_one_alert(pool):
    account_id = await create_account(pool, employees=450, country="India")  # 45 + 40 = 85

    await score_account(account_id, pool)

    row = await pool.fetchrow(
        "SELECT status, attempts, details FROM notifications WHERE account_id = $1",
        account_id,
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    details = json.loads(row["details"])
    assert details["name"] == "Acme Corp"
    assert details["score"] == 85



async def test_scoring_again_while_qualified_creates_no_new_alert(pool):
    account_id = await create_account(pool, employees=450, country="India")

    await score_account(account_id, pool)
    await score_account(account_id, pool)  # same job again / rescore, still qualified

    assert await count_alerts(pool, account_id) == 1



async def test_disqualified_account_creates_no_alert(pool):
    account_id = await create_account(pool, employees=120, country="Brazil")  # 30 + 10 = 40

    await score_account(account_id, pool)

    assert await count_alerts(pool, account_id) == 0



async def test_qualified_disqualified_qualified_creates_two_alerts(pool):
    account_id = await create_account(pool, employees=450, country="India")   # 85, qualified
    await score_account(account_id, pool)

    await change_company(pool, account_id, employees=120, country="Brazil")   # 40, disqualified
    await score_account(account_id, pool)

    await change_company(pool, account_id, employees=450, country="Germany")  # 70, qualified
    await score_account(account_id, pool)

    assert await count_alerts(pool, account_id) == 2



async def test_alert_points_to_its_stage_changed_history_row(pool):
    account_id = await create_account(pool, employees=450, country="India")

    await score_account(account_id, pool)

    source_event_id = await pool.fetchval(
        "SELECT source_event_id FROM notifications WHERE account_id = $1", account_id
    )
    history_id = await pool.fetchval(
        """
        SELECT id FROM history
        WHERE account_id = $1 AND event_type = 'stage_changed' AND stage = 'qualified'
        """,
        account_id,
    )
    assert source_event_id == history_id