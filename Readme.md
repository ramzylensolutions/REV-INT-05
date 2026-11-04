# REV-INT-05 · Score and rank accounts

Sales has a list of target companies and no way to tell which ones to call first.
This project imports that list, scores every company automatically in the
background, and gives sales a ranked list so they call the most promising
companies first.

There is no user interface. **The API and the command line are the interface.**

---

## How it works

```
companies.json
     │
     ▼
import_trigger.py ──POST /companies──▶ FastAPI ──▶ PostgreSQL (accounts + "created" history row)
                                          │
                                          └──▶ SQS queue: {"task": "score_account", "account_id", "idempotency_key"}
                                                   │
                                                   ▼
                                                Worker ──▶ PostgreSQL (score, stage, "scored" / "stage_changed" history)
                                                   │
                                                   └──▶ S3 bucket (audit record for this scoring run)

GET /ranking?stage=qualified  ──▶  accounts sorted by score, highest first
```

| Component | File(s) | Job |
|-----------|---------|-----|
| Import command | `import_trigger.py` | Reads a companies JSON file and sends each company to the API, one at a time |
| API | `app/` | Validates and cleans each company, saves it, writes history, queues a scoring job. Also serves the ranking and rescore endpoints |
| Database | `sql_migrations/` | `accounts` (current score and stage) and `history` (every event). Migrations run automatically when the API starts |
| Queue | SQS in LocalStack | Holds scoring jobs. Failed jobs move to a dead-letter queue (DLQ) after 3 tries |
| Worker | `scripts/main.py`, `scripts/handlers.py` | Takes jobs from the queue, scores the account, saves the result, writes the audit record |
| Scoring rule | `scripts/scoring_rule.py` | The rule itself, in one place |
| Audit bucket | S3 in LocalStack | One JSON record per scoring run |

**Why scoring runs in the background:** the API answers immediately instead of
waiting for scoring, a slow or failing scoring step can't break the import, and
jobs survive a worker crash because they wait in the queue until they succeed.

---

## Setup

### Requirements

- Python 3.11+
- PostgreSQL
- Docker (for LocalStack)

### 1. Install Python packages

```
python -m venv venv
venv\Scripts\activate            # Windows
source venv/bin/activate         # Mac / Linux

pip install -r requirements.txt
```

### 2. Create your `.env`

Copy `.env.example` to `.env` and fill in your own values. `.env` is in
`.gitignore` and must never be committed.

| Setting | Meaning |
|---------|---------|
| `api_token` | Token the API expects in `Authorization: Bearer <token>` |
| `api_base_url` | Where the import and rescore commands send requests |
| `db_name`, `db_user`, `db_pass`, `db_host`, `db_port` | Your PostgreSQL database |
| `AWS_ENDPOINT_URL`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | LocalStack connection (dummy keys are fine) |
| `SCORING_QUEUE_NAME`, `SCORING_DLQ_NAME` | Queue names |
| `AUDIT_BUCKET_NAME` | S3 bucket for audit records |
| `test_db_name`, `test_db_user`, `test_db_pass`, `test_db_host`, `test_db_port` | A **separate** database for the tests |

On Windows, use `127.0.0.1` instead of `localhost` in URLs. `localhost` tries
IPv6 first and adds about 2 seconds to every request.

### 3. Create the database

```
psql -U postgres -c "create database revenue_project;"
```

You don't create tables by hand. The API applies every file in
`sql_migrations/` at startup, in order, and records each one in
`track_migration` so it only runs once.

### 4. Start LocalStack and create the queues and bucket

```
docker run -d --name localstack -p 4566:4566 -e SERVICES=sqs,s3 localstack/localstack:4.4
python scripts/setup_queues.py
```

After the first time, use `docker start localstack`.

> LocalStack keeps queues and buckets in memory. **Every time it restarts, run
> `python scripts/setup_queues.py` again**, or the API fails at startup with
> "The specified queue does not exist".

Version `4.4` is used on purpose: newer LocalStack images require an auth token.

### 5. Start the API and the worker

In two separate terminals, from the project folder:

```
python -m uvicorn app.main:app --reload
python -m scripts.main
```

Use `python -m ...` so the `app` and `scripts` packages can be imported.

---

## How to import

```
python import_trigger.py companies_20.json
```

The file is read from the `Data/` folder. Each line is reported:

| Output | Meaning |
|--------|---------|
| `imported` | New account created and a scoring job queued |
| `already exists, skipped` | A company with the same domain is already in the system (409). No new account, no new job |
| `failed (422) ...` | The record is invalid (missing name or domain, bad employee count, not an object). It is skipped and the rest of the file continues |

Within about a minute, the worker scores every new account.

**Running the same file again is safe.** Every company is reported as already
existing, nothing is duplicated, and nothing is scored twice.

### What gets cleaned

Domains are normalised before saving, so messy and clean spellings of the same
company are treated as one company:

| In the file | Stored as |
|-------------|-----------|
| `https://WWW.Example.com/` | `example.com` |
| `http://example.com/about/team` | `example.com` |
| `  Example.COM  ` | `example.com` |

### Sample files

| File | Purpose |
|------|---------|
| `Data/companies.json` | 100 sample companies |
| `Data/companies_20.json` | 20 companies with a known, hand-checked ranking (10 qualified) |
| `Data/companies_messy.json` | Messy domains, missing fields, a duplicate, and broken records |

All company data is fictional.

---

## How scoring works

**Score = size points + market points** (0 to 100)

| Employees | Size points |
|-----------|------------:|
| 1000 or more | 60 |
| 200 – 999 | 45 |
| 50 – 199 | 30 |
| 1 – 49 | 15 |
| Missing, 0, or negative | 0 |

| Country | Market points |
|---------|--------------:|
| India, USA (Tier 1) | 40 |
| United Kingdom, Germany, Singapore, Australia, Canada (Tier 2) | 25 |
| Any other country | 10 |
| Missing or empty | 0 |

**Stage:** a score of **60 or more** is `qualified`; below 60 is `disqualified`.

**Example:** FalconNest Technologies has 749 employees (45) and is in India (40),
so it scores **85** and is qualified.

### Missing data

A company with missing fields still gets an account and a score. A missing
field simply earns **0 points** for that part:

| Company | Size | Market | Score | Stage |
|---------|-----:|-------:|------:|-------|
| No employee count, India | 0 | 40 | 40 | disqualified |
| 1500 employees, no country | 60 | 0 | 60 | qualified |
| Nothing but name and domain | 0 | 0 | 0 | disqualified |

Country names must match exactly (for example `United Kingdom`, not `UK`, and
`India`, not `india`). Anything else counts as "any other country".

### Changing the rule

Every number lives at the top of `scripts/scoring_rule.py` (`THRESHOLD`,
`TIER_1`, `TIER_2`, the size bands, and `RULE_VERSION`). Change it there,
bump `RULE_VERSION`, and update the tests.

**Accounts that are already scored keep their old score and stage** until they
are rescored. Each audit record stores the rule version and threshold used, so
you can always tell which rule produced a score.

---

## How to see the ranking

```
GET /ranking                     all accounts, ranked
GET /ranking?stage=qualified     qualified accounts only
GET /ranking?stage=disqualified  disqualified accounts only
```

**Order:** score (highest first), then employees (highest first), then name
(A–Z). Accounts that haven't been scored yet appear **at the end**.

An unknown stage (for example `?stage=banana`) is rejected with **422** and a
message listing the allowed values.

PowerShell example:

```powershell
$headers = @{ Authorization = "Bearer <your token>" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/ranking?stage=qualified" -Headers $headers |
    Format-Table name, score, employees, country
```

Or open `http://127.0.0.1:8000/docs` and try it there.

---

## How to rescore

Use this after correcting a company's data, for example its employee count.

```
python rescore_trigger.py <account_id> --employees 1300
python rescore_trigger.py <account_id> --country India
python rescore_trigger.py <account_id> --employees 1300 --country India
```

Find an account's id with:

```sql
select id, name from accounts where domain = 'brightleafsys.com';
```

This calls `POST /accounts/{account_id}/rescore`, which:

1. Updates only the fields you sent (the others stay as they were)
2. Adds an `updated` row to history
3. Queues a new scoring job with a **new idempotency key**, so the worker scores it again

The worker then saves the new score and stage and **adds** new history rows.
Old history is never replaced, so you can see the score before and after.

| Response | Meaning |
|----------|---------|
| `Rescore queued` (202) | Data updated, job queued |
| `Account not found` (404) | No account with that id |
| 422 | The id isn't a valid UUID, or a value has the wrong type |

---

## History and audit records

### History table

Every event for an account is a new row. Rows are never updated or deleted.

| `event_type` | Written by | When |
|--------------|-----------|------|
| `created` | API | The account is imported |
| `scored` | Worker | Every time the account is scored (stores score, stage, time, and points) |
| `stage_changed` | Worker | Only when the stage is different from before |
| `updated` | API | The account's data is corrected through rescore |

To see one account's history in order:

```sql
select event_type, score, stage, details, created_at
from history
where account_id = '<account id>'
order by created_at;
```

**History survives deleting an account.** `history.account_id` is deliberately
not a cascading foreign key, so deleting an account leaves its history in
place. This is useful for audits and for answering "what happened to this
company?" after it's gone.

### Audit records (S3)

Every scoring run writes one JSON record to the audit bucket, including the
inputs (employees, country), the points for each part, the score, threshold,
stage, previous stage, rule version, and time. To list and open them:

```
python scripts/check_s3.py
```

---

## What stops duplicates

| Problem | Protection |
|---------|-----------|
| Same company imported twice | `accounts.domain` is unique. The second insert fails and the API returns 409 before any history row or job is created |
| Same company with a differently written domain | Domains are cleaned before saving, so they become identical and hit the unique rule |
| Same queue message delivered twice | Each job carries an idempotency key. The worker checks the audit bucket and skips a key it has already completed |

SQS standard queues can deliver a message more than once, so the worker never
relies on the queue alone to prevent duplicates.

---

## What happens when each step fails

| Step | Failure | What happens |
|------|---------|--------------|
| Import file | A record is invalid (missing name/domain, `"abc"` employees, not an object) | API returns 422. The command prints it as failed and **continues** with the rest |
| Import file | The same company is already in the system | API returns 409. Reported as "already exists". No new account, history row, or job |
| API | Wrong or missing token | 401. Nothing is saved |
| API | Saving the account or its history fails | Both are in one transaction, so neither is saved |
| API | The account is saved but sending the job to the queue fails | The account exists without a score. Fix it with the rescore command |
| Queue | The worker is stopped or crashes mid-import | Unfinished jobs stay in the queue. A job is only deleted **after** it succeeds, so when the worker restarts, it continues with no lost or duplicated accounts |
| Worker | A job fails (for example, the database is briefly unavailable) | The job is not deleted. It reappears after the visibility timeout (30 s) and is retried |
| Worker | A job keeps failing | After 3 attempts SQS moves it to the DLQ (`scoring-jobs-dlq`) instead of retrying forever |
| Worker | A message can never succeed (bad JSON, missing fields, unknown task, account no longer exists) | Sent straight to the DLQ with the error reason, and removed from the main queue |
| Worker | Ctrl+C or SIGTERM | Finishes the current message, then stops cleanly |
| LocalStack | Restarted | Queues and bucket are gone. Run `python scripts/setup_queues.py` again |

Useful helper scripts:

| Script | What it does |
|--------|-------------|
| `scripts/setup_queues.py` | Creates the queue, the DLQ (with redrive policy), and the audit bucket |
| `scripts/purge_queue.py` | Empties the queue and the DLQ |
| `scripts/check_s3.py` | Lists audit records and prints one |

---

## Tests

```
python -m pytest -v
```

| File | What it covers |
|------|---------------|
| `test_scoring_rule.py` | Every size band and boundary, every country tier, missing data, the threshold, and the hand-checked examples |
| `test_domain_cleaning.py` | Domain cleaning, required and optional fields |
| `test_parse_job.py` | The worker's message checks (bad JSON, missing fields, unknown task) |
| `test_companies_api.py` | Import: created, cleaned, history row, job queued, duplicates, 422, 401 |
| `test_ranking_api.py` | Sort order, tie-breaks, unscored last, stage filter, 422 for an unknown stage |
| `test_rescore_api.py` | Rescore: 202, data updated, `updated` history, new key each time, 404, 422 |
| `test_score_handler.py` | Worker handler: score saved, history events, rescore adds instead of replacing |

Each test has a comment explaining which bug it would catch.

### How the API and worker tests run

- They use a **separate test database** (`test_db_name` in `.env`). Create it once:
  `psql -U postgres -c "create database revenue_test;"`
- Before each test, `accounts` and `history` are emptied.
- Migrations are applied to the test database automatically.
- Requests go straight into the FastAPI app (no uvicorn needed), and a **fake SQS**
  records sent jobs instead of using LocalStack.
- The worker handler is called directly with the test database.

**Never point `test_db_name` at your real database.** The tests empty its tables.

### CI

GitHub Actions (`.github/workflows/ci.yml`) runs the full test suite on every
push and pull request, with a real PostgreSQL service and fake settings.