# REV-INT-05 · Score and rank accounts
# REV-INT-06 · Slack notifications

Sales has a list of target companies and no way to tell which ones to call first.
This project imports that list, scores every company automatically in the
background, and gives sales a ranked list so they call the most promising
companies first.

When a company becomes **qualified**, the sales team is told in **Slack**
straight away, and every weekday morning they get a short **digest** of the
best accounts, so good leads are acted on the same day.

There is no user interface. **The API, the command line, and Slack are the interface.**

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
                                                Worker ──▶ PostgreSQL (score, stage, history)
                                                   │        └─ became qualified? → alert row in `notifications` (pending)
                                                   │
                                                   └──▶ S3 bucket (audit record for this scoring run)

Sender (separate process)
   ├─ every few seconds: pending alerts ──▶ Slack (one message each, or one summary for many)
   └─ weekdays at 09:00 IST: daily digest ──▶ Slack

GET /ranking?stage=qualified  ──▶  accounts sorted by score, highest first
```

| Component | File(s) | Job |
|-----------|---------|-----|
| Import command | `import_trigger.py` | Reads a companies JSON file and sends each company to the API, one at a time |
| API | `app/` | Validates and cleans each company, saves it, writes history, queues a scoring job. Also serves the ranking and rescore endpoints |
| Database | `sql_migrations/` | `accounts`, `history`, `notifications` (Slack alerts), `settings` (on/off switch), `digests`. Migrations run automatically when the API starts |
| Queue | SQS in LocalStack | Holds scoring jobs. Failed jobs move to a dead-letter queue (DLQ) after 3 tries |
| Worker | `scripts/main.py`, `scripts/handlers.py` | Takes jobs from the queue, scores the account, saves the result, creates a Slack alert when an account becomes qualified, writes the audit record |
| Scoring rule | `scripts/scoring_rule.py` | The rule itself, in one place |
| Audit bucket | S3 in LocalStack | One JSON record per scoring run |
| Sender | `scripts/sender_main.py`, `scripts/sender.py` | Sends waiting alerts to Slack, retries failures, parks alerts that keep failing, and sends the daily digest |
| Slack client | `scripts/slack_client.py` | Posts one message to the Slack webhook and reports what happened: sent, retry, park, or rate limited |
| Message text | `scripts/slack_messages.py` | Builds the alert, the bulk summary, and the digest messages |
| Digest | `scripts/digest.py` | Collects the digest numbers, sends it once per weekday, and offers a manual trigger |
| On/off switch | `scripts/slack_settings.py`, `scripts/slack_switch.py` | Turns Slack notifications on or off without a deploy |
| Parked alerts | `scripts/parked.py` | Lists parked or skipped alerts and resends one with a single command |

**Why scoring runs in the background:** the API answers immediately instead of
waiting for scoring, a slow or failing scoring step can't break the import, and
jobs survive a worker crash because they wait in the queue until they succeed.

**Why Slack messages are sent by a separate sender:** Slack is an outside
service that can be slow, down, or reject us. Scoring only writes an alert row
in the database. It never calls Slack, so Slack problems can never stop
accounts from being created or scored.

---

## Setup

### Requirements

- Python 3.11+
- Docker and Docker Compose

### 1. Install Python packages

These are needed to run the tests and the import command on your machine.

```
python -m venv venv
venv\Scripts\activate            # Windows
source venv/bin/activate         # Mac / Linux

pip install -r requirements.txt
```

### 2. Create your `.env`

Copy `.env.example` to `.env` and fill in your own values. `.env` is in
`.gitignore` and `.dockerignore`, and must never be committed.

| Setting | Meaning |
|---------|---------|
| `api_token` | Token the API expects in `Authorization: Bearer <token>` |
| `api_base_url` | Where the import and rescore commands send requests (`http://127.0.0.1:8000`) |
| `db_name`, `db_user`, `db_pass`, `db_host`, `db_port` | The PostgreSQL database. For the Docker database use `revenue_project`, `postgres`, `postgres`, `127.0.0.1`, `5434` |
| `AWS_ENDPOINT_URL`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | LocalStack connection (dummy keys are fine) |
| `SCORING_QUEUE_NAME`, `SCORING_DLQ_NAME` | Queue names |
| `AUDIT_BUCKET_NAME` | S3 bucket for audit records |
| `SLACK_WEBHOOK_URL` | The Slack incoming webhook URL. **Secret.** See [The Slack secret](#the-slack-secret) |
| `DIGEST_TIME` | Optional. When the daily digest is sent, 24-hour format. Default `09:00` |
| `DIGEST_TIMEZONE` | Optional. Time zone for the digest. Default `Asia/Kolkata` (IST) |
| `test_db_name`, `test_db_user`, `test_db_pass`, `test_db_host`, `test_db_port` | A **separate** database for the tests |

On Windows, use `127.0.0.1` instead of `localhost` in URLs. `localhost` tries
IPv6 first and adds about 2 seconds to every request.

### 3. Set up a test Slack workspace

**Never post to a real team channel while testing.** Use a separate workspace:

1. Create a new workspace at `slack.com/get-started` and a channel, for example `#test-channel`
2. Go to `api.slack.com/apps` → **Create New App** → **Pick features**, and choose the test workspace
3. Add only the `incoming-webhook` bot scope. No events
4. Open **Incoming Webhooks**, switch it on, click **Add New Webhook**, and choose the channel
5. Copy the URL into `.env` as `SLACK_WEBHOOK_URL`. Don't paste it anywhere else

### 4. Start everything

```
docker compose up -d --build
```

This starts PostgreSQL, LocalStack, a one-off `setup` job (creates the queues
and bucket), the API, the worker, and the sender. The API applies every file in
`sql_migrations/` at startup, in order, and records each one in
`track_migration` so it only runs once.

Check that everything is running:

```
docker compose ps
docker compose logs -f sender
```

You should see `Sender started`.

> LocalStack keeps queues and buckets in memory. If it restarts, run
> `docker compose up -d setup` again, or the API fails with
> "The specified queue does not exist".

Version `4.4` of LocalStack is used on purpose: newer images require an auth token.

### Running commands

The helper commands below are run inside the sender container, so they use the
same database settings as the services:

```
docker compose exec sender python -m scripts.<name> ...
```

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

Within about a minute, the worker scores every new account, and every account
that becomes qualified is announced in Slack.

**Running the same file again is safe.** Every company is reported as already
existing, nothing is duplicated, nothing is scored twice, and no Slack message
is sent again.

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
(A–Z). Accounts that haven't been scored yet appear **at the end**. The daily
digest uses exactly the same order.

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

## Slack notifications

### How an alert gets from a score change to Slack

1. **The worker scores an account.** In the **same transaction** as the new
   score, if the stage changed **to qualified**, it inserts a row into
   `notifications` with status `pending`. The row is linked to the
   `stage_changed` history row that caused it (`source_event_id`, unique).
   The worker never calls Slack.
2. **The sender** (a separate process) checks for waiting alerts every few
   seconds. It waits until the oldest waiting alert is at least **15 seconds**
   old, so alerts from one import can gather.
3. It **locks** the alerts it takes (`FOR UPDATE SKIP LOCKED`), so two senders
   never send the same alert.
4. It checks the **on/off switch**. If notifications are off, the alerts are
   marked `skipped`.
5. It sends:
   - **3 or fewer** waiting → one message per alert
   - **more than 3** waiting → **one summary message** for all of them
6. It records the result on each alert (`sent`, retry later, or `parked`) and
   writes a history row for each company.

Alert statuses:

```
pending ──► sent      Slack accepted it
        ──► skipped   notifications were switched off
        ──► parked    Slack rejected it, or it failed 8 times
parked / skipped ──► pending   (resend command)
```

### What stops duplicate alerts

| Situation | Why there is no second message |
|-----------|-------------------------------|
| Rescore, and the account stays qualified | The stage didn't change, so no new alert is created. History gets `alert_skipped` with reason `already_qualified` |
| The same scoring job runs twice, or the worker restarts mid-job | The second run sees the account is already qualified, so the stage doesn't change and no alert is created |
| Two senders running at once | Each alert is locked by the sender working on it; the other sender skips it |
| Resending an alert that was already sent | The resend command refuses anything that isn't `parked` or `skipped` |

An account that goes **qualified → disqualified → qualified** gets a **new**
alert, because the second change to qualified is a new `stage_changed` row.
Its history shows both alerts and why.

### Bulk imports

Importing many companies at once doesn't flood the channel. Alerts gather for
15 seconds; if more than 3 are waiting, the sender posts **one summary**:

```
📥 19 new qualified leads
Top 5 by score:
1. OceanField Systems, 100, oceanfieldsys.com
...
…and 14 more. They'll appear in the morning summary.
```

A large import that takes a while arrives in waves, so it produces **a few**
summaries, one per wave. In testing, importing 100 companies (48 qualified)
produced 3 messages. Every company in a summary still gets its own
`alert_sent` history row, with `"sent_as": "summary"`.

### Daily digest

Every weekday (Monday–Friday) at **09:00 IST**, the channel gets one message:

```
☀️ Morning summary: Tue 17 Nov
🆕 6 new qualified leads since yesterday
⏳ 12 companies still waiting to be scored

Top 10 qualified leads
1. Acme Corp, 100, acme.com 🆕
...
```

- **Top 10:** qualified accounts in the same order as `GET /ranking`
- **New:** accounts that became qualified since the last digest and are still qualified (marked 🆕 in the list)
- **Waiting:** accounts that haven't been scored yet
- If nothing is new, it says so ("No new qualified leads since yesterday.") instead of being skipped

The sender checks once a minute whether the digest is due. **Only one
scheduled digest per day** is allowed (a unique index on the `digests` table),
so it is sent once even if two senders are running.

If the machine is off at 09:00, the digest is sent as soon as the sender starts
again that day. Days when the sender never runs are not sent later. In
production this runs on an always-on server.

**Send a digest now** (for testing or a demo):

```
docker compose exec sender python -m scripts.digest now
```

Manual digests are recorded with `kind = 'manual'` and don't block the
scheduled one.

### How to switch notifications off

```
docker compose exec sender python -m scripts.slack_switch off
docker compose exec sender python -m scripts.slack_switch on
docker compose exec sender python -m scripts.slack_switch status
```

The switch is stored in the `settings` table and checked **before every send**,
so it works immediately, without a deploy or restart.

While it is off:
- No alerts or digests are posted
- Each alert is marked `skipped`, with an `alert_skipped` history row (reason `notifications_off`)
- Skipped alerts are **not** sent later when the switch is turned back on. They can be resent by hand (below)

### How to resend a parked alert

See parked and skipped alerts:

```
docker compose exec sender python -m scripts.parked list
```

```
3f2a9c...  parked   Parked Test Ltd   attempts=1  error=http 404: no_service
```

Fix the cause first (for example, a new webhook URL), then resend:

```
docker compose exec sender python -m scripts.parked resend <id>
```

The alert goes back to `pending` with 0 attempts, an `alert_resent` history row
is written, and the sender sends it within about 15 seconds. Alerts that are
already `sent` or `pending` are refused, so a resend can't cause a duplicate.

### What happens when each step fails

| Step | Failure | What happens |
|------|---------|--------------|
| Slack | Down, timeout, connection error, or 5xx | Alert stays `pending` and is retried after 30 s, 1, 2, 4, then every 5 minutes. After **8** failed attempts (about 22 minutes) it is `parked` |
| Slack | Rate limited (429) | The sender waits for the time in Slack's `Retry-After` header. Not counted as a failed attempt |
| Slack | Rejects the message (bad payload, channel archived, webhook removed, blocked by an admin) | Retrying won't help, so the alert is `parked` straight away with Slack's reason in `last_error` |
| Slack | Down for 10 minutes while accounts are imported | Accounts are still created and scored (scoring never calls Slack). Every missed alert is delivered once Slack is back |
| Sender | Crashes **after** Slack accepted a message but **before** it recorded it | The transaction is rolled back, the alert is still `pending`, and it is sent again. A rare duplicate is possible. This is a deliberate choice: a duplicate is better than a lost lead (at-least-once delivery) |
| Sender | Unexpected error (for example, the database is briefly unavailable) | Logged by error type, waits 5 seconds, carries on. One error doesn't stop the sender |
| Sender | Stopped or crashes | Docker restarts it (`restart: unless-stopped`). Pending alerts wait in the database |
| Sender | Ctrl+C or SIGTERM | Finishes the current alert, then stops cleanly |
| Digest | Slack fails | Marked `failed` and tried again 2 minutes later |
| Digest | Sender crashes while sending | The digest stays `sending`; after 10 minutes another check takes it over and sends it |
| Switch | Notifications off | Alerts and digests are `skipped`, and history says why |

### The Slack secret

The webhook URL works like a password: anyone who has it can post in the channel.

| Where | How it is protected |
|-------|---------------------|
| Repository | Lives only in `.env`, which is in `.gitignore`. `docker-compose.yml` reads it as `${SLACK_WEBHOOK_URL}`, so the file holds no secret |
| Docker image | `.env` is in `.dockerignore`, so `COPY . .` never puts it in the image |
| Code | Loaded as a `SecretStr`, which prints as `**********`. The real value is read with `get_secret_value()` in one place only, where the Slack client is created |
| Logs | httpx logs every request URL, so the `httpx` and `httpcore` loggers are set to `WARNING`. Errors are logged by type only (for example `ConnectError`), never the full message |
| History and `last_error` | Only short, safe reasons are stored (`timeout`, `http 503`, `http 410: channel_is_archived`) |

Check the logs are clean:

```
docker compose logs sender | Select-String "hooks.slack.com"
```

This should print nothing.

**If the webhook leaks** (first ten minutes):

1. In Slack, open the app → **Incoming Webhooks** → **remove** the leaked webhook. It stops working immediately
2. **Add a new webhook** for the same channel
3. Put the new URL in `.env`
4. Recreate the sender so it uses the new URL and old logs are discarded:
   `docker compose up -d --force-recreate sender`
5. Check the channel for messages that didn't come from us

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
| `alert_sent` | Sender | Slack accepted the alert (`sent_as`: `single` or `summary`) |
| `alert_failed` | Sender | One send attempt failed and will be retried (attempt number, error, wait time) |
| `alert_parked` | Sender | The alert was given up and needs an operator |
| `alert_skipped` | Worker / Sender | No alert was sent on purpose: `already_qualified` or `notifications_off` |
| `alert_resent` | Parked command | An operator put a parked or skipped alert back in the queue |

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

## What stops duplicate accounts and scoring

| Problem | Protection |
|---------|-----------|
| Same company imported twice | `accounts.domain` is unique. The second insert fails and the API returns 409 before any history row or job is created |
| Same company with a differently written domain | Domains are cleaned before saving, so they become identical and hit the unique rule |
| Same queue message delivered twice | Each job carries an idempotency key. The worker checks the audit bucket and skips a key it has already completed |

SQS standard queues can deliver a message more than once, so the worker never
relies on the queue alone to prevent duplicates. For duplicate **Slack
alerts**, see [What stops duplicate alerts](#what-stops-duplicate-alerts).

---

## What happens when import and scoring fail

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
| LocalStack | Restarted | Queues and bucket are gone. Run `docker compose up -d setup` again |

Useful helper scripts:

| Script | What it does |
|--------|-------------|
| `scripts/setup_queues.py` | Creates the queue, the DLQ (with redrive policy), and the audit bucket |
| `scripts/purge_queue.py` | Empties the queue and the DLQ |
| `scripts/check_s3.py` | Lists audit records and prints one |
| `scripts/slack_switch.py` | Turns Slack notifications on or off, or shows the status |
| `scripts/parked.py` | Lists parked or skipped alerts, and resends one |
| `scripts/digest.py` | Sends the daily digest now (`now`) |

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
| `test_companies.py` | Import: created, cleaned, history row, job queued, duplicates, 422, 401 |
| `test_ranking.py` | Sort order, tie-breaks, unscored last, stage filter, 422 for an unknown stage |
| `test_rescore.py` | Rescore: 202, data updated, `updated` history, new key each time, 404, 422 |
| `test_score_account.py` | Worker handler: score saved, history events, rescore adds instead of replacing |
| `test_notification.py` | Alerts: one alert when qualified, none on rescore or when disqualified, two after qualified → disqualified → qualified, `already_qualified` skip recorded |
| `test_slack_client.py` | Each Slack answer is understood (200, 429, 5xx, 4xx, timeout), and the webhook URL never appears in a saved error |
| `test_slack_settings.py` | The switch turns on and off; a missing switch counts as off |
| `test_sender.py` | Sent once; switch off → skipped; Slack down then back → sent; keeps failing → parked; rejected → parked; rate limited → waits |

Each test has a comment explaining which bug it would catch.

### How the tests run

- They use a **separate test database** (`test_db_name` in `.env`). Create it once:
  `psql -U postgres -c "create database revenue_test;"`
- Before each test, `accounts`, `history`, and `notifications` are emptied.
  `settings` is kept, because it holds the on/off switch.
- Migrations are applied to the test database automatically.
- Requests go straight into the FastAPI app (no uvicorn needed), and a **fake SQS**
  records sent jobs instead of using LocalStack.
- The worker handler is called directly with the test database.
- **No test calls the real Slack.** The Slack client is tested with httpx's
  `MockTransport`, and the sender is tested with `tests/fake_slack.py`, a pretend
  Slack that records messages and returns whatever answer the test asks for.

**Never point `test_db_name` at your real database.** The tests empty its tables.

### CI

GitHub Actions (`.github/workflows/ci.yml`) runs the full test suite on every
push and pull request, with a real PostgreSQL service and fake settings. CI
doesn't need a Slack webhook.