"""/api/auth endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import User
from app.deps import get_db
from app.security.auth import (
    _DUMMY_HASH,
    COOKIE_NAME,
    SESSION_MAX_AGE,
    LoginLimiter,
    current_user,
    hash_password,
    make_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = LoginLimiter()


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


def _set_session_cookie(response: Response, settings: Settings, user: User) -> None:
    response.set_cookie(
        COOKIE_NAME,
        make_session_token(settings, user),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=settings.public_base_url.startswith("https://"),
    )


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login")
async def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    ip = _ip(request)
    if limiter.blocked(ip):
        raise HTTPException(status_code=429, detail="Too many failed attempts")
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if user is None or not ok:
        limiter.record_failure(ip)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    limiter.reset(ip)
    _set_session_cookie(response, settings, user)
    return {"username": user.username}


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(user: Annotated[User, Depends(current_user)]) -> dict[str, str]:
    return {"username": user.username}


@router.post("/password")
async def change_password(
    body: PasswordBody,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    user.password_hash = hash_password(body.new_password)
    db.add(user)
    await db.commit()
    # Sessions are bound to the password hash: every other session is now signed out, and this
    # one gets a fresh cookie so the admin who just changed it is not logged out too.
    _set_session_cookie(response, settings, user)
    return {"ok": True}
