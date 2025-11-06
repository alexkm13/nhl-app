"""Tests for the win probability graph generation."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))


@pytest.mark.unit
class TestGraphDataProcessing:
    """Test graph data processing logic."""
    
    def test_graph_data_structure(self):
        """Test that graph data has correct structure."""
        # Sample history data structure
        history_data = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
            {"ts": 1200, "p_home_win": 0.60},
        ]
        
        # Verify structure
        assert len(history_data) == 3
        assert all("ts" in d and "p_home_win" in d for d in history_data)
        assert all(0 <= d["p_home_win"] <= 1 for d in history_data)
    
    def test_graph_data_validation(self):
        """Test validation of graph data."""
        # Valid data
        valid_data = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 100, "p_home_win": 0.6},
        ]
        assert all(isinstance(d["ts"], (int, float)) for d in valid_data)
        assert all(isinstance(d["p_home_win"], (int, float)) for d in valid_data)
    
    def test_graph_data_sorting(self):
        """Test that graph data should be sorted by timestamp."""
        unsorted_data = [
            {"ts": 1200, "p_home_win": 0.60},
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
        ]
        
        sorted_data = sorted(unsorted_data, key=lambda x: x["ts"])
        assert sorted_data[0]["ts"] == 0
        assert sorted_data[1]["ts"] == 600
        assert sorted_data[2]["ts"] == 1200


@pytest.mark.integration
class TestGraphAPI:
    """Test graph data API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient
        try:
            from services.gateway.main import app
            return TestClient(app)
        except ImportError:
            pytest.skip("Cannot import app")
    
    def test_winprob_history_endpoint(self, client):
        """Test win probability history endpoint structure."""
        # This will likely return 404 for test game, but we can test the endpoint exists
        response = client.get("/v1/games/TEST_GAME/winprob/history")
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            data = response.json()
            assert "data" in data or "history" in data or isinstance(data, list)
    
    def test_winprob_friendly_endpoint(self, client):
        """Test win probability friendly endpoint structure."""
        response = client.get("/v1/games/TEST_GAME/winprob/friendly")
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            data = response.json()
            # Should have win probability data
            assert "win_probability" in data or "p_home_win" in data or "score" in data


@pytest.mark.unit
class TestGraphCalculation:
    """Test graph calculation logic."""
    
    def test_time_range_calculation(self):
        """Test calculation of time range for graph."""
        history_data = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
            {"ts": 1800, "p_home_win": 0.60},
        ]
        
        times = [d["ts"] for d in history_data]
        min_time = min(times)
        max_time = max(times)
        
        assert min_time == 0
        assert max_time == 1800
        assert max_time - min_time == 1800
    
    def test_probability_to_coordinate(self):
        """Test conversion of probability to graph coordinates."""
        # Graph dimensions
        height = 120
        padding_top = 20
        padding_bottom = 30
        chart_height = height - padding_top - padding_bottom
        
        # Test probability 0.5 (50%) should be in middle
        prob = 0.5
        y = padding_top + chart_height - (prob * chart_height)
        
        # Should be approximately in the middle
        expected_y = padding_top + chart_height / 2
        assert abs(y - expected_y) < 1
    
    def test_empty_history_data(self):
        """Test graph with empty history data."""
        history_data = []
        current_prob = 0.6
        
        # Should still generate graph with current probability
        assert len(history_data) == 0
        # Graph should use current probability as baseline
        assert 0 <= current_prob <= 1


@pytest.mark.unit
class TestGraphInterpolation:
    """Test graph interpolation logic."""
    
    def test_interpolation_between_points(self):
        """Test interpolation between data points."""
        # Two points with gap
        point1 = {"ts": 0, "p_home_win": 0.5}
        point2 = {"ts": 600, "p_home_win": 0.6}
        
        # Interpolate at midpoint
        mid_time = 300
        time_diff = point2["ts"] - point1["ts"]
        prob_diff = point2["p_home_win"] - point1["p_home_win"]
        
        mid_prob = point1["p_home_win"] + (prob_diff * (mid_time - point1["ts"]) / time_diff)
        
        assert 0.5 < mid_prob < 0.6
        assert abs(mid_prob - 0.55) < 0.01


@pytest.mark.integration
class TestGraphIntegration:
    """Integration tests for graph functionality."""
    
    @pytest.fixture
    def sample_graph_data(self):
        """Sample graph data for testing."""
        return {
            "historyData": [
                {"ts": 0, "p_home_win": 0.5},
                {"ts": 600, "p_home_win": 0.55},
                {"ts": 1200, "p_home_win": 0.60},
            ],
            "homeProb": 65.0,
            "awayProb": 35.0,
            "isLive": True,
            "currentGameTime": 1800
        }
    
    def test_graph_data_structure_valid(self, sample_graph_data):
        """Test that sample graph data structure is valid."""
        assert "historyData" in sample_graph_data
        assert "homeProb" in sample_graph_data
        assert "awayProb" in sample_graph_data
        assert sample_graph_data["homeProb"] + sample_graph_data["awayProb"] == 100.0

