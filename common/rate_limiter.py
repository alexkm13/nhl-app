"""Rate limiting middleware for FastAPI applications."""

import time
from typing import Dict, Tuple
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from common.constants import (
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    HTTP_STATUS_SERVICE_UNAVAILABLE,
)


class RateLimiter:
    """
    Simple in-memory rate limiter using sliding window algorithm.

    Note: This is a basic implementation. For production use with multiple
    instances, consider using Redis-based rate limiting.
    """

    def __init__(
        self, max_requests: int = RATE_LIMIT_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS
    ):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, list[float]] = {}

    def is_allowed(self, client_id: str) -> Tuple[bool, Dict[str, any]]:
        """
        Check if request from client is allowed.

        Args:
            client_id: Unique client identifier (IP address, API key, etc.)

        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        now = time.time()
        window_start = now - self.window_seconds

        # Get or initialize request history for this client
        if client_id not in self.requests:
            self.requests[client_id] = []

        # Remove old requests outside the window
        self.requests[client_id] = [
            req_time for req_time in self.requests[client_id] if req_time > window_start
        ]

        current_count = len(self.requests[client_id])

        # Check if limit exceeded
        if current_count >= self.max_requests:
            oldest_request = self.requests[client_id][0]
            retry_after = int(oldest_request + self.window_seconds - now) + 1

            return False, {
                "limit": self.max_requests,
                "remaining": 0,
                "reset": int(oldest_request + self.window_seconds),
                "retry_after": retry_after,
            }

        # Add current request
        self.requests[client_id].append(now)

        return True, {
            "limit": self.max_requests,
            "remaining": self.max_requests - current_count - 1,
            "reset": int(now + self.window_seconds),
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting."""

    def __init__(self, app, max_requests: int = RATE_LIMIT_REQUESTS, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS):
        """
        Initialize rate limit middleware.

        Args:
            app: FastAPI application
            max_requests: Maximum requests allowed per window
            window_seconds: Time window in seconds
        """
        super().__init__(app)
        self.limiter = RateLimiter(max_requests, window_seconds)

    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        # Get client identifier (IP address)
        client_id = request.client.host if request.client else "unknown"

        # Check rate limit
        allowed, rate_info = self.limiter.is_allowed(client_id)

        if not allowed:
            raise HTTPException(
                status_code=HTTP_STATUS_SERVICE_UNAVAILABLE,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(rate_info["limit"]),
                    "X-RateLimit-Remaining": str(rate_info["remaining"]),
                    "X-RateLimit-Reset": str(rate_info["reset"]),
                    "Retry-After": str(rate_info["retry_after"]),
                },
            )

        # Add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rate_info["limit"])
        response.headers["X-RateLimit-Remaining"] = str(rate_info["remaining"])
        response.headers["X-RateLimit-Reset"] = str(rate_info["reset"])

        return response
