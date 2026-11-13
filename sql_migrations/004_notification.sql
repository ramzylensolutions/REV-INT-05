create table if not exists notifications (
    id uuid primary key default gen_random_uuid(),
    account_id uuid not null,
    source_event_id uuid not null unique,
    status text not null default 'pending'
        check (status in ('pending', 'sent', 'skipped', 'parked')),
    attempts integer not null default 0,
    next_attempt_at timestamptz not null default now(),
    last_error text,
    details jsonb not null,
    created_at timestamptz not null default now(),
    sent_at timestamptz
);

create index if not exists notifications_status_next_attempt_idx
    on notifications (status, next_attempt_at);