"""Health check utilities for all services."""

from typing import Dict, Any, Optional
from datetime import datetime
import asyncio

from redis.asyncio import Redis
import psycopg

from common.constants import HEALTH_CHECK_TIMEOUT_SECONDS


async def check_redis_health(redis_url: str) -> Dict[str, Any]:
    """
    Check Redis connection health.

    Args:
        redis_url: Redis connection URL

    Returns:
        Health status dictionary
    """
    try:
        redis = Redis.from_url(redis_url, decode_responses=True)
        await asyncio.wait_for(redis.ping(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        await redis.aclose()
        return {"status": "healthy", "service": "redis"}
    except asyncio.TimeoutError:
        return {"status": "unhealthy", "service": "redis", "error": "timeout"}
    except Exception as e:
        return {"status": "unhealthy", "service": "redis", "error": str(e)}


async def check_database_health(database_url: str) -> Dict[str, Any]:
    """
    Check PostgreSQL database connection health.

    Args:
        database_url: Database connection URL

    Returns:
        Health status dictionary
    """
    if not database_url:
        return {"status": "disabled", "service": "database"}

    try:
        conn = await asyncio.wait_for(
            psycopg.AsyncConnection.connect(database_url),
            timeout=HEALTH_CHECK_TIMEOUT_SECONDS,
        )
        await conn.close()
        return {"status": "healthy", "service": "database"}
    except asyncio.TimeoutError:
        return {"status": "unhealthy", "service": "database", "error": "timeout"}
    except Exception as e:
        return {"status": "unhealthy", "service": "database", "error": str(e)}


def create_health_response(
    service_name: str,
    version: str = "1.0.0",
    redis_status: Optional[Dict[str, Any]] = None,
    database_status: Optional[Dict[str, Any]] = None,
    additional_checks: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Create a standardized health check response.

    Args:
        service_name: Name of the service
        version: Service version
        redis_status: Redis health check result
        database_status: Database health check result
        additional_checks: Additional service-specific health checks

    Returns:
        Standardized health response dictionary
    """
    checks = {}

    if redis_status:
        checks["redis"] = redis_status

    if database_status:
        checks["database"] = database_status

    if additional_checks:
        checks.update(additional_checks)

    # Overall status is healthy only if all checks are healthy or disabled
    all_healthy = all(
        check["status"] in ["healthy", "disabled"] for check in checks.values()
    )

    return {
        "service": service_name,
        "version": version,
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
    }
