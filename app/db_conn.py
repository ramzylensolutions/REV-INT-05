import asyncpg
from .config import Settings
async def create_pool():
    pool = await asyncpg.create_pool(
        user=Settings.db_user,
        password=Settings.db_pass,
        database=Settings.db_name,
        host=Settings.db_host,
        port=Settings.db_port
    )
    return pool