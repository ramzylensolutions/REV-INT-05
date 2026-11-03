from fastapi import APIRouter,Depends
from ..dependencies.auth import verify_token
from ..dependencies.get_a_pool import get_a_pool
from ..models.create_companies import Sorted_Account
router_2 = APIRouter(tags=["companies"],dependencies=[Depends(verify_token)])
@router_2.get("/ranking",status_code=201,response_model=list[Sorted_Account])
async def ranking(Connection = Depends(get_a_pool)):
    sql = """select * from accounts where stage='qualified' order by score desc nulls last, employees desc nulls last, name asc ;"""
    rows = await Connection.fetch(sql)
    accounts = [dict(row) for row in rows]
    return accounts

'''Invoke-RestMethod -Uri "http://127.0.0.1:8000/ranking" -Headers $headers |
    Format-Table name, score, employees, country, stage'''