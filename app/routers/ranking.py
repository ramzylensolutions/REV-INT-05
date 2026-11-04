from typing import Literal, Optional

from fastapi import APIRouter, Depends
from ..dependencies.auth import verify_token
from ..dependencies.get_a_pool import get_a_pool
from ..models.create_companies import Sorted_Account

router_2 = APIRouter(tags=["companies"], dependencies=[Depends(verify_token)])


@router_2.get("/ranking", response_model=list[Sorted_Account])
async def ranking(
    stage: Optional[Literal["qualified", "disqualified"]] = None,
    Connection=Depends(get_a_pool),
):
    order = "order by score desc nulls last, employees desc nulls last, name asc"

    if stage:
        rows = await Connection.fetch(f"select * from accounts where stage = $1 {order}", stage)
    else:
        rows = await Connection.fetch(f"select * from accounts {order}")

    return [dict(row) for row in rows]


'''Invoke-RestMethod -Uri "http://127.0.0.1:8000/ranking" -Headers $headers |
    Format-Table name, score, employees, country, stage'''