"""API Key authentication middleware for FastAPI."""

import os
from typing import List, Optional

from fastapi import HTTPException, Request, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware to validate API keys for protected endpoints."""

    def __init__(self, app, enabled: bool = False, api_keys: Optional[List[str]] = None):
        """
        Initialize API key middleware.

        Args:
            app: FastAPI application
            enabled: Whether API key authentication is enabled
            api_keys: List of valid API keys
        """
        super().__init__(app)
        self.enabled = enabled
        self.api_keys = set(api_keys) if api_keys else set()
        # Public endpoints that don't require API keys
        self.public_paths = {
            "/",
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/static",
        }

    async def dispatch(self, request: Request, call_next):
        """Process request with API key validation."""
        # Skip authentication if disabled
        if not self.enabled:
            return await call_next(request)

        # Skip authentication for public paths
        path = request.url.path
        if any(path.startswith(public_path) for public_path in self.public_paths):
            return await call_next(request)

        # Extract API key from header
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key required. Provide X-API-Key header.",
            )

        if api_key not in self.api_keys:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid API key.",
            )

        # API key is valid, proceed with request
        response = await call_next(request)
        return response


def get_api_key_middleware_config() -> tuple[bool, List[str]]:
    """
    Get API key middleware configuration from environment variables.

    Returns:
        Tuple of (enabled, api_keys_list)
    """
    enabled = os.environ.get("API_KEY_ENABLED", "false").lower() == "true"
    api_keys_str = os.environ.get("API_KEYS", "")
    api_keys = [key.strip() for key in api_keys_str.split(",") if key.strip()] if api_keys_str else []

    return enabled, api_keys
