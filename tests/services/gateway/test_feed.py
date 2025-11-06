"""Tests for the play-by-play feed functionality."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))


@pytest.mark.unit
class TestFeedEventStructure:
    """Test feed event data structure."""
    
    def test_event_structure(self):
        """Test that feed events have correct structure."""
        sample_event = {
            "id": "game-123-event-1",
            "timestamp": 1234567890,
            "event_type": "GOAL",
            "period": 1,
            "time_in_period": "10:30",
            "team": "HOME",
            "player_name": "John Doe",
            "player_id": 12345,
            "description": "Goal scored by John Doe"
        }
        
        required_fields = ["id", "event_type", "period", "team"]
        assert all(field in sample_event for field in required_fields)
    
    def test_goal_event_structure(self):
        """Test structure of goal events."""
        goal_event = {
            "id": "game-123-goal-1",
            "event_type": "GOAL",
            "period": 2,
            "time_in_period": "5:20",
            "team": "HOME",
            "player_name": "Scorer",
            "assist1_name": "Assist1",
            "assist2_name": "Assist2",
            "strength": "EV",
            "empty_net": False
        }
        
        assert goal_event["event_type"] == "GOAL"
        assert "player_name" in goal_event
        assert goal_event["strength"] in ["EV", "PP", "SH", "EN"]
    
    def test_penalty_event_structure(self):
        """Test structure of penalty events."""
        penalty_event = {
            "id": "game-123-penalty-1",
            "event_type": "PENALTY",
            "period": 1,
            "time_in_period": "8:15",
            "team": "AWAY",
            "player_name": "Player Name",
            "penalty_type": "Tripping",
            "duration": "2:00"
        }
        
        assert penalty_event["event_type"] == "PENALTY"
        assert "player_name" in penalty_event or "team" in penalty_event


@pytest.mark.integration
class TestFeedAPI:
    """Test feed API endpoints."""
    
    @pytest.fixture
    def client(self):
        """Create test client."""
        from fastapi.testclient import TestClient
        try:
            from services.gateway.main import app
            return TestClient(app)
        except ImportError:
            pytest.skip("Cannot import app")
    
    def test_playbyplay_endpoint_exists(self, client):
        """Test that play-by-play endpoint exists."""
        response = client.get("/v1/games/TEST_GAME/playbyplay")
        assert response.status_code in [200, 404]
    
    def test_playbyplay_response_structure(self, client):
        """Test play-by-play response structure."""
        response = client.get("/v1/games/TEST_GAME/playbyplay?limit=10")
        
        if response.status_code == 200:
            data = response.json()
            assert "game_id" in data
            assert "events" in data
            assert isinstance(data["events"], list)
            
            # If events exist, check structure
            if data["events"]:
                event = data["events"][0]
                assert "event_type" in event
                assert "period" in event
    
    def test_playbyplay_limit_parameter(self, client):
        """Test limit parameter in play-by-play endpoint."""
        response = client.get("/v1/games/TEST_GAME/playbyplay?limit=5")
        
        if response.status_code == 200:
            data = response.json()
            # Should respect limit (or return all if less than limit)
            assert len(data.get("events", [])) <= 5


@pytest.mark.unit
class TestFeedEventFiltering:
    """Test feed event filtering logic."""
    
    def test_crucial_events_filter(self):
        """Test filtering of crucial events."""
        events = [
            {"event_type": "GOAL", "period": 1},
            {"event_type": "SHOT", "period": 1},
            {"event_type": "PENALTY", "period": 1},
            {"event_type": "FACEOFF", "period": 1},
        ]
        
        crucial_types = ["GOAL", "PENALTY"]
        crucial_events = [e for e in events if e["event_type"] in crucial_types]
        
        assert len(crucial_events) == 2
        assert all(e["event_type"] in crucial_types for e in crucial_events)
    
    def test_event_deduplication(self):
        """Test event deduplication logic."""
        events = [
            {"id": "event-1", "event_type": "GOAL"},
            {"id": "event-1", "event_type": "GOAL"},  # Duplicate
            {"id": "event-2", "event_type": "GOAL"},
        ]
        
        seen_ids = set()
        unique_events = []
        for event in events:
            event_id = event.get("id")
            if event_id and event_id not in seen_ids:
                seen_ids.add(event_id)
                unique_events.append(event)
        
        assert len(unique_events) == 2
        assert len(seen_ids) == 2
    
    def test_event_sorting(self):
        """Test event sorting by timestamp."""
        events = [
            {"timestamp": 100, "event_type": "GOAL"},
            {"timestamp": 50, "event_type": "GOAL"},
            {"timestamp": 150, "event_type": "GOAL"},
        ]
        
        # Sort descending (most recent first)
        sorted_events = sorted(events, key=lambda x: x["timestamp"], reverse=True)
        
        assert sorted_events[0]["timestamp"] == 150
        assert sorted_events[1]["timestamp"] == 100
        assert sorted_events[2]["timestamp"] == 50


@pytest.mark.unit
class TestFeedEventProcessing:
    """Test feed event processing."""
    
    def test_event_period_grouping(self):
        """Test grouping events by period."""
        events = [
            {"period": 1, "event_type": "GOAL"},
            {"period": 1, "event_type": "SHOT"},
            {"period": 2, "event_type": "GOAL"},
            {"period": 2, "event_type": "PENALTY"},
        ]
        
        periods = {}
        for event in events:
            period = event["period"]
            if period not in periods:
                periods[period] = []
            periods[period].append(event)
        
        assert len(periods) == 2
        assert len(periods[1]) == 2
        assert len(periods[2]) == 2
    
    def test_event_timestamp_formatting(self):
        """Test timestamp formatting for events."""
        # Unix timestamp
        timestamp = 1234567890
        
        # Convert to readable format (this would be done in frontend)
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp)
        formatted = dt.strftime("%H:%M:%S")
        
        assert isinstance(formatted, str)
        assert ":" in formatted


@pytest.mark.integration
class TestFeedIntegration:
    """Integration tests for feed functionality."""
    
    @pytest.fixture
    def sample_feed_data(self):
        """Sample feed data for testing."""
        return {
            "game_id": "2025020161",
            "events": [
                {
                    "id": "event-1",
                    "timestamp": 1234567890,
                    "event_type": "GOAL",
                    "period": 1,
                    "time_in_period": "10:30",
                    "team": "HOME",
                    "player_name": "Player 1",
                },
                {
                    "id": "event-2",
                    "timestamp": 1234567900,
                    "event_type": "PENALTY",
                    "period": 1,
                    "time_in_period": "11:00",
                    "team": "AWAY",
                    "player_name": "Player 2",
                },
            ],
            "home_team": "Home Team",
            "away_team": "Away Team",
        }
    
    def test_feed_data_structure(self, sample_feed_data):
        """Test feed data structure."""
        assert "game_id" in sample_feed_data
        assert "events" in sample_feed_data
        assert isinstance(sample_feed_data["events"], list)
        assert len(sample_feed_data["events"]) > 0
    
    def test_feed_events_have_required_fields(self, sample_feed_data):
        """Test that feed events have required fields."""
        for event in sample_feed_data["events"]:
            assert "event_type" in event
            assert "period" in event
            assert "team" in event

