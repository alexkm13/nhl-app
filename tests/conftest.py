"""Pytest configuration and shared fixtures."""
import asyncio
import os
from unittest.mock import AsyncMock

import pytest

# Try to import FastAPI, but don't fail if it's not available
try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    TestClient = None

# Set test environment variables
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

# Try to import fakeredis, fallback to mock if not available
try:
    from fakeredis import FakeAsyncRedis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False
    FakeAsyncRedis = None


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def redis_client():
    """Create a fake Redis client for testing."""
    if HAS_FAKEREDIS:
        redis = FakeAsyncRedis()
        yield redis
        await redis.flushall()
        await redis.close()
    else:
        # Fallback to mock if fakeredis not available
        mock = AsyncMock()
        yield mock


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    if HAS_FAKEREDIS:
        return FakeAsyncRedis()
    else:
        return AsyncMock()

