"""Utility functions for gateway service."""
import logging
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(name)s] %(levelname)s: %(message)s'
)

logger = logging.getLogger("gateway")


def log_error(message: str, error: Optional[Exception] = None, **kwargs):
    """Log an error with context."""
    context = " ".join([f"{k}={v}" for k, v in kwargs.items()])
    if error:
        logger.error(f"{message} - {context}: {error}", exc_info=True)
    else:
        logger.error(f"{message} - {context}")


def log_info(message: str, **kwargs):
    """Log an info message with context."""
    context = " ".join([f"{k}={v}" for k, v in kwargs.items()])
    logger.info(f"{message} - {context}")


def log_warning(message: str, **kwargs):
    """Log a warning message with context."""
    context = " ".join([f"{k}={v}" for k, v in kwargs.items()])
    logger.warning(f"{message} - {context}")


def safe_parse_time(time_str: str) -> tuple[int, int]:
    """Safely parse time string in MM:SS format."""
    try:
        parts = time_str.split(":")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        pass
    return 0, 0


def format_period_label(period: int) -> str:
    """Format period number as label (1st, 2nd, 3rd, OT, etc.)."""
    if period == 1:
        return "1st"
    elif period == 2:
        return "2nd"
    elif period == 3:
        return "3rd"
    elif period == 4:
        return "OT"
    else:
        return f"{period}th"

