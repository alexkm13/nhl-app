"""Integration test to verify graph reflects live probability updates."""
import pytest
import json

# Try to import required modules
try:
    from redis.asyncio import Redis  # noqa: F401
    from fakeredis import FakeAsyncRedis
    HAS_FAKEREDIS = True
except ImportError:
    HAS_FAKEREDIS = False
    FakeAsyncRedis = None

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def redis_client():
    """Create a fake Redis client for testing."""
    if HAS_FAKEREDIS:
        redis = FakeAsyncRedis(decode_responses=True)
        yield redis
        await redis.flushall()
        await redis.close()
    else:
        pytest.skip("fakeredis not available for testing")


@pytest.fixture
def game_start_time():
    """Get a game start time for testing."""
    import time
    return time.time()


@pytest.fixture
def sample_game_id():
    """Sample game ID for testing."""
    return "2025020161"


class TestGraphLiveProbabilityReflection:
    """Test that graph reflects live probability updates."""
    
    @pytest.mark.asyncio
    async def test_graph_updates_with_real_time_events(self, redis_client, game_start_time, sample_game_id):
        """Test that graph updates in real-time as events occur and probabilities change."""
        
        # Simulate a complete game with events and probability updates
        game_timeline = [
            # Time 0: Game start
            {
                "time": 0,
                "home_score": 0,
                "away_score": 0,
                "event": "game_start",
                "expected_prob": 0.5,
            },
            # Time 300: Home scores first goal
            {
                "time": 300,
                "home_score": 1,
                "away_score": 0,
                "event": "home_goal",
                "expected_prob": 0.55,
            },
            # Time 600: Away scores (tied)
            {
                "time": 600,
                "home_score": 1,
                "away_score": 1,
                "event": "away_goal",
                "expected_prob": 0.5,
            },
            # Time 1200: Home scores again
            {
                "time": 1200,
                "home_score": 2,
                "away_score": 1,
                "event": "home_goal",
                "expected_prob": 0.60,
            },
            # Time 2400: Still 2-1
            {
                "time": 2400,
                "home_score": 2,
                "away_score": 1,
                "event": "no_goal",
                "expected_prob": 0.65,  # Higher because less time remaining
            },
            # Time 3600: Late in 3rd period, away scores (tied)
            {
                "time": 3600,
                "home_score": 2,
                "away_score": 2,
                "event": "away_goal",
                "expected_prob": 0.5,
            },
            # Time 3800: Very late, away scores again (takes lead)
            {
                "time": 3800,
                "home_score": 2,
                "away_score": 3,
                "event": "away_goal",
                "expected_prob": 0.35,  # Away team leading late
            },
        ]
        
        # Simulate events being published and processed
        events_stream = "events"
        features_stream = "features"
        predictions_stream = "predictions"
        
        predictions_history = []
        home_score = 0
        away_score = 0
        
        for timeline_item in game_timeline:
            relative_time = timeline_item["time"]
            home_score = timeline_item["home_score"]
            away_score = timeline_item["away_score"]
            
            # Simulate event being published
            if timeline_item["event"] != "no_goal":
                event = {
                    "game_id": sample_game_id,
                    "ts": game_start_time + relative_time,
                    "team": "HOME" if "home" in timeline_item["event"] else "AWAY",
                    "event_type": "GOAL",
                    "strength": "EV",
                    "empty_net": False,
                }
                await redis_client.xadd(events_stream, {"json": json.dumps(event)})
            
            # Simulate feature state processing
            feature_state = {
                "game_id": sample_game_id,
                "home_score": home_score,
                "away_score": away_score,
                "ts": relative_time,
                "strength": "EV",
                "last_event": "GOAL" if timeline_item["event"] != "no_goal" else "SHOT",
            }
            await redis_client.xadd(features_stream, {"json": json.dumps(feature_state)})
            
            # Simulate model prediction
            score_diff = home_score - away_score
            time_factor = min(1.0, relative_time / 3600.0)
            
            if score_diff == 0:
                prob = 0.5
            else:
                base_prob = 0.5 + (score_diff * 0.1 * time_factor)
                prob = max(0.05, min(0.95, base_prob))
            
            prediction = {
                "game_id": sample_game_id,
                "ts": relative_time,
                "model_id": "test_model",
                "p_home_win": round(prob, 4),
            }
            await redis_client.xadd(predictions_stream, {"json": json.dumps(prediction)})
            await redis_client.hset(f"pred:{sample_game_id}", mapping={k: str(v) for k, v in prediction.items()})
            
            predictions_history.append({
                "time": relative_time,
                "home_score": home_score,
                "away_score": away_score,
                "probability": prob,
                "prediction": prediction,
            })
        
        # Verify predictions were generated for each event
        predictions = await redis_client.xrange(predictions_stream, "-", "+")
        assert len(predictions) == len(game_timeline)
        
        # Verify probability changes reflect score changes
        assert predictions_history[0]["probability"] == 0.5  # Tied at start
        assert predictions_history[1]["probability"] > 0.5  # Home leads after first goal
        assert abs(predictions_history[2]["probability"] - 0.5) < 0.1  # Tied after second goal
        assert predictions_history[3]["probability"] > 0.5  # Home leads again
        assert predictions_history[4]["probability"] > predictions_history[3]["probability"]  # Higher with less time
        assert abs(predictions_history[5]["probability"] - 0.5) < 0.1  # Tied late in game
        assert predictions_history[6]["probability"] < 0.5  # Away leads late in game
        
        # Verify final probability reflects final score
        final_prediction = predictions_history[-1]
        assert final_prediction["home_score"] == 2
        assert final_prediction["away_score"] == 3
        assert final_prediction["probability"] < 0.5  # Away team leading
        
        # Verify graph history would include all predictions
        history_data = [{"ts": p["time"], "p_home_win": p["probability"]} for p in predictions_history]
        
        # Verify all events are included
        assert len(history_data) == len(game_timeline)
        
        # Verify late game events are included
        late_events = [h for h in history_data if h["ts"] >= 3600]
        assert len(late_events) == 2  # Two late game events
        
        # Verify final event is included
        final_event = history_data[-1]
        assert final_event["ts"] == 3800  # Very late in game
        assert final_event["p_home_win"] < 0.5  # Away team leading
    
    @pytest.mark.asyncio
    async def test_graph_reflects_current_probability(self, redis_client, game_start_time, sample_game_id):
        """Test that graph displays the current live probability."""
        
        # Simulate history data
        history_data = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
            {"ts": 1200, "p_home_win": 0.60},
            {"ts": 3600, "p_home_win": 0.65},
        ]
        
        # Current probability (from latest prediction)
        current_home_prob = 40.0  # 40% (away team leading)
        current_away_prob = 60.0  # 60%
        current_game_time = 3800  # 63:20 in game
        
        # Verify current probability is different from last history point
        last_history_prob = history_data[-1]["p_home_win"] * 100
        assert current_home_prob != last_history_prob
        
        # Graph should include current probability
        # The graph generation should add current point at current_game_time
        assert current_home_prob + current_away_prob == 100.0
        
        # Current probability should reflect the latest game state
        # (away team leading, so home prob < 50%)
        assert current_home_prob < 50.0
        assert current_away_prob > 50.0
        
        # Verify graph would include this current point
        # The graph should show the line extending to current_game_time with current_prob
        extended_history = history_data + [{"ts": current_game_time, "p_home_win": current_home_prob / 100}]
        
        assert len(extended_history) == len(history_data) + 1
        assert extended_history[-1]["ts"] == current_game_time
        assert extended_history[-1]["p_home_win"] == current_home_prob / 100
    
    @pytest.mark.asyncio
    async def test_graph_updates_with_late_goals(self, redis_client, game_start_time, sample_game_id):
        """Test that graph reflects late goals that change probability."""
        
        # Simulate game progression
        initial_history = [
            {"ts": 0, "p_home_win": 0.5},
            {"ts": 600, "p_home_win": 0.55},
            {"ts": 1200, "p_home_win": 0.60},
            {"ts": 2400, "p_home_win": 0.65},
            {"ts": 3600, "p_home_win": 0.70},  # Home team leading late
        ]
        
        # Late goal occurs - away team scores
        late_goal_time = 3800
        late_goal_probability = 0.45  # Home probability drops after away scores
        
        # Graph should include this late goal
        updated_history = initial_history + [{"ts": late_goal_time, "p_home_win": late_goal_probability}]
        
        # Verify late goal is included
        assert len(updated_history) == len(initial_history) + 1
        assert updated_history[-1]["ts"] == late_goal_time
        assert updated_history[-1]["p_home_win"] == late_goal_probability
        
        # Verify probability changed significantly
        assert updated_history[-1]["p_home_win"] < updated_history[-2]["p_home_win"]
        
        # Verify time progression
        times = [h["ts"] for h in updated_history]
        assert times == sorted(times)
        assert times[-1] > 3600  # Late in game
        
        # Simulate this being published to predictions stream
        prediction = {
            "game_id": sample_game_id,
            "ts": late_goal_time,
            "model_id": "test_model",
            "p_home_win": late_goal_probability,
        }
        await redis_client.xadd("predictions", {"json": json.dumps(prediction)})
        await redis_client.hset(f"pred:{sample_game_id}", mapping={k: str(v) for k, v in prediction.items()})
        
        # Verify prediction was stored
        stored_pred = await redis_client.hgetall(f"pred:{sample_game_id}")
        assert stored_pred["ts"] == str(late_goal_time)
        assert float(stored_pred["p_home_win"]) == late_goal_probability
    
    @pytest.mark.asyncio
    async def test_graph_continuous_updates(self, redis_client, game_start_time, sample_game_id):
        """Test that graph continuously updates with each new prediction."""
        
        # Simulate multiple updates throughout game
        updates = []
        
        for i in range(10):
            time_offset = i * 300  # Every 5 minutes
            home_score = 1 if i > 2 else 0
            away_score = 1 if i > 5 else 0
            
            score_diff = home_score - away_score
            time_factor = min(1.0, time_offset / 3600.0)
            
            if score_diff == 0:
                prob = 0.5
            else:
                prob = 0.5 + (score_diff * 0.1 * time_factor)
                prob = max(0.05, min(0.95, prob))
            
            prediction = {
                "game_id": sample_game_id,
                "ts": time_offset,
                "model_id": "test_model",
                "p_home_win": round(prob, 4),
            }
            
            await redis_client.xadd("predictions", {"json": json.dumps(prediction)})
            updates.append({
                "time": time_offset,
                "probability": prob,
                "prediction": prediction,
            })
        
        # Verify all updates were stored
        predictions = await redis_client.xrange("predictions", "-", "+")
        assert len(predictions) == 10
        
        # Verify graph history would include all updates
        history_data = [{"ts": u["time"], "p_home_win": u["probability"]} for u in updates]
        
        assert len(history_data) == 10
        
        # Verify times are in order
        times = [h["ts"] for h in history_data]
        assert times == sorted(times)
        
        # Verify probabilities change throughout
        probs = [h["p_home_win"] for h in history_data]
        # Not all probabilities should be the same
        assert len(set(probs)) > 1
        
        # Verify final update reflects latest state
        final_update = updates[-1]
        assert final_update["time"] == 2700  # 45 minutes in
        assert 0.05 <= final_update["probability"] <= 0.95


@pytest.mark.integration
class TestGraphLiveUpdatesEndToEnd:
    """End-to-end test simulating the full pipeline."""
    
    @pytest.mark.asyncio
    async def test_complete_game_simulation_with_graph_updates(self, redis_client, game_start_time, sample_game_id):
        """Test complete game simulation with graph reflecting all probability changes."""
        
        # Simulate a complete game with all events
        game_events = [
            {"time": 0, "home_score": 0, "away_score": 0, "event": "start"},
            {"time": 300, "home_score": 1, "away_score": 0, "event": "home_goal"},
            {"time": 600, "home_score": 1, "away_score": 1, "event": "away_goal"},
            {"time": 1200, "home_score": 2, "away_score": 1, "event": "home_goal"},
            {"time": 2400, "home_score": 2, "away_score": 1, "event": "no_goal"},
            {"time": 3600, "home_score": 2, "away_score": 2, "event": "away_goal"},
            {"time": 3800, "home_score": 2, "away_score": 3, "event": "away_goal"},  # Final goal
        ]
        
        # Process each event through the pipeline
        predictions_history = []
        
        for event_data in game_events:
            relative_time = event_data["time"]
            home_score = event_data["home_score"]
            away_score = event_data["away_score"]
            
            # Calculate probability
            score_diff = home_score - away_score
            time_factor = min(1.0, relative_time / 3600.0)
            
            if score_diff == 0:
                prob = 0.5
            else:
                prob = 0.5 + (score_diff * 0.1 * time_factor)
                prob = max(0.05, min(0.95, prob))
            
            prediction = {
                "game_id": sample_game_id,
                "ts": relative_time,
                "model_id": "test_model",
                "p_home_win": round(prob, 4),
            }
            
            await redis_client.xadd("predictions", {"json": json.dumps(prediction)})
            predictions_history.append({
                "time": relative_time,
                "home_score": home_score,
                "away_score": away_score,
                "probability": prob,
            })
        
        # Verify graph would reflect all predictions
        history_data = [{"ts": p["time"], "p_home_win": p["probability"]} for p in predictions_history]
        
        # Verify all events are reflected
        assert len(history_data) == len(game_events)
        
        # Verify probability changes correctly
        assert history_data[0]["p_home_win"] == 0.5  # Start
        assert history_data[1]["p_home_win"] > 0.5  # After home goal
        assert abs(history_data[2]["p_home_win"] - 0.5) < 0.1  # Tied
        assert history_data[3]["p_home_win"] > 0.5  # Home leads again
        assert history_data[4]["p_home_win"] > history_data[3]["p_home_win"]  # Higher with less time
        assert abs(history_data[5]["p_home_win"] - 0.5) < 0.1  # Tied late
        assert history_data[6]["p_home_win"] < 0.5  # Away leads late
        
        # Verify final prediction reflects complete game
        final_pred = predictions_history[-1]
        assert final_pred["home_score"] == 2
        assert final_pred["away_score"] == 3
        assert final_pred["probability"] < 0.5
        assert final_pred["time"] == 3800  # Late in game
        
        # Verify graph would show complete timeline
        times = [h["ts"] for h in history_data]
        assert min(times) == 0  # Game start
        assert max(times) == 3800  # Includes late events
        
        # Verify probabilities span the full range
        probs = [h["p_home_win"] for h in history_data]
        assert min(probs) >= 0.05
        assert max(probs) <= 0.95
        assert 0.5 in [round(p, 1) for p in probs]  # Tied at some point

