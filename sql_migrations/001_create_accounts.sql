create table if not exists accounts (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    domain text not null unique,
    employees integer,
    country text,
    score integer check (score >= 0 and score <= 100),
    stage text check (stage in ('qualified', 'disqualified'))
);