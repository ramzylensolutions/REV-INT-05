import json
from datetime import datetime, timezone
from scripts.scoring_rule import calculate_score, RULE_VERSION, THRESHOLD

class MalformedJob(Exception):
    """A job that can never succeed: bad JSON, unknown type, or missing fields."""


def require(job: dict, *fields: str) -> None:
    missing = [field for field in fields if field not in job]
    if missing:
        raise MalformedJob(f"missing field(s): {', '.join(missing)}")

async def score_account(account_id,pool):
    async with pool.acquire() as connection:
        account = await connection.fetchrow(
       """select name , domain, employees, country, stage from accounts where id = $1""",
        account_id,
        )
        if account is None:
            raise MalformedJob(f"account {account_id} not found")
        calc = calculate_score(account["employees"], account["country"])
        score = calc["score"]
        stage = calc["stage"]

        async with connection.transaction():
            await connection.execute(
                "update accounts set score = $1, stage = $2 where id = $3",
                score, stage, account_id,
            )
            await connection.execute(
                """insert into history (account_id, event_type, score, stage, scored_at, details)
                   values ($1, 'scored', $2, $3, now(), $4)""",
                account_id, score, stage,
                json.dumps({"size": calc["size"], "market": calc["market"]}),
            )
            if account["stage"] != stage:
                stage_event_id = await connection.fetchval(
                    """insert into history (account_id, event_type, stage, details)
                       values ($1, 'stage_changed', $2, $3) returning id""",
                    account_id, stage,
                    json.dumps({"from": account["stage"], "to": stage}),)

                if stage == "qualified":
                    details = {
                    "name": account["name"],
                    "domain": account["domain"],
                    "score": score,
                    "employees": account["employees"],
                    "country": account["country"],
                }
                    await connection.execute(
                        """
                        INSERT INTO notifications (account_id, source_event_id, details)
                        VALUES ($1, $2, $3::jsonb)
                        """,
                        account_id, stage_event_id, json.dumps(details),
                        )
            elif stage == "qualified":
                await connection.execute(
                        """
                        INSERT INTO history (account_id, event_type, details)
                        VALUES ($1, 'alert_skipped', $2::jsonb)
                        """,
                        account_id, json.dumps({"reason": "already_qualified"}),
    )
                
    return {
        "Scored_at": datetime.now(timezone.utc).isoformat(),
        "Account_id": str(account_id),
        "Company_Name": account["name"],
        "Domain": account["domain"],
        "Employees": account["employees"],
        "Country": account["country"],
        "Rule-Version": RULE_VERSION,
        "Points.Size": calc["size"],
        "Points.Market": calc["market"],
        "Threshold": THRESHOLD,
        "Score": score,
        "Stage": stage,
        "Previous-Stage": account["stage"],
    }