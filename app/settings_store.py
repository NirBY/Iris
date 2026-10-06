"""Runtime settings in the `settings` table (typed JSON values with code defaults)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting

DEFAULTS: dict[str, Any] = {
    "scope.monitor_from_me": True,
    "scope.monitor_direct": True,
    "scope.monitor_groups": True,
    "alerts.sender_instance_id": None,
    "alerts.recipient": None,
}


async def get_setting(db: AsyncSession, key: str) -> Any:
    row = await db.get(Setting, key)
    return row.value if row is not None else DEFAULTS.get(key)


async def set_setting(db: AsyncSession, key: str, value: Any, *, is_secret: bool = False) -> None:
    row = await db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=value, is_secret=is_secret))
    else:
        row.value = value
        row.is_secret = is_secret
    await db.commit()
