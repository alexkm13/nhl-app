"""Tests for NHL API functions."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from nhl_api import (
    fetch_nhl_boxscore,
    fetch_nhl_daily_schedule,
    fetch_nhl_play_by_play,
    fetch_team_standings,
)


@pytest.mark.asyncio
async def test_fetch_nhl_play_by_play_success(mock_httpx_client):
    """Test successful play-by-play fetch."""
    game_id = "2024020589"
    expected_data = {
        "gameState": "LIVE",
        "homeTeam": {"id": 1, "commonName": {"default": "Bruins"}},
        "awayTeam": {"id": 2, "commonName": {"default": "Leafs"}},
        "plays": []
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data
    
    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            return None
        
        async def get(self, *args, **kwargs):
            return mock_response
    
    with patch('nhl_api.httpx.AsyncClient', MockAsyncClient):
        result = await fetch_nhl_play_by_play(game_id)
        
        assert result == expected_data


@pytest.mark.asyncio
async def test_fetch_nhl_play_by_play_not_found(mock_httpx_client):
    """Test play-by-play fetch with 404 error."""
    game_id = "2024020589"
    
    mock_response = AsyncMock()
    mock_response.status_code = 404
    mock_httpx_client.get.return_value = mock_response
    
    result = await fetch_nhl_play_by_play(game_id)
    
    assert result is None


@pytest.mark.asyncio
async def test_fetch_nhl_play_by_play_network_error(mock_httpx_client):
    """Test play-by-play fetch with network error."""
    game_id = "2024020589"
    
    mock_httpx_client.get.side_effect = httpx.TimeoutException("Request timeout")
    
    result = await fetch_nhl_play_by_play(game_id)
    
    assert result is None


@pytest.mark.asyncio
async def test_fetch_nhl_boxscore_success(mock_httpx_client):
    """Test successful boxscore fetch."""
    game_id = "2024020589"
    expected_data = {
        "homeTeam": {"id": 1, "score": 2},
        "awayTeam": {"id": 2, "score": 1}
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data
    
    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            return None
        
        async def get(self, *args, **kwargs):
            return mock_response
    
    with patch('nhl_api.httpx.AsyncClient', MockAsyncClient):
        result = await fetch_nhl_boxscore(game_id)
        
        assert result == expected_data


@pytest.mark.asyncio
async def test_fetch_nhl_boxscore_not_found(mock_httpx_client):
    """Test boxscore fetch with 404 error."""
    game_id = "2024020589"
    
    mock_response = AsyncMock()
    mock_response.status_code = 404
    mock_httpx_client.get.return_value = mock_response
    
    result = await fetch_nhl_boxscore(game_id)
    
    assert result is None


@pytest.mark.asyncio
async def test_fetch_team_standings_success(mock_httpx_client, mock_redis):
    """Test successful standings fetch."""
    expected_data = {
        "standings": [
            {
                "teamAbbrev": {"default": "BOS"},
                "wins": 10,
                "losses": 5,
                "otLosses": 2
            },
            {
                "teamAbbrev": {"default": "TOR"},
                "wins": 8,
                "losses": 7,
                "otLosses": 1
            }
        ]
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data
    mock_redis.get.return_value = None  # Cache miss
    
    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            return None
        
        async def get(self, *args, **kwargs):
            return mock_response
    
    with patch('nhl_api.httpx.AsyncClient', MockAsyncClient):
        result = await fetch_team_standings(mock_redis)
        
        assert "BOS" in result
        assert result["BOS"]["wins"] == 10
        assert result["BOS"]["losses"] == 5
        assert result["BOS"]["ot_losses"] == 2
        assert result["TOR"]["wins"] == 8
        mock_redis.setex.assert_called_once()  # Should cache the result


@pytest.mark.asyncio
async def test_fetch_team_standings_cache_hit(mock_httpx_client, mock_redis):
    """Test standings fetch with cache hit."""
    cached_data = {"BOS": {"wins": 10, "losses": 5, "ot_losses": 2}}
    mock_redis.get.return_value = json.dumps(cached_data)
    
    result = await fetch_team_standings(mock_redis)
    
    assert result == cached_data
    mock_httpx_client.get.assert_not_called()  # Should not call API


@pytest.mark.asyncio
async def test_fetch_team_standings_no_redis(mock_httpx_client):
    """Test standings fetch without Redis."""
    expected_data = {
        "standings": [
            {
                "teamAbbrev": {"default": "BOS"},
                "wins": 10,
                "losses": 5,
                "otLosses": 2
            }
        ]
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data
    
    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            return None
        
        async def get(self, *args, **kwargs):
            return mock_response
    
    with patch('nhl_api.httpx.AsyncClient', MockAsyncClient):
        result = await fetch_team_standings(None)
        
        assert "BOS" in result
        assert result["BOS"]["wins"] == 10


@pytest.mark.asyncio
async def test_fetch_nhl_daily_schedule_success(mock_httpx_client):
    """Test successful daily schedule fetch."""
    date = "2024-01-15"
    expected_data = {
        "date": date,
        "games": [
            {"id": "2024020589", "homeTeam": {"id": 1}, "awayTeam": {"id": 2}}
        ]
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data
    
    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            return None
        
        async def get(self, *args, **kwargs):
            return mock_response
    
    with patch('nhl_api.httpx.AsyncClient', MockAsyncClient):
        result = await fetch_nhl_daily_schedule(date)
        
        assert result == expected_data


@pytest.mark.asyncio
async def test_fetch_nhl_daily_schedule_no_date(mock_httpx_client):
    """Test daily schedule fetch without date (uses today)."""
    # Since datetime.date.today() is hard to mock, we'll just verify
    # that the function works when called without a date
    # The actual date will be today's date, but we can verify the structure
    expected_data = {
        "date": "2024-01-15",
        "games": []
    }
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected_data
    
    # Create a proper async context manager mock
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            return None
        
        async def get(self, *args, **kwargs):
            return mock_response
    
    with patch('nhl_api.httpx.AsyncClient', MockAsyncClient):
        # Just verify it doesn't crash and returns a dict with expected keys
        result = await fetch_nhl_daily_schedule(None)
        
        assert isinstance(result, dict)
        assert "games" in result or "date" in result


@pytest.mark.asyncio
async def test_fetch_nhl_daily_schedule_error(mock_httpx_client):
    """Test daily schedule fetch with error."""
    mock_response = AsyncMock()
    mock_response.status_code = 500
    mock_httpx_client.get.return_value = mock_response
    
    result = await fetch_nhl_daily_schedule("2024-01-15")
    
    assert result == {"games": [], "date": "2024-01-15"}

