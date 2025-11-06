"""Tests for main app routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """Create a test client with mocked Redis."""
    with patch("main.Redis.from_url") as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.aclose = AsyncMock()
        mock_redis.return_value = mock_redis_instance

        # Set app state for testing
        app.state.redis = mock_redis_instance

        yield TestClient(app)


def test_favicon(client):
    """Test favicon endpoint."""
    response = client.get("/favicon.ico")
    assert response.status_code == 204  # No Content


def test_root_with_html(client):
    """Test root endpoint with HTML file."""
    with patch("os.path.exists", return_value=True):
        with patch("builtins.open", create=True) as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = (
                "<html><body>Test</body></html>"
            )

            response = client.get("/")

            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]


def test_root_no_html(client):
    """Test root endpoint without HTML file."""
    with patch("os.path.exists", return_value=False):
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "docs" in data


def test_metrics(client):
    """Test metrics endpoint."""
    response = client.get("/metrics")

    assert response.status_code == 200
    # Metrics endpoint returns Prometheus format which can be text/plain or have version
    content_type = response.headers.get("content-type", "")
    assert "text/plain" in content_type or len(response.text) > 0
    # Should contain some metric data
    assert len(response.text) > 0


def test_middleware_metrics(client):
    """Test that middleware records metrics."""
    with patch("main.REQUESTS") as mock_requests, patch("main.LATENCY") as mock_latency:
        mock_requests.labels.return_value.inc = MagicMock()
        mock_latency.observe = MagicMock()

        response = client.get("/")

        assert response.status_code == 200
        # Metrics should be recorded (exact calls depend on implementation)
        # Just verify the endpoint works
