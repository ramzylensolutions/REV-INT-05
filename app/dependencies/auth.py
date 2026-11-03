from fastapi import HTTPException,Request
from ..config import Settings
import secrets
async def verify_token(request:Request):
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[len("Bearer "):]
    if not secrets.compare_digest(token,Settings.api_token):
        raise HTTPException(
            status_code=401,
            detail="Wrong credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )