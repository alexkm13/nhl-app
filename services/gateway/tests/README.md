# Gateway Service Tests

This directory contains comprehensive unit tests for the NHL GameCast++ Gateway service.

## Test Structure

- `test_models.py` - Tests for Pydantic models
- `test_nhl_api.py` - Tests for NHL API client functions
- `test_player_utils.py` - Tests for player utility functions
- `test_event_helpers.py` - Tests for event processing helper functions
- `test_utils.py` - Tests for utility functions (win probability, ingestion, etc.)
- `test_routes_games.py` - Tests for game-related API routes
- `test_routes_playbyplay.py` - Tests for play-by-play routes (to be added)
- `test_routes_standings.py` - Tests for standings routes
- `test_routes_websocket.py` - Tests for websocket routes (to be added)
- `test_main.py` - Tests for main app routes (favicon, root, metrics)

## Running Tests

### Install Dependencies

```bash
pip install -r requirements-test.txt
```

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test File

```bash
pytest tests/test_models.py -v
```

### Run with Coverage

```bash
pytest tests/ --cov=. --cov-report=html
```

## Test Coverage

The test suite covers:

- ✅ Pydantic model validation
- ✅ NHL API client functions (fetching, error handling, caching)
- ✅ Player utility functions (name/headshot fetching, batch operations)
- ✅ Event helper functions (strength calculation, goal distance, formatting)
- ✅ Utility functions (win probability calculation, game ingestion, overtime detection)
- ✅ Game routes (list games, start ingestion, status, win probability, rosters)
- ✅ Standings routes
- ✅ Main app routes (favicon, root, metrics)

## Mocking

Tests use extensive mocking to avoid external dependencies:

- **Redis**: Mocked with `AsyncMock` to avoid requiring a Redis instance
- **HTTP Clients**: Mocked with `httpx.AsyncClient` to avoid making real API calls
- **File System**: Mocked where necessary for static file serving

## Fixtures

Shared fixtures are defined in `conftest.py`:

- `mock_redis` - Mock Redis client
- `mock_httpx_client` - Mock HTTP client
- `test_client` - FastAPI test client
- `sample_game_data` - Sample game data from NHL API
- `sample_boxscore_data` - Sample boxscore data

## Notes

- Some tests may require adjustments based on actual API responses
- WebSocket tests require special handling due to async nature
- Integration tests would require actual services running (Redis, TimescaleDB)

