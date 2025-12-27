"""Database connection pool management."""

import os
from contextlib import asynccontextmanager
from typing import Optional

from psycopg_pool import AsyncConnectionPool

logger = None


def get_logger():
    """Lazy import logger to avoid circular imports."""
    global logger
    if logger is None:
        import logging
        import sys

        sys.path.insert(
            0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        )
        from common.logging_config import setup_logger

        logger = setup_logger("gateway.db_pool", level=logging.INFO)
    return logger


# Global connection pool
_db_pool: Optional[AsyncConnectionPool] = None


async def init_db_pool(
    database_url: Optional[str] = None, min_size: int = 2, max_size: int = 10
):
    """
    Initialize the database connection pool.

    Args:
        database_url: PostgreSQL connection string
        min_size: Minimum number of connections in pool
        max_size: Maximum number of connections in pool
    """
    global _db_pool

    if _db_pool is not None:
        return

    if not database_url:
        database_url = os.environ.get("DATABASE_URL")

    if not database_url:
        get_logger().warning("DATABASE_URL not set, connection pool not initialized")
        return

    try:
        _db_pool = AsyncConnectionPool(
            database_url,
            min_size=min_size,
            max_size=max_size,
            open=True,
        )
        get_logger().info(
            f"Database connection pool initialized (min={min_size}, max={max_size})"
        )
    except Exception as e:
        get_logger().error(f"Failed to initialize database connection pool: {e}")
        raise


async def close_db_pool():
    """Close the database connection pool."""
    global _db_pool

    if _db_pool is not None:
        await _db_pool.close()
        _db_pool = None
        get_logger().info("Database connection pool closed")


@asynccontextmanager
async def get_db_connection():
    """
    Get a database connection from the pool.

    Yields:
        AsyncConnection: Database connection

    Raises:
        RuntimeError: If pool is not initialized
    """
    if _db_pool is None:
        raise RuntimeError(
            "Database connection pool not initialized. Call init_db_pool() first."
        )

    async with _db_pool.connection() as conn:
        yield conn


def get_db_pool() -> Optional[AsyncConnectionPool]:
    """Get the database connection pool instance."""
    return _db_pool
