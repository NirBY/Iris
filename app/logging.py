"""loguru setup. Logs never carry message content, only IDs and metadata."""

import sys

from loguru import logger


def setup_logging(level: str = "INFO", json: bool = False) -> None:
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), serialize=json)
