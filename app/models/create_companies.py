from pydantic import BaseModel,field_validator,Field
from uuid import UUID
from typing import Literal,Optional
class create_companies(BaseModel):
    name:str
    domain:str
    employees: Optional[int] = None
    country: Optional[str] = None
    @field_validator("domain")
    @classmethod
    def clean_domain(cls, value):
        value = value.strip()
        value = value.lower()
        if value.startswith("https://"):
            value = value[8:]
        elif value.startswith("http://"):
            value = value[7:]
        if value.startswith("www."):
            value = value[4:]
        value = value.split("/")[0]
        return value
class Sorted_Account(BaseModel):
    id: UUID
    name: str
    domain: str
    employees: Optional[int] = None
    country: Optional[str] = None
    score: Optional[int] = Field(default=None, ge=0, le=100)
    stage: Optional[Literal["qualified", "disqualified"]] = None
class update_account(BaseModel):
    employees: Optional[int]=None
    country: Optional[str]=None