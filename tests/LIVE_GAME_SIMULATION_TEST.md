# Live Game Simulation Test

## Overview

This test simulates a complete live game scenario to verify that the model updates in real-time as events occur. It tests the entire pipeline:

1. **Events** → Published to Redis `events` stream
2. **Feature State** → Processes events and publishes features to `features` stream
3. **Model Service** → Processes features and publishes predictions to `predictions` stream
4. **Graph Updates** → Predictions are stored and can be retrieved for the graph

## Test Scenarios

### 1. `test_game_event_pipeline`
Simulates a full game with multiple events:
- Game start (faceoff)
- HOME scores first goal (5 minutes in)
- AWAY scores tying goal (10 minutes in)
- End of 1st period
- HOME scores in 2nd period (20 minutes in)
- AWAY scores in 3rd period to tie (60 minutes in)
- AWAY scores final goal late in 3rd period (63:20 in) - **tests final period events**

**Verifications:**
- ✅ All events are published to Redis events stream
- ✅ Feature state processes all events and tracks score correctly
- ✅ Score progression is tracked accurately (0-0 → 1-0 → 1-1 → 2-1 → 2-2 → 2-3)
- ✅ Predictions are generated for each event
- ✅ Probability changes logically with score changes
- ✅ Final period events are processed (including late 3rd period goals)
- ✅ Final score reflects all events including late goals

### 2. `test_game_ending_events_processed`
Specifically tests that events from the final period are processed even after the game ends:
- HOME scores early goal
- AWAY scores late in 3rd period (58:20 in)
- AWAY scores very late in 3rd period (59:40 in) - **tests game ending events**

**Verifications:**
- ✅ All events, including final period events, are in the stream
- ✅ Final score includes all goals, including late 3rd period goals
- ✅ Relative time for final events is correctly calculated

### 3. `test_prediction_updates_with_each_event`
Tests that predictions update with each new event:
- Multiple events throughout the game
- Score changes from tied → HOME leads → tied → HOME leads

**Verifications:**
- ✅ Predictions change with each event
- ✅ Probability increases when HOME scores
- ✅ Probability decreases when AWAY scores
- ✅ Probability returns to 50/50 when tied
- ✅ Score tracking is accurate for each event

## Key Test Features

### Real-Time Updates
The test simulates how events flow through the system in real-time:
- Events are published sequentially
- Each event updates the game state
- Predictions are generated immediately after state updates
- All events are processed, including final period events

### Score Tracking
The test verifies that score tracking works correctly:
- Initial state: 0-0
- After each goal, score is updated correctly
- Final score reflects all goals from all periods
- Late goals in final period are included

### Probability Updates
The test verifies that probability updates logically:
- Starts at 50/50 (tied game)
- Increases when HOME leads
- Decreases when AWAY leads
- Returns to 50/50 when tied
- Reflects time remaining (later in game = more impact)

## Running the Tests

```bash
# Run all live game simulation tests
pytest tests/integration/test_live_game_simulation.py -v

# Run specific test
pytest tests/integration/test_live_game_simulation.py::TestLiveGameSimulation::test_game_event_pipeline -v

# Run with coverage
pytest tests/integration/test_live_game_simulation.py --cov=services --cov-report=html
```

## Test Dependencies

- `pytest`
- `pytest-asyncio`
- `fakeredis` (for Redis simulation)

Install with:
```bash
pip install pytest pytest-asyncio fakeredis
```

## What This Test Validates

✅ **Events are published correctly** - All game events reach the Redis events stream  
✅ **Feature state processes events** - Score and game state are tracked accurately  
✅ **Predictions are generated** - Model produces predictions for each state update  
✅ **Final period events are processed** - Late goals and final events are included  
✅ **Real-time updates work** - The pipeline processes events as they occur  
✅ **Score tracking is accurate** - Final score reflects all events from all periods  

## Integration with Actual System

This test simulates the behavior that should occur in the actual system:
1. Gateway polls NHL API and publishes events
2. Feature state processes events and updates game state
3. Model service generates predictions based on updated state
4. Predictions are stored and can be retrieved for the graph

The test validates that the fix for processing final events works correctly, ensuring that:
- Events from the final period are not missed
- Late goals are included in the final score
- Predictions reflect the complete game state

