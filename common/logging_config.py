"""Structured logging configuration for all services."""

import logging
import sys
from typing import Optional

from common.constants import LOG_FORMAT, LOG_DATE_FORMAT


def setup_logger(
    name: str, level: int = logging.INFO, log_file: Optional[str] = None
) -> logging.Logger:
    """
    Configure and return a structured logger.

    Args:
        name: Logger name (typically service name)
        level: Logging level (default: INFO)
        log_file: Optional file path for log output

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers = []

    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Optional file handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
