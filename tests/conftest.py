from tests.apply_migration import run_migration
from dotenv import load_dotenv
import asyncpg
load_dotenv()
import pytest,json,os,httpx
from contextlib import asynccontextmanager
from app.main import app
def env(name):
    return os.getenv(name.upper()) or os.getenv(name.lower())

TEST_DB_NAME = env("test_db_name")
TEST_DB_USER = env("test_db_user")
TEST_DB_PASS = env("test_db_pass")
TEST_DB_HOST = env("test_db_host")
TEST_DB_PORT = int(env("test_db_port"))
@asynccontextmanager
async def create_a_pool():
    pool = await asyncpg.create_pool(
        user = TEST_DB_USER,
        password= TEST_DB_PASS,
        database=TEST_DB_NAME,
        host=TEST_DB_HOST,
        port=TEST_DB_PORT
    )
    yield pool
    await pool.close()

@pytest.fixture
async def pool():
    async with create_a_pool() as test_pool:
        await run_migration(test_pool)

        async with test_pool.acquire() as connection:
            await connection.execute("truncate table accounts, history")

        yield test_pool

class FakeSQS:
    def __init__(self):
        self.messages = []

    def send_message(self, QueueUrl, MessageBody):
        self.messages.append(json.loads(MessageBody))
        return {"MessageId": "fake-id"}
@pytest.fixture
def fake_sqs():
    return FakeSQS()

@pytest.fixture
async def client(pool, fake_sqs):
    app.state.pool = pool
    app.state.sqs = fake_sqs
    app.state.queue_url = "fake-queue"

    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {env('api_token')}"}

    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers=headers) as c:
        yield c