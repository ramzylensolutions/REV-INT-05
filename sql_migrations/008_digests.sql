create table if not exists digests (
    id uuid primary key default gen_random_uuid(),
    digest_date date not null,
    kind text not null check (kind in ('scheduled', 'manual')),
    status text not null default 'sending'
        check (status in ('sending', 'sent', 'failed', 'skipped')),
    last_error text,
    details jsonb,
    created_at timestamptz not null default now(),
    last_attempt_at timestamptz not null default now(),
    sent_at timestamptz
);

create unique index if not exists digests_one_scheduled_per_day
    on digests (digest_date)
    where kind = 'scheduled';