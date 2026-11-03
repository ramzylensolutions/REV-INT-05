from fastapi import FastAPI
from contextlib import asynccontextmanager
from .db_conn import create_pool
import os
from .routers.insert_companies import router
from .routers.ranking import router_2
from .routers.rescore import router3
import boto3
from dotenv import load_dotenv
load_dotenv()

async def run_migration(pool):
    async with pool.acquire() as connection:
        migration_directory = os.path.join(os.path.dirname(__file__), "..", "sql_migrations")
        sql="""
                create table if not exists track_migration (
                    filename text primary key,
                    applied_at timestamptz not null default current_timestamp
                )
            """
        await connection.execute(sql)
        applied = {row[0] for row in (await connection.fetch("""select filename from track_migration"""))}
        for filename in sorted(os.listdir(migration_directory)):
            if filename in applied or not filename.endswith(".sql"):
                continue
            with open (os.path.join(migration_directory,filename),encoding="utf-8") as f:
                await connection.execute(f.read())
                await connection.execute("""insert into track_migration(filename) values($1)""",filename)
@asynccontextmanager
async def lifespan(app:FastAPI):
    app.state.sqs = boto3.client("sqs",
                                endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
                                region_name=os.getenv("AWS_REGION"),
                                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),)
    app.state.queue_url = app.state.sqs.get_queue_url(QueueName=os.getenv("SCORING_QUEUE_NAME"))["QueueUrl"]
    app.state.pool = await create_pool()
    print("The Database connection pool created Successfully")
    await run_migration(app.state.pool)
    yield
    print("The Database connection has been closed")
    await app.state.pool.close()


app = FastAPI(lifespan=lifespan)

app.include_router(router)
app.include_router(router_2)
app.include_router(router3)