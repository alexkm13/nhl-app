"""Tests for standings routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


@pytest.mark.asyncio
async def test_get_standings_success(client, mock_httpx_client):
    """Test successful standings fetch."""
    expected_data = {
        "standings": [
            {
                "teamAbbrev": {"default": "BOS"},
                "teamName": {"default": "Boston Bruins"},
                "placeName": {"default": "Boston"},
                "commonName": {"default": "Bruins"},
                "wins": 10,
                "losses": 5,
                "otLosses": 2,
                "points": 22,
                "gamesPlayed": 17,
                "goalFor": 55,
                "goalAgainst": 40,
                "teamLogo": "https://example.com/bruins.png",
            },
            {
                "teamAbbrev": {"default": "TOR"},
                "teamName": {"default": "Toronto Maple Leafs"},
                "placeName": {"default": "Toronto"},
                "commonName": {"default": "Maple Leafs"},
                "wins": 8,
                "losses": 7,
                "otLosses": 1,
                "points": 17,
                "gamesPlayed": 16,
                "goalFor": 48,
                "goalAgainst": 45,
                "teamLogo": "https://example.com/leafs.png",
            },
        ]
    }

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data

    # Create a proper async context manager mock that works with FastAPI TestClient
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return mock_response

    with patch("routes.standings.httpx.AsyncClient", MockAsyncClient):
        response = client.get("/v1/standings")

        assert response.status_code == 200
        data = response.json()
        assert "standings" in data
        assert len(data["standings"]) == 2
        assert data["standings"][0]["abbreviation"] == "BOS"
        assert data["standings"][0]["wins"] == 10


@pytest.mark.asyncio
async def test_get_standings_api_error(client, mock_httpx_client):
    """Test standings fetch with API error."""
    mock_response = AsyncMock()
    mock_response.status_code = 500
    mock_httpx_client.get.return_value = mock_response

    with patch("routes.standings.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_httpx_client
        mock_client.__aexit__.return_value = None
        mock_client_class.return_value = mock_client

        response = client.get("/v1/standings")

        assert response.status_code == 500


@pytest.mark.asyncio
async def test_get_standings_network_error(client):
    """Test standings fetch with network error."""
    with patch("routes.standings.httpx.AsyncClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.side_effect = httpx.TimeoutException("Timeout")
        mock_client_class.return_value = mock_client

        response = client.get("/v1/standings")

        assert response.status_code == 500


@pytest.mark.asyncio
async def test_get_standings_empty_response(client, mock_httpx_client):
    """Test standings fetch with empty response."""
    expected_data = {"standings": []}

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data

    # Create a proper async context manager mock that works with FastAPI TestClient
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return mock_response

    with patch("routes.standings.httpx.AsyncClient", MockAsyncClient):
        response = client.get("/v1/standings")

        assert response.status_code == 200
        data = response.json()
        assert "standings" in data
        assert len(data["standings"]) == 0
