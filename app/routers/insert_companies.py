from fastapi import APIRouter,Depends,HTTPException,Request
from ..dependencies.auth import verify_token
from ..models.create_companies import create_companies
from ..dependencies.get_a_pool import get_a_pool
import asyncpg,asyncio
import json,uuid
router = APIRouter(tags=["companies"],dependencies=[Depends(verify_token)])
@router.post("/companies",status_code=201)
async def insert_company(company:create_companies,request:Request,connection=Depends(get_a_pool)):
    idempotency_key = str(uuid.uuid4())
    try:
        sql = """insert into accounts (name, domain, employees, country) values ($1, $2, $3, $4)
        returning id """
        sql1="""insert into history(account_id,event_type,details)values($1,$2,$3)"""
        created="created"
        details={"Created_from":"Import command"}
        async with connection.transaction():
            account_id=await connection.fetchval(sql,company.name,company.domain,company.employees,company.country)
            await connection.execute(sql1,account_id,created,json.dumps(details))
        await asyncio.to_thread(request.app.state.sqs.send_message,
                                QueueUrl=request.app.state.queue_url,
                                MessageBody=json.dumps({"account_id": str(account_id),"task": "score_account","idempotency_key": idempotency_key,}),)
    except asyncpg.UniqueViolationError:
        raise HTTPException(
                status_code=409,
                detail=f"Company with domain '{company.domain}' already exists",
            )
    return "Inserted Successfully"