"""loguru setup. Logs never carry message content, only IDs and metadata."""

import sys

from loguru import logger


def setup_logging(level: str = "INFO", json: bool = False) -> None:
    logger.remove()
    # Exception tracebacks must never expose local variables containing messages or keys.
    logger.add(sys.stderr, level=level.upper(), serialize=json, diagnose=False)
