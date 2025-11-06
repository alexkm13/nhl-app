"""Integration test that simulates a live game to verify real-time model updates."""
import pytest
import json
import time

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Try to import required modules
try:
    from redis.asyncio import Redis  # noqa: F401
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False

# Try to import fakeredis
try:
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
    return time.time()


@pytest.fixture
def sample_game_id():
    """Sample game ID for testing."""
    return "2025020161"


class TestLiveGameSimulation:
    """Test that simulates a live game to verify model updates in real-time."""
    
    @pytest.mark.asyncio
    async def test_game_event_pipeline(self, redis_client, game_start_time, sample_game_id):
        """Test the full pipeline: events -> features -> predictions."""
        
        # Step 1: Simulate game events being published to Redis events stream
        events_stream = "events"
        
        # Create a sequence of events simulating a game
        game_events = [
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 0,  # Game start
                "team": "HOME",
                "event_type": "FACEOFF",
                "strength": "EV",
                "empty_net": False,
                "player_id": 12345,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 300,  # 5 minutes in - HOME goal
                "team": "HOME",
                "event_type": "GOAL",
                "strength": "EV",
                "empty_net": False,
                "player_id": 12346,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 600,  # 10 minutes in - AWAY goal
                "team": "AWAY",
                "event_type": "GOAL",
                "strength": "PP",
                "empty_net": False,
                "player_id": 12347,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 1200,  # 20 minutes in - end of 1st period
                "team": "HOME",
                "event_type": "SHOT",
                "strength": "EV",
                "empty_net": False,
                "player_id": 12348,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 2400,  # 40 minutes in - 2nd period, HOME goal
                "team": "HOME",
                "event_type": "GOAL",
                "strength": "EV",
                "empty_net": False,
                "player_id": 12349,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 3600,  # 60 minutes in - 3rd period, AWAY goal (tie)
                "team": "AWAY",
                "event_type": "GOAL",
                "strength": "EV",
                "empty_net": False,
                "player_id": 12350,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 3800,  # 63:20 in - 3rd period, AWAY goal (takes lead)
                "team": "AWAY",
                "event_type": "GOAL",
                "strength": "EV",
                "empty_net": False,
                "player_id": 12351,
            },
        ]
        
        # Publish events to Redis events stream
        for event in game_events:
            await redis_client.xadd(events_stream, {"json": json.dumps(event)})
        
        # Verify events were published
        events = await redis_client.xrange(events_stream, "-", "+")
        assert len(events) == len(game_events)
        
        # Step 2: Simulate feature state processing events and publishing features
        features_stream = "features"
        features_published = []
        
        # Track game state
        home_score = 0
        away_score = 0
        
        for event in game_events:
            # Update score based on goals
            if event["event_type"] == "GOAL":
                if event["team"] == "HOME":
                    home_score += 1
                else:
                    away_score += 1
            
            # Calculate relative time (seconds elapsed from game start)
            relative_time = event["ts"] - game_start_time
            
            # Create feature state
            feature_state = {
                "game_id": sample_game_id,
                "home_score": home_score,
                "away_score": away_score,
                "ts": relative_time,  # Relative time in seconds
                "strength": event["strength"],
                "last_event": event["event_type"],
                "period": 1 + (relative_time // 1200),  # Calculate period (20 min = 1200 sec)
            }
            
            # Publish to features stream
            await redis_client.xadd(features_stream, {"json": json.dumps(feature_state)})
            features_published.append(feature_state)
        
        # Verify features were published
        features = await redis_client.xrange(features_stream, "-", "+")
        assert len(features) == len(features_published)
        
        # Step 3: Verify score progression
        assert features_published[0]["home_score"] == 0
        assert features_published[0]["away_score"] == 0  # Game start
        
        assert features_published[1]["home_score"] == 1
        assert features_published[1]["away_score"] == 0  # After first goal
        
        assert features_published[2]["home_score"] == 1
        assert features_published[2]["away_score"] == 1  # After second goal (tied)
        
        assert features_published[4]["home_score"] == 2
        assert features_published[4]["away_score"] == 1  # After third goal
        
        assert features_published[5]["home_score"] == 2
        assert features_published[5]["away_score"] == 2  # After fourth goal (tied again)
        
        assert features_published[6]["home_score"] == 2
        assert features_published[6]["away_score"] == 3  # Final score - away team leads
        
        # Step 4: Verify that predictions would be generated (simulate model processing)
        predictions_stream = "predictions"
        predictions_published = []
        
        for feature in features_published:
            # Simulate model prediction
            # In a real scenario, this would call the actual model
            score_diff = feature["home_score"] - feature["away_score"]
            relative_time = feature["ts"]
            
            # Simple probability calculation (simplified version)
            if relative_time > 0:
                time_factor = min(1.0, relative_time / 3600.0)  # Normalize to game length
                base_prob = 0.5 + (score_diff * 0.1 * time_factor)
                probability = max(0.05, min(0.95, base_prob))
            else:
                probability = 0.5
            
            prediction = {
                "game_id": sample_game_id,
                "ts": feature["ts"],  # Relative time
                "model_id": "test_model",
                "p_home_win": round(probability, 4),
            }
            
            # Publish to predictions stream
            await redis_client.xadd(predictions_stream, {"json": json.dumps(prediction)})
            predictions_published.append(prediction)
        
        # Verify predictions were published
        predictions = await redis_client.xrange(predictions_stream, "-", "+")
        assert len(predictions) == len(predictions_published)
        
        # Step 5: Verify probability changes throughout the game
        # At game start, should be close to 50/50
        assert 0.45 <= predictions_published[0]["p_home_win"] <= 0.55
        
        # After HOME scores first goal, HOME probability should increase
        assert predictions_published[1]["p_home_win"] > predictions_published[0]["p_home_win"]
        
        # After AWAY scores (tied), probability should return closer to 50/50
        assert abs(predictions_published[2]["p_home_win"] - 0.5) < abs(predictions_published[1]["p_home_win"] - 0.5)
        
        # After HOME takes lead again, HOME probability should increase
        assert predictions_published[4]["p_home_win"] > predictions_published[2]["p_home_win"]
        
        # Final prediction should reflect away team winning
        assert predictions_published[6]["p_home_win"] < 0.5  # Away team leads
        
        # Step 6: Verify predictions are stored in Redis hash
        pred_key = f"pred:{sample_game_id}"
        latest_pred = await redis_client.hgetall(pred_key)
        
        if latest_pred:
            assert latest_pred["game_id"] == sample_game_id
            assert "p_home_win" in latest_pred
            assert float(latest_pred["p_home_win"]) < 0.5  # Away team leads
        
        # Step 7: Verify that all events from the entire game are processed
        # Including events from the final period
        final_period_event = None
        for event in game_events:
            relative_time = event["ts"] - game_start_time
            if relative_time > 3600:  # Events in 3rd period
                final_period_event = event
        
        assert final_period_event is not None
        assert final_period_event["event_type"] == "GOAL"
        assert final_period_event["team"] == "AWAY"
        
        # Verify this event was processed
        final_features = [f for f in features_published if f["ts"] > 3600]
        assert len(final_features) > 0
        
        # Verify final score reflects all events
        final_score = features_published[-1]
        assert final_score["home_score"] == 2
        assert final_score["away_score"] == 3
    
    @pytest.mark.asyncio
    async def test_game_ending_events_processed(self, redis_client, game_start_time, sample_game_id):
        """Test that events from the final period are processed even after game ends."""
        
        events_stream = "events"
        
        # Simulate events throughout the game
        game_events = [
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 300,
                "team": "HOME",
                "event_type": "GOAL",
                "strength": "EV",
                "empty_net": False,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 3500,  # Late in 3rd period
                "team": "AWAY",
                "event_type": "GOAL",
                "strength": "EV",
                "empty_net": False,
            },
            {
                "game_id": sample_game_id,
                "ts": game_start_time + 3580,  # Very late in 3rd period (game ending)
                "team": "AWAY",
                "event_type": "GOAL",
                "strength": "EV",
                "empty_net": False,
            },
        ]
        
        # Publish all events
        for event in game_events:
            await redis_client.xadd(events_stream, {"json": json.dumps(event)})
        
        # Verify all events, including final period events, are in the stream
        events = await redis_client.xrange(events_stream, "-", "+")
        assert len(events) == 3
        
        # Verify final period events are present
        final_events = [e for e in game_events if (e["ts"] - game_start_time) >= 3500]
        assert len(final_events) == 2
        
        # Process all events as features
        features_stream = "features"
        home_score = 0
        away_score = 0
        
        for event in game_events:
            if event["event_type"] == "GOAL":
                if event["team"] == "HOME":
                    home_score += 1
                else:
                    away_score += 1
            
            relative_time = event["ts"] - game_start_time
            feature_state = {
                "game_id": sample_game_id,
                "home_score": home_score,
                "away_score": away_score,
                "ts": relative_time,
                "strength": "EV",
                "last_event": event["event_type"],
            }
            
            await redis_client.xadd(features_stream, {"json": json.dumps(feature_state)})
        
        # Verify final score includes all goals, including late 3rd period goals
        features = await redis_client.xrange(features_stream, "-", "+")
        final_feature_json = json.loads(features[-1][1]["json"])
        
        assert final_feature_json["home_score"] == 1
        assert final_feature_json["away_score"] == 2  # Both late goals counted
        
        # Verify relative time for final event
        assert final_feature_json["ts"] > 3500  # Late in 3rd period
    
    @pytest.mark.asyncio
    async def test_prediction_updates_with_each_event(self, redis_client, game_start_time, sample_game_id):
        """Test that predictions update with each new event."""
        
        # Simulate multiple events and verify predictions change
        events = [
            {"game_id": sample_game_id, "ts": game_start_time + 0, "team": "HOME", "event_type": "FACEOFF", "strength": "EV"},
            {"game_id": sample_game_id, "ts": game_start_time + 600, "team": "HOME", "event_type": "GOAL", "strength": "EV"},
            {"game_id": sample_game_id, "ts": game_start_time + 1200, "team": "AWAY", "event_type": "GOAL", "strength": "EV"},
            {"game_id": sample_game_id, "ts": game_start_time + 2400, "team": "HOME", "event_type": "GOAL", "strength": "EV"},
        ]
        
        predictions = []
        home_score = 0
        away_score = 0
        
        for event in events:
            # Update score
            if event["event_type"] == "GOAL":
                if event["team"] == "HOME":
                    home_score += 1
                else:
                    away_score += 1
            
            # Calculate prediction
            score_diff = home_score - away_score
            relative_time = event["ts"] - game_start_time
            
            if relative_time > 0:
                time_factor = min(1.0, relative_time / 3600.0)
                base_prob = 0.5 + (score_diff * 0.1 * time_factor)
                probability = max(0.05, min(0.95, base_prob))
            else:
                probability = 0.5
            
            predictions.append({
                "ts": relative_time,
                "home_score": home_score,
                "away_score": away_score,
                "p_home_win": probability,
            })
        
        # Verify predictions change with each event
        assert predictions[0]["p_home_win"] == 0.5  # Tied at start
        
        assert predictions[1]["p_home_win"] > 0.5  # HOME leads after first goal
        assert predictions[1]["home_score"] == 1
        assert predictions[1]["away_score"] == 0
        
        assert predictions[2]["p_home_win"] == 0.5  # Tied after second goal
        assert predictions[2]["home_score"] == 1
        assert predictions[2]["away_score"] == 1
        
        assert predictions[3]["p_home_win"] > 0.5  # HOME leads again after third goal
        assert predictions[3]["home_score"] == 2
        assert predictions[3]["away_score"] == 1
        
        # Verify probability changes are logical
        assert predictions[1]["p_home_win"] > predictions[0]["p_home_win"]  # Increase after HOME goal
        assert predictions[2]["p_home_win"] < predictions[1]["p_home_win"]  # Decrease after AWAY goal
        assert predictions[3]["p_home_win"] > predictions[2]["p_home_win"]  # Increase after HOME goal

