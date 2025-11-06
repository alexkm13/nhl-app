"""Integration tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

from services.gateway.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.mark.integration
class TestAPIIntegration:
    """Integration tests for API endpoints."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns valid response."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
    
    def test_metrics_endpoint(self, client):
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers.get("content-type", "")
        assert "gateway_requests_total" in response.text or "http_requests_total" in response.text
    
    @pytest.mark.slow
    def test_playbyplay_endpoint_structure(self, client):
        """Test play-by-play endpoint returns correct structure."""
        # This test requires a valid game ID - may fail if NHL API is unavailable
        # Use a known game ID or mock the API
        response = client.get("/v1/games/2025020161/playbyplay")
        # Accept both success and not found
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.json()
            assert "game_id" in data
            assert "events" in data
            assert isinstance(data["events"], list)

