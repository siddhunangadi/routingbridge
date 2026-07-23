"""Application-wide logging configuration."""

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger once, at process startup.

    A single call here (from main.py) beats sprinkling `logging.basicConfig`
    calls across modules, which can silently no-op if called more than once.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
