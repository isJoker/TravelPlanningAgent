"""Loguru-based structured logger setup."""
from __future__ import annotations

import os
import sys

from loguru import logger

_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def _configure() -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=_LEVEL,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
    )


_configure()

__all__ = ["logger"]
