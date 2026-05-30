"""stderr logging helpers for build-index (timings and SQL phase progress)."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

BUILD_LOGGER_NAME = "polscience.retrieval.build"


def configure_build_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure stderr logging for index build. Idempotent for repeated calls."""
    logger = logging.getLogger(BUILD_LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
    else:
        for handler in logger.handlers:
            handler.setLevel(level)
    logger.propagate = False
    return logger


def get_build_logger() -> logging.Logger:
    return logging.getLogger(BUILD_LOGGER_NAME)


@contextmanager
def log_step(logger: logging.Logger, step: str, **details: Any) -> Iterator[None]:
    detail_str = ", ".join(f"{k}={v}" for k, v in details.items() if v is not None)
    if detail_str:
        logger.info("▶ %s (%s)", step, detail_str)
    else:
        logger.info("▶ %s", step)
    started = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed = time.perf_counter() - started
        logger.exception("✗ %s failed after %.1fs", step, elapsed)
        raise
    elapsed = time.perf_counter() - started
    logger.info("✓ %s done in %.1fs", step, elapsed)


def log_progress(
    logger: logging.Logger,
    message: str,
    *,
    current: int,
    interval: int = 50_000,
) -> None:
    if current == 1 or current % interval == 0:
        logger.info(message, current)
