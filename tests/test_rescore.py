# Tests for POST /accounts/{account_id}/rescore
import uuid


async def add_account(pool, name, domain, employees=None, country=None):
    async with pool.acquire() as connection:
        return await connection.fetchval(
            """insert into accounts (name, domain, employees, country)
               values ($1, $2, $3, $4) returning id""",
            name, domain, employees, country,
        )


async def test_rescore_returns_202_and_sends_job(client, pool, fake_sqs):
    # Bug caught: rescore accepted but no job sent to the worker
    account_id = await add_account(pool, "Bright", "bright.com", 13, "Japan")

    response = await client.post(f"/accounts/{account_id}/rescore", json={"employees": 1300})

    assert response.status_code == 202
    assert len(fake_sqs.messages) == 1
    assert fake_sqs.messages[0]["account_id"] == str(account_id)


async def test_rescore_updates_only_the_sent_field(client, pool):
    # Bug caught: corrected data not saved, or other fields wiped to null
    account_id = await add_account(pool, "Bright", "bright.com", 13, "Japan")

    await client.post(f"/accounts/{account_id}/rescore", json={"employees": 1300})

    async with pool.acquire() as connection:
        row = await connection.fetchrow("select employees, country from accounts where id = $1", account_id)
    assert row["employees"] == 1300
    assert row["country"] == "Japan"


async def test_rescore_adds_updated_to_history(client, pool):
    # Bug caught: data correction not recorded
    account_id = await add_account(pool, "Bright", "bright.com", 13, "Japan")

    await client.post(f"/accounts/{account_id}/rescore", json={"employees": 1300})

    async with pool.acquire() as connection:
        event = await connection.fetchval("select event_type from history where account_id = $1", account_id)
    assert event == "stage_changed"


async def test_two_rescores_get_different_keys(client, pool, fake_sqs):
    # Bug caught: second rescore skipped by the worker as a duplicate
    account_id = await add_account(pool, "Bright", "bright.com", 13, "Japan")

    await client.post(f"/accounts/{account_id}/rescore", json={"employees": 1300})
    await client.post(f"/accounts/{account_id}/rescore", json={"employees": 1400})

    first, second = fake_sqs.messages
    assert first["idempotency_key"] != second["idempotency_key"]


async def test_unknown_account_returns_404(client, fake_sqs):
    # Bug caught: rescoring an account that doesn't exist
    response = await client.post(f"/accounts/{uuid.uuid4()}/rescore", json={"employees": 1300})
    assert response.status_code == 404
    assert fake_sqs.messages == []


async def test_bad_account_id_returns_422(client):
    # Bug caught: a bad id crashing the API with a 500
    response = await client.post("/accounts/not-a-uuid/rescore", json={"employees": 1300})
    assert response.status_code == 422