from fastapi import APIRouter,Depends,HTTPException,Request
from ..dependencies.auth import verify_token
from ..dependencies.get_a_pool import get_a_pool
import uuid,asyncio,json
from ..models.create_companies import update_account
from uuid import UUID
router3 = APIRouter(tags=["companies"],dependencies=[Depends(verify_token)])
@router3.post("/accounts/{account_id}/rescore",status_code=202)
async def rescore(account_id:UUID,update:update_account,request:Request,connection = Depends(get_a_pool)):
    idempotency = str(uuid.uuid4())
    sql="""select id from accounts where id = $1"""
    found = await connection.fetchval(sql,account_id)
    if found is None:
        raise HTTPException(status_code=404, detail="The company doesn't exist")
    async with connection.transaction():
        await connection.execute(
            """update accounts
            set employees = coalesce($1, employees),
            country = coalesce($2, country)
            where id = $3""",update.employees,update.country,account_id
        )
        event_type = "stage_changed"
        details = {"employees": update.employees, "country": update.country}
        await connection.execute(
            """insert into history(account_id,event_type,details)values($1,$2,$3)""",account_id,event_type,json.dumps(details)
        )

    await asyncio.to_thread(request.app.state.sqs.send_message,
                                    QueueUrl=request.app.state.queue_url,
                                    MessageBody=json.dumps({"account_id": str(account_id),"task": "score_account","idempotency_key": idempotency,}),)

    return {"account_id": str(account_id), "status": "queued"}