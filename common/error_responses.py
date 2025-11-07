"""Standardized error response formats for API endpoints."""

from typing import Optional, Dict, Any
from pydantic import BaseModel

from common.constants import (
    HTTP_STATUS_BAD_REQUEST,
    HTTP_STATUS_NOT_FOUND,
    HTTP_STATUS_INTERNAL_SERVER_ERROR,
    HTTP_STATUS_SERVICE_UNAVAILABLE,
)


class ErrorResponse(BaseModel):
    """Standard error response model."""

    error: str
    message: str
    status_code: int
    details: Optional[Dict[str, Any]] = None


def create_error_response(
    error: str,
    message: str,
    status_code: int,
    details: Optional[Dict[str, Any]] = None,
) -> ErrorResponse:
    """
    Create a standardized error response.

    Args:
        error: Error type/category
        message: Human-readable error message
        status_code: HTTP status code
        details: Optional additional error details

    Returns:
        ErrorResponse object
    """
    return ErrorResponse(
        error=error, message=message, status_code=status_code, details=details
    )


def bad_request_error(message: str, details: Optional[Dict[str, Any]] = None) -> ErrorResponse:
    """Create a 400 Bad Request error response."""
    return create_error_response("BadRequest", message, HTTP_STATUS_BAD_REQUEST, details)


def not_found_error(message: str, details: Optional[Dict[str, Any]] = None) -> ErrorResponse:
    """Create a 404 Not Found error response."""
    return create_error_response("NotFound", message, HTTP_STATUS_NOT_FOUND, details)


def internal_server_error(
    message: str = "Internal server error", details: Optional[Dict[str, Any]] = None
) -> ErrorResponse:
    """Create a 500 Internal Server Error response."""
    return create_error_response(
        "InternalServerError", message, HTTP_STATUS_INTERNAL_SERVER_ERROR, details
    )


def service_unavailable_error(
    message: str = "Service temporarily unavailable",
    details: Optional[Dict[str, Any]] = None,
) -> ErrorResponse:
    """Create a 503 Service Unavailable error response."""
    return create_error_response(
        "ServiceUnavailable", message, HTTP_STATUS_SERVICE_UNAVAILABLE, details
    )
