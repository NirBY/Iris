"""Admin auth: argon2 hashing, signed session cookie, login rate limit."""

import hashlib
import hmac
import time
from collections import defaultdict, deque
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import User
from app.deps import get_db

COOKIE_NAME = "iris_session"
SESSION_MAX_AGE = 7 * 24 * 3600
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW = 15 * 60

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    # Derive a signing key distinct from the encryption key.
    key = hmac.new(settings.key_bytes, b"iris-session-v1", hashlib.sha256).hexdigest()
    return URLSafeTimedSerializer(key, salt="session")


def make_session_token(settings: Settings, user_id: int) -> str:
    return _serializer(settings).dumps({"uid": user_id})


def read_session_token(settings: Settings, token: str) -> int | None:
    try:
        data = _serializer(settings).loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, int) else None


class LoginLimiter:
    """In-memory: 5 failures per 15 minutes per IP."""

    def __init__(self) -> None:
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, ip: str, now: float) -> deque[float]:
        q = self._fails[ip]
        while q and now - q[0] > LOGIN_WINDOW:
            q.popleft()
        return q

    def blocked(self, ip: str) -> bool:
        return len(self._prune(ip, time.monotonic())) >= LOGIN_MAX_FAILURES

    def record_failure(self, ip: str) -> None:
        self._prune(ip, time.monotonic()).append(time.monotonic())

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)


async def bootstrap_admin(session: AsyncSession, settings: Settings) -> None:
    """Create the initial admin on first run; env credentials are ignored afterwards."""
    if (await session.execute(select(User.id).limit(1))).first():
        return
    if not settings.admin_username or not settings.admin_password:
        raise RuntimeError("IRIS_ADMIN_USERNAME and IRIS_ADMIN_PASSWORD are required on first run")
    session.add(
        User(username=settings.admin_username, password_hash=hash_password(settings.admin_password))
    )
    await session.commit()


async def current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    uid = read_session_token(settings, token) if token else None
    user = await db.get(User, uid) if uid is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
