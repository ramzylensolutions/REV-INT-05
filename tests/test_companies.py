# Tests for POST /companies (the import endpoint)


async def count_rows(pool, table):
    async with pool.acquire() as connection:
        return await connection.fetchval(f"select count(*) from {table}")


async def test_new_company_is_created(client, pool):
    # Bug caught: valid companies not saved
    response = await client.post(
        "/companies",
        json={"name": "Aurora", "domain": "aurora.com", "employees": 2400, "country": "India"},
    )
    assert response.status_code == 201
    assert await count_rows(pool, "accounts") == 1


async def test_messy_domain_is_stored_clean(client, pool):
    # Bug caught: https://WWW.Example.com/ stored as-is
    await client.post("/companies", json={"name": "Example", "domain": "https://WWW.Example.com/"})

    async with pool.acquire() as connection:
        domain = await connection.fetchval("select domain from accounts")
    assert domain == "example.com"


async def test_created_row_is_added_to_history(client, pool):
    # Bug caught: account saved without its "created" history row
    await client.post("/companies", json={"name": "Aurora", "domain": "aurora.com"})

    async with pool.acquire() as connection:
        event = await connection.fetchval("select event_type from history")
    assert event == "created"


async def test_scoring_job_is_sent(client, fake_sqs):
    # Bug caught: account saved but never scored (no job sent)
    await client.post("/companies", json={"name": "Aurora", "domain": "aurora.com"})

    assert len(fake_sqs.messages) == 1
    assert fake_sqs.messages[0]["task"] == "score_account"


async def test_duplicate_returns_409(client):
    # Bug caught: the same company created twice
    company = {"name": "Aurora", "domain": "aurora.com"}
    await client.post("/companies", json=company)
    response = await client.post("/companies", json=company)
    assert response.status_code == 409


async def test_duplicate_does_not_send_a_second_job(client, pool, fake_sqs):
    # Bug caught: re-importing scores the same account twice
    company = {"name": "Aurora", "domain": "aurora.com"}
    await client.post("/companies", json=company)
    await client.post("/companies", json=company)

    assert len(fake_sqs.messages) == 1
    assert await count_rows(pool, "history") == 1


async def test_messy_and_clean_domain_are_duplicates(client):
    # Bug caught: duplicate check bypassed by writing the domain differently
    await client.post("/companies", json={"name": "Example", "domain": "example.com"})
    response = await client.post("/companies", json={"name": "Example", "domain": "https://WWW.Example.com/"})
    assert response.status_code == 409


async def test_missing_employees_and_country_is_accepted(client):
    # Bug caught: companies with missing data rejected instead of imported
    response = await client.post("/companies", json={"name": "Alder", "domain": "alder.com"})
    assert response.status_code == 201


async def test_missing_name_returns_422(client, fake_sqs):
    # Bug caught: incomplete records saved
    response = await client.post("/companies", json={"domain": "noname.com"})
    assert response.status_code == 422
    assert fake_sqs.messages == []


async def test_text_employees_returns_422(client):
    # Bug caught: "abc" accepted as an employee count
    response = await client.post(
        "/companies", json={"name": "Cedar", "domain": "cedar.com", "employees": "abc"}
    )
    assert response.status_code == 422


async def test_no_token_returns_401(client):
    # Bug caught: auth accidentally removed
    response = await client.post(
        "/companies",
        json={"name": "Aurora", "domain": "aurora.com"},
        headers={"Authorization": ""},
    )
    assert response.status_code == 401


async def test_wrong_token_returns_401(client):
    # Bug caught: any token accepted
    response = await client.post(
        "/companies",
        json={"name": "Aurora", "domain": "aurora.com"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401