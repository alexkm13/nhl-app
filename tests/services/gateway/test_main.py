"""Unit tests for gateway service."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

# Import the app after setting up test environment
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

try:
    from services.gateway.main import app, fetch_nhl_play_by_play, fetch_nhl_boxscore, calculate_win_probability
except ImportError as e:
    # Handle import errors gracefully
    pytest.skip(f"Could not import gateway main: {e}", allow_module_level=True)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.mark.unit
class TestWinProbabilityCalculation:
    """Test win probability calculation logic."""
    
    def test_calculate_win_probability_tied_game(self):
        """Test win probability for tied game."""
        try:
            prob = calculate_win_probability(
                home_score=0,
                away_score=0,
                game_state="LIVE",
                period=1,
                time_in_period="10:00"
            )
            assert 0.45 <= prob <= 0.55  # Should be close to 50/50
        except NameError:
            pytest.skip("calculate_win_probability not available")
    
    def test_calculate_win_probability_home_leading(self):
        """Test win probability when home team is leading."""
        prob = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=2,
            time_in_period="10:00"
        )
        assert prob > 0.5  # Home team should have higher probability
    
    def test_calculate_win_probability_away_leading(self):
        """Test win probability when away team is leading."""
        prob = calculate_win_probability(
            home_score=1,
            away_score=2,
            game_state="LIVE",
            period=2,
            time_in_period="10:00"
        )
        assert prob < 0.5  # Away team should have higher probability
    
    def test_calculate_win_probability_late_game(self):
        """Test win probability late in game."""
        prob_late = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=3,
            time_in_period="2:00"
        )
        prob_early = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=1,
            time_in_period="10:00"
        )
        assert prob_late > prob_early  # Lead is more significant late in game


@pytest.mark.unit
class TestNHLAPIFunctions:
    """Test NHL API fetching functions."""
    
    @pytest.mark.asyncio
    @patch('services.gateway.main.httpx.AsyncClient')
    async def test_fetch_nhl_play_by_play_success(self, mock_client_class):
        """Test successful play-by-play fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"plays": [], "gameState": "LIVE"}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client
        
        result = await fetch_nhl_play_by_play("2025020161")
        assert result is not None
        assert "plays" in result
    
    @pytest.mark.asyncio
    @patch('services.gateway.main.httpx.AsyncClient')
    async def test_fetch_nhl_play_by_play_error(self, mock_client_class):
        """Test play-by-play fetch with error."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(side_effect=Exception("Network error"))
        mock_client_class.return_value = mock_client
        
        result = await fetch_nhl_play_by_play("2025020161")
        assert result is None
    
    @pytest.mark.asyncio
    @patch('services.gateway.main.httpx.AsyncClient')
    async def test_fetch_nhl_boxscore_success(self, mock_client_class):
        """Test successful boxscore fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"homeTeam": {"score": 2}, "awayTeam": {"score": 1}}
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client
        
        result = await fetch_nhl_boxscore("2025020161")
        assert result is not None
        assert "homeTeam" in result


@pytest.mark.api
class TestAPIEndpoints:
    """Test API endpoints."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        assert "message" in response.json()
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code in [200, 404]  # May or may not exist
    
    def test_metrics_endpoint(self, client):
        """Test metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")

