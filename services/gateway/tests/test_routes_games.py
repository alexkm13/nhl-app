"""Tests for game routes."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """Create a test client with mocked Redis."""
    with patch('main.Redis.from_url') as mock_redis:
        mock_redis_instance = AsyncMock()
        mock_redis_instance.aclose = AsyncMock()
        mock_redis_instance.get = AsyncMock(return_value=None)
        mock_redis_instance.hget = AsyncMock(return_value=None)
        mock_redis_instance.hgetall = AsyncMock(return_value={})
        mock_redis_instance.setex = AsyncMock(return_value=True)
        mock_redis_instance.hset = AsyncMock(return_value=True)
        mock_redis_instance.delete = AsyncMock(return_value=True)
        mock_redis.return_value = mock_redis_instance
        
        # Set app state for testing
        app.state.redis = mock_redis_instance
        
        yield TestClient(app)


@pytest.mark.asyncio
async def test_list_games_success(client, sample_game_data, mock_redis):
    """Test successful game list fetch."""
    schedule_data = {
        "date": "2024-01-15",
        "games": [
            {
                "id": "2024020589",
                "gameState": "LIVE",
                "startTimeUTC": "2024-01-15T19:00:00Z",
                "homeTeam": {
                    "id": 1,
                    "commonName": {"default": "Bruins"},
                    "abbrev": "BOS",
                    "logo": "https://example.com/bruins.png",
                    "score": 2
                },
                "awayTeam": {
                    "id": 2,
                    "commonName": {"default": "Leafs"},
                    "abbrev": "TOR",
                    "logo": "https://example.com/leafs.png",
                    "score": 1
                },
                "periodDescriptor": {
                    "number": 2,
                    "timeRemaining": "15:00"
                }
            }
        ]
    }
    
    standings_data = {
        "BOS": {"wins": 10, "losses": 5, "ot_losses": 2},
        "TOR": {"wins": 8, "losses": 7, "ot_losses": 1}
    }
    
    with patch('routes.games.fetch_nhl_daily_schedule') as mock_schedule, \
         patch('routes.games.fetch_team_standings') as mock_standings:
        mock_schedule.return_value = schedule_data
        mock_standings.return_value = standings_data
        
        response = client.get("/v1/games")
        
        assert response.status_code == 200
        data = response.json()
        assert "games" in data
        assert len(data["games"]) == 1
        assert data["games"][0]["game_id"] == "2024020589"
        assert data["games"][0]["home_team"] == "BOS"


@pytest.mark.asyncio
async def test_list_games_with_date(client, mock_redis):
    """Test game list fetch with specific date."""
    schedule_data = {
        "date": "2024-01-15",
        "games": []
    }
    
    with patch('routes.games.fetch_nhl_daily_schedule') as mock_schedule, \
         patch('routes.games.fetch_team_standings') as mock_standings:
        mock_schedule.return_value = schedule_data
        mock_standings.return_value = {}
        
        response = client.get("/v1/games?date=2024-01-15")
        
        assert response.status_code == 200
        data = response.json()
        assert "games" in data
        mock_schedule.assert_called_once()


@pytest.mark.asyncio
async def test_start_game_ingestion_success(client, sample_game_data, mock_redis):
    """Test successful game ingestion start."""
    game_id = "2024020589"
    
    with patch('routes.games.fetch_nhl_play_by_play') as mock_fetch:
        mock_fetch.return_value = sample_game_data
        mock_redis.hget.return_value = None  # Not in progress
        
        response = client.post(f"/v1/games/{game_id}/start")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "started"
        assert data["game_id"] == game_id


@pytest.mark.asyncio
async def test_start_game_ingestion_already_in_progress(client, sample_game_data):
    """Test game ingestion start when already in progress."""
    game_id = "2024020589"
    
    with patch('routes.games.fetch_nhl_play_by_play') as mock_fetch:
        mock_fetch.return_value = sample_game_data
        # Mock Redis to return "in_progress" status
        app.state.redis.hget = AsyncMock(return_value="in_progress")
        
        response = client.post(f"/v1/games/{game_id}/start")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"


@pytest.mark.asyncio
async def test_start_game_ingestion_not_found(client):
    """Test game ingestion start with non-existent game."""
    game_id = "9999999999"
    
    with patch('routes.games.fetch_nhl_play_by_play') as mock_fetch:
        mock_fetch.return_value = None
        
        response = client.post(f"/v1/games/{game_id}/start")
        
        # Should return 404 or 500 depending on implementation
        assert response.status_code in [404, 500]


@pytest.mark.asyncio
async def test_get_game_status(client):
    """Test getting game status."""
    game_id = "2024020589"
    
    # Mock hgetall to return different values based on key
    async def mock_hgetall(key):
        if key == f"ingestion_status:{game_id}":
            return {"status": "completed", "matchup": "Leafs @ Bruins"}
        elif key == f"pred:{game_id}":
            return {"p_home_win": "0.75", "model_id": "test_model"}
        elif key == f"state:{game_id}":
            return {"home_score": "2", "away_score": "1"}
        return {}
    
    app.state.redis.hgetall = AsyncMock(side_effect=mock_hgetall)
    
    response = client.get(f"/v1/games/{game_id}/status")
    
    assert response.status_code == 200
    data = response.json()
    assert "ingestion_status" in data
    assert data["has_prediction"] is True


@pytest.mark.asyncio
async def test_get_winprob_success(client):
    """Test successful win probability fetch."""
    game_id = "2024020589"
    
    app.state.redis.hgetall = AsyncMock(return_value={
        "game_id": game_id,
        "p_home_win": "0.75",
        "model_id": "lightgbm_20251104_121934_d9b5b03f",
        "ts": "1705358400.0"
    })
    
    response = client.get(f"/v1/games/{game_id}/winprob")
    
    assert response.status_code == 200
    data = response.json()
    assert data["game_id"] == game_id
    assert data["p_home_win"] == 0.75
    assert data["model_id"] == "lightgbm_20251104_121934_d9b5b03f"


@pytest.mark.asyncio
async def test_get_winprob_not_found(client, mock_redis):
    """Test win probability fetch with no prediction."""
    game_id = "2024020589"
    
    mock_redis.hgetall.return_value = {}
    mock_redis.hget.return_value = None
    
    response = client.get(f"/v1/games/{game_id}/winprob")
    
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_winprob_in_progress(client):
    """Test win probability fetch with ingestion in progress."""
    game_id = "2024020589"
    
    app.state.redis.hgetall = AsyncMock(return_value={})
    app.state.redis.hget = AsyncMock(return_value="in_progress")
    
    response = client.get(f"/v1/games/{game_id}/winprob")
    
    assert response.status_code == 202  # Accepted


@pytest.mark.asyncio
async def test_get_game_rosters_success(client, sample_boxscore_data, mock_redis):
    """Test successful roster fetch."""
    game_id = "2024020589"
    
    with patch('routes.games.fetch_nhl_boxscore') as mock_boxscore:
        mock_boxscore.return_value = sample_boxscore_data
        
        response = client.get(f"/v1/games/{game_id}/rosters")
        
        assert response.status_code == 200
        data = response.json()
        assert "home_team" in data
        assert "away_team" in data
        assert "roster" in data["home_team"]
        assert len(data["home_team"]["roster"]) > 0


@pytest.mark.asyncio
async def test_get_game_rosters_not_found(client):
    """Test roster fetch with non-existent game."""
    game_id = "9999999999"
    
    with patch('routes.games.fetch_nhl_boxscore') as mock_boxscore:
        mock_boxscore.return_value = None
        
        response = client.get(f"/v1/games/{game_id}/rosters")
        
        # Should return 404 or 500 depending on implementation
        assert response.status_code in [404, 500]

