# Tests for GET /ranking


async def add_account(pool, name, domain, employees=None, country=None, score=None, stage=None):
    async with pool.acquire() as connection:
        return await connection.fetchval(
            """insert into accounts (name, domain, employees, country, score, stage)
               values ($1, $2, $3, $4, $5, $6) returning id""",
            name, domain, employees, country, score, stage,
        )


def names(response):
    return [account["name"] for account in response.json()]


async def test_highest_score_first(client, pool):
    # Bug caught: list not sorted, or sorted lowest first
    await add_account(pool, "Low", "low.com", 10, "Japan", 25, "disqualified")
    await add_account(pool, "High", "high.com", 2400, "India", 100, "qualified")
    await add_account(pool, "Mid", "mid.com", 749, "India", 85, "qualified")

    response = await client.get("/ranking")
    assert response.status_code == 200
    assert names(response) == ["High", "Mid", "Low"]


async def test_same_score_more_employees_first(client, pool):
    # Bug caught: missing tie-break
    await add_account(pool, "Smaller", "smaller.com", 150, "India", 70, "qualified")
    await add_account(pool, "Bigger", "bigger.com", 3100, "Japan", 70, "qualified")

    response = await client.get("/ranking")
    assert names(response) == ["Bigger", "Smaller"]


async def test_same_score_and_employees_ordered_by_name(client, pool):
    # Bug caught: last tie-break (name A-Z) missing
    await add_account(pool, "Zeta", "zeta.com", 500, "India", 85, "qualified")
    await add_account(pool, "Alpha", "alpha.com", 500, "India", 85, "qualified")

    response = await client.get("/ranking")
    assert names(response) == ["Alpha", "Zeta"]


async def test_unscored_accounts_are_last(client, pool):
    # Bug caught: unscored accounts shown at the top
    await add_account(pool, "Not Scored", "notscored.com", 5000, "USA")
    await add_account(pool, "Scored", "scored.com", 10, "Japan", 25, "disqualified")

    response = await client.get("/ranking")
    assert names(response) == ["Scored", "Not Scored"]


async def test_filter_qualified(client, pool):
    # Bug caught: stage filter ignored
    await add_account(pool, "Q", "q.com", 2400, "India", 100, "qualified")
    await add_account(pool, "D", "d.com", 10, "Japan", 25, "disqualified")

    response = await client.get("/ranking", params={"stage": "qualified"})
    assert names(response) == ["Q"]


async def test_filter_disqualified(client, pool):
    await add_account(pool, "Q", "q.com", 2400, "India", 100, "qualified")
    await add_account(pool, "D", "d.com", 10, "Japan", 25, "disqualified")

    response = await client.get("/ranking", params={"stage": "disqualified"})
    assert names(response) == ["D"]


async def test_unknown_stage_returns_422(client):
    # Bug caught: any stage accepted; the ticket wants the allowed values listed
    response = await client.get("/ranking", params={"stage": "banana"})
    assert response.status_code == 422
    assert "qualified" in response.text


async def test_no_accounts_returns_empty_list(client):
    # Bug caught: crash when the table is empty
    response = await client.get("/ranking")
    assert response.status_code == 200
    assert response.json() == []