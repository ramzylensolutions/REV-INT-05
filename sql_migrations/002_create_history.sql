create table if not exists history (
    id uuid primary key default gen_random_uuid(),
    account_id uuid not null,
    event_type text not null check (event_type in ('created', 'scored', 'stage_changed')),
    details jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_history_account_id on history (account_id);