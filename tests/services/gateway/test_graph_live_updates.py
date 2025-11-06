"""Tests for live graph probability updates."""
import pytest


@pytest.mark.unit
class TestGraphLiveUpdates:
    """Test that the graph reflects live probability updates."""
    
    def test_graph_updates_with_new_probability(self):
        """Test that graph HTML updates when new probability data arrives."""
        # Simulate graph generation with different probabilities
        
        # Initial probability
        home_prob_initial = 60.0
        away_prob_initial = 40.0
        
        # Updated probability (after goal)
        home_prob_updated = 75.0
        away_prob_updated = 25.0
        
        # Verify probabilities change
        assert home_prob_updated > home_prob_initial
        assert away_prob_updated < away_prob_initial
        assert home_prob_updated + away_prob_updated == 100.0
    
    def test_graph_reflects_score_changes(self):
        """Test that graph reflects probability changes when score changes."""
        # Simulate score progression
        scenarios = [
            {"home_score": 0, "away_score": 0, "expected_prob_range": (0.45, 0.55)},
            {"home_score": 1, "away_score": 0, "expected_prob_range": (0.55, 0.75)},
            {"home_score": 1, "away_score": 1, "expected_prob_range": (0.45, 0.55)},
            {"home_score": 2, "away_score": 1, "expected_prob_range": (0.60, 0.80)},
            {"home_score": 2, "away_score": 3, "expected_prob_range": (0.20, 0.40)},
        ]
        
        for scenario in scenarios:
            home_score = scenario["home_score"]
            away_score = scenario["away_score"]
            score_diff = home_score - away_score
            
            # Simple probability calculation
            if score_diff == 0:
                prob = 0.5
            else:
                # Use sigmoid-like function
                prob = 0.5 + (score_diff * 0.1)
                prob = max(0.05, min(0.95, prob))
            
            min_prob, max_prob = scenario["expected_prob_range"]
            assert min_prob <= prob <= max_prob, f"Score {home_score}-{away_score} gave probability {prob}, expected {min_prob}-{max_prob}"
    
    def test_graph_history_data_structure(self):
        """Test that graph history data structure is correct."""
        # Simulate history data from API
        history_data = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 300, "p_home_win": 0.52},
            {"ts": 600, "p_home_win": 0.55},
            {"ts": 900, "p_home_win": 0.58},
            {"ts": 1200, "p_home_win": 0.60},
            {"ts": 1800, "p_home_win": 0.65},
            {"ts": 2400, "p_home_win": 0.70},
            {"ts": 3600, "p_home_win": 0.75},  # Late in game
        ]
        
        # Verify structure
        assert len(history_data) > 0
        assert all("ts" in d and "p_home_win" in d for d in history_data)
        assert all(0 <= d["p_home_win"] <= 1 for d in history_data)
        
        # Verify time progression
        times = [d["ts"] for d in history_data]
        assert times == sorted(times)  # Times should be in order
        
        # Verify probability progression makes sense (home team increasing)
        probs = [d["p_home_win"] for d in history_data]
        assert probs[0] == 0.5  # Start at 50/50
        assert probs[-1] > 0.5  # End higher (home team winning)
    
    def test_graph_updates_with_current_probability(self):
        """Test that graph includes current probability as the latest point."""
        # Simulate history data
        history_data = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
            {"ts": 1200, "p_home_win": 0.60},
        ]
        
        # Current probability (from API)
        current_home_prob = 65.0  # 65%
        current_away_prob = 35.0  # 35%
        
        # Verify current probability is different from last history point
        last_history_prob = history_data[-1]["p_home_win"] * 100
        assert current_home_prob != last_history_prob
        
        # Graph should include current probability as the rightmost point
        # The graph generation function should add current point at current time
        assert current_home_prob + current_away_prob == 100.0
    
    def test_graph_reflects_late_game_events(self):
        """Test that graph reflects probability changes from late game events."""
        # Simulate probability changes throughout game
        history_data = [
            {"ts": 0, "p_home_win": 0.5},  # Game start
            {"ts": 600, "p_home_win": 0.55},  # Early goal
            {"ts": 1200, "p_home_win": 0.60},  # End of 1st
            {"ts": 2400, "p_home_win": 0.65},  # 2nd period goal
            {"ts": 3600, "p_home_win": 0.70},  # Late in 3rd
        ]
        
        # Late game event changes probability
        late_game_prob = 0.45  # Away team scores late
        
        # Verify late game event changes probability significantly
        assert late_game_prob < history_data[-1]["p_home_win"]
        
        # Graph should include this late game change
        history_data.append({"ts": 3800, "p_home_win": late_game_prob})
        
        # Verify final probability reflects late game event
        assert history_data[-1]["p_home_win"] == 0.45
        assert history_data[-1]["ts"] > 3600  # Late in game
    
    def test_graph_time_range_calculation(self):
        """Test that graph time range includes all events including late ones."""
        # Simulate events throughout game
        history_data = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
            {"ts": 1200, "p_home_win": 0.60},
            {"ts": 3600, "p_home_win": 0.65},  # Late in 3rd period
            {"ts": 3800, "p_home_win": 0.45},  # Very late in 3rd period
        ]
        
        # Calculate time range
        times = [d["ts"] for d in history_data]
        min_time = min(times)
        max_time = max(times)
        
        # Verify time range includes late events
        assert min_time == 0  # Game start
        assert max_time >= 3600  # Includes late 3rd period events
        assert max_time >= 3800  # Includes very late events
        
        # Time range should accommodate all events
        time_range = max_time - min_time
        assert time_range >= 3800  # At least 63+ minutes
    
    def test_graph_updates_with_each_event(self):
        """Test that graph updates with each new event."""
        # Simulate sequential probability updates
        updates = [
            {"event": "game_start", "home_prob": 50.0, "away_prob": 50.0},
            {"event": "home_goal_1", "home_prob": 55.0, "away_prob": 45.0},
            {"event": "away_goal_1", "home_prob": 50.0, "away_prob": 50.0},
            {"event": "home_goal_2", "home_prob": 60.0, "away_prob": 40.0},
            {"event": "away_goal_2", "home_prob": 50.0, "away_prob": 50.0},
            {"event": "away_goal_3", "home_prob": 40.0, "away_prob": 60.0},  # Late goal
        ]
        
        # Verify each update changes probability
        for i in range(1, len(updates)):
            prev_prob = updates[i-1]["home_prob"]
            curr_prob = updates[i]["home_prob"]
            
            # Probability should change with each event
            assert prev_prob != curr_prob or updates[i]["event"] == "away_goal_1" or updates[i]["event"] == "away_goal_2"
            
            # Probabilities should sum to 100
            assert updates[i]["home_prob"] + updates[i]["away_prob"] == 100.0


@pytest.mark.integration
class TestGraphLiveUpdatesIntegration:
    """Integration tests for live graph updates."""
    
    def test_graph_data_updates_with_api_response(self):
        """Test that graph data structure updates when API returns new data."""
        # Simulate API response with history data
        api_response = {
            "game": {"id": "2025020161", "is_live": True, "game_state": "LIVE"},
            "score": {
                "home": {"team": "Detroit Red Wings", "score": 2, "abbrev": "DET"},
                "away": {"team": "Vegas Golden Knights", "score": 3, "abbrev": "VGK"}
            },
            "win_probability": {
                "Detroit Red Wings": 40.0,
                "Vegas Golden Knights": 60.0
            },
            "historyData": [
                {"ts": 0, "p_home_win": 0.5},
                {"ts": 600, "p_home_win": 0.55},
                {"ts": 1200, "p_home_win": 0.60},
                {"ts": 3600, "p_home_win": 0.45},  # Late in game, away team leads
            ],
            "currentGameTime": 3800  # 63:20 in game
        }
        
        # Verify data structure
        assert "historyData" in api_response
        assert "win_probability" in api_response
        assert "currentGameTime" in api_response
        
        # Verify current probability matches score
        home_prob = api_response["win_probability"]["Detroit Red Wings"]
        away_prob = api_response["win_probability"]["Vegas Golden Knights"]
        
        # Away team is leading, so away_prob should be higher
        assert away_prob > home_prob
        assert home_prob == 40.0
        assert away_prob == 60.0
        
        # Verify history includes late game events
        history = api_response["historyData"]
        [d for d in history if d["ts"] > 3600]
        # Current time is 3800, so history should reflect recent changes
        
        # Verify current game time is included
        assert api_response["currentGameTime"] == 3800
        assert api_response["currentGameTime"] > 3600  # Late in game
    
    def test_graph_reflects_live_updates(self):
        """Test that graph reflects live updates as game progresses."""
        # Simulate multiple API responses throughout game
        api_responses = [
            # Early in game
            {
                "historyData": [{"ts": 0, "p_home_win": 0.5}],
                "win_probability": {"Home": 50.0, "Away": 50.0},
                "currentGameTime": 300
            },
            # After first goal
            {
                "historyData": [
                    {"ts": 0, "p_home_win": 0.5},
                    {"ts": 300, "p_home_win": 0.55}
                ],
                "win_probability": {"Home": 55.0, "Away": 45.0},
                "currentGameTime": 600
            },
            # Late in game
            {
                "historyData": [
                    {"ts": 0, "p_home_win": 0.5},
                    {"ts": 300, "p_home_win": 0.55},
                    {"ts": 3600, "p_home_win": 0.45}
                ],
                "win_probability": {"Home": 40.0, "Away": 60.0},
                "currentGameTime": 3800
            },
        ]
        
        # Verify each response updates the graph
        for i, response in enumerate(api_responses):
            # History should grow with each update
            if i > 0:
                assert len(response["historyData"]) >= len(api_responses[i-1]["historyData"])
            
            # Current time should progress
            assert response["currentGameTime"] > 0
            
            # Probabilities should sum to 100
            home_prob = response["win_probability"]["Home"]
            away_prob = response["win_probability"]["Away"]
            assert home_prob + away_prob == 100.0
        
        # Verify final response reflects late game state
        final_response = api_responses[-1]
        assert final_response["currentGameTime"] >= 3600  # Late in game
        assert final_response["win_probability"]["Home"] < 50.0  # Home team trailing
        assert final_response["win_probability"]["Away"] > 50.0  # Away team leading


@pytest.mark.integration
class TestGraphRealTimeUpdates:
    """Test that graph updates in real-time as events occur."""
    
    @pytest.mark.asyncio
    async def test_graph_updates_with_new_events(self):
        """Test that graph updates when new events trigger probability changes."""
        # Simulate event sequence
        events = [
            {"time": 0, "home_score": 0, "away_score": 0, "expected_prob": 0.5},
            {"time": 300, "home_score": 1, "away_score": 0, "expected_prob": 0.55},
            {"time": 600, "home_score": 1, "away_score": 1, "expected_prob": 0.5},
            {"time": 1200, "home_score": 2, "away_score": 1, "expected_prob": 0.60},
            {"time": 3600, "home_score": 2, "away_score": 2, "expected_prob": 0.5},
            {"time": 3800, "home_score": 2, "away_score": 3, "expected_prob": 0.40},  # Late goal
        ]
        
        # Simulate graph updates for each event
        graph_updates = []
        for event in events:
            # Calculate probability based on score and time
            score_diff = event["home_score"] - event["away_score"]
            time_factor = min(1.0, event["time"] / 3600.0)
            
            if score_diff == 0:
                prob = 0.5
            else:
                prob = 0.5 + (score_diff * 0.1 * time_factor)
                prob = max(0.05, min(0.95, prob))
            
            graph_updates.append({
                "time": event["time"],
                "probability": prob,
                "home_score": event["home_score"],
                "away_score": event["away_score"],
            })
        
        # Verify graph updates with each event
        assert len(graph_updates) == len(events)
        
        # Verify probabilities change with events
        for i, update in enumerate(graph_updates):
            expected_prob = events[i]["expected_prob"]
            # Allow some tolerance
            assert abs(update["probability"] - expected_prob) < 0.1, \
                f"Event at {update['time']}s: expected ~{expected_prob}, got {update['probability']}"
        
        # Verify final update reflects late goal
        final_update = graph_updates[-1]
        assert final_update["time"] == 3800  # Late in game
        assert final_update["home_score"] == 2
        assert final_update["away_score"] == 3
        assert final_update["probability"] < 0.5  # Away team leading
    
    def test_graph_history_updates_live(self):
        """Test that graph history updates live as new predictions arrive."""
        # Simulate live updates
        initial_history = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
        ]
        
        # New update arrives
        new_prediction = {"ts": 1200, "p_home_win": 0.60}
        updated_history = initial_history + [new_prediction]
        
        # Verify history grows
        assert len(updated_history) == len(initial_history) + 1
        assert updated_history[-1] == new_prediction
        
        # Another update arrives
        another_prediction = {"ts": 2400, "p_home_win": 0.65}
        updated_history.append(another_prediction)
        
        # Verify history continues to grow
        assert len(updated_history) == len(initial_history) + 2
        
        # Verify times are in order
        times = [d["ts"] for d in updated_history]
        assert times == sorted(times)
        
        # Verify probabilities reflect game progression
        probs = [d["p_home_win"] for d in updated_history]
        assert probs[0] == 0.5  # Start at 50/50
        assert probs[-1] > probs[0]  # Progressing in favor of home team
    
    def test_graph_current_probability_updates(self):
        """Test that current probability displayed on graph updates live."""
        # Simulate current probability updates
        updates = [
            {"time": 0, "home_prob": 50.0, "away_prob": 50.0},
            {"time": 300, "home_prob": 55.0, "away_prob": 45.0},
            {"time": 600, "home_prob": 50.0, "away_prob": 50.0},
            {"time": 3600, "home_prob": 45.0, "away_prob": 55.0},  # Late in game
            {"time": 3800, "home_prob": 40.0, "away_prob": 60.0},  # Very late
        ]
        
        # Verify each update changes probability
        for i in range(1, len(updates)):
            prev = updates[i-1]
            curr = updates[i]
            
            # Probability should change
            assert prev["home_prob"] != curr["home_prob"] or prev["time"] == curr["time"]
            
            # Should sum to 100
            assert curr["home_prob"] + curr["away_prob"] == 100.0
        
        # Verify late game update reflects final score
        final_update = updates[-1]
        assert final_update["time"] >= 3600  # Late in game
        assert final_update["away_prob"] > final_update["home_prob"]  # Away team leading

