"""/api/settings: flat key map; secrets are write-only."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.deps import get_db
from app.security.auth import current_user
from app.settings_store import REGISTRY, all_settings, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(current_user)])


class SettingsUpdate(BaseModel):
    settings: dict[str, Any]


@router.get("")
async def read_settings(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, Any]:
    return await all_settings(db)


@router.put("")
async def update_settings(
    body: SettingsUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    cfg: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    # Validate everything first so a bad key never leaves a half-applied update.
    errors: dict[str, str] = {}
    for key, value in body.settings.items():
        spec = REGISTRY.get(key)
        if spec is None:
            errors[key] = "unknown setting"
            continue
        try:
            spec.validate(value)
        except ValueError as exc:
            errors[key] = str(exc)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    for key, value in body.settings.items():
        await set_setting(db, key, value, cfg.key_bytes)
    return await all_settings(db)
