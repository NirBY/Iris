"""Programmatic `alembic upgrade head`."""

from alembic import command
from alembic.config import Config


def upgrade_head(url: str | None = None) -> None:
    cfg = Config("alembic.ini")
    if url:
        cfg.attributes["url"] = url
    command.upgrade(cfg, "head")
