from fastapi import Request
async def get_a_pool(request:Request):
    pool = request.app.state.pool
    async with pool.acquire() as connection:
        yield connection