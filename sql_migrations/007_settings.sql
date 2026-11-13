create table if not exists settings (
    key text primary key,
    value text not null,
    updated_at timestamptz not null default now()
);

insert into settings (key, value)
values ('slack_enabled', 'true')
on conflict (key) do nothing;