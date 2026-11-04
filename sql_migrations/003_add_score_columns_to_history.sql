alter table history add column if not exists score integer;
alter table history add column if not exists stage text;
alter table history add column if not exists scored_at timestamptz;