import os


async def run_migration(pool):
    migration_directory = os.path.join(os.path.dirname(__file__), "..", "sql_migrations")

    async with pool.acquire() as connection:
        await connection.execute(
            """
            create table if not exists track_migration (
                filename text primary key,
                applied_at timestamptz not null default current_timestamp
            )
            """
        )

        rows = await connection.fetch("select filename from track_migration")
        applied = {row[0] for row in rows}

        for filename in sorted(os.listdir(migration_directory)):
            if filename in applied or not filename.endswith(".sql"):
                continue

            with open(os.path.join(migration_directory, filename), encoding="utf-8") as f:
                sql_text = f.read()

            async with connection.transaction():
                await connection.execute(sql_text)
                await connection.execute(
                    "insert into track_migration (filename) values ($1)", filename
                )