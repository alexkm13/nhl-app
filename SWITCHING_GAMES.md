# Switching Between NHL Games

GameCast++ now supports any NHL game! Here's how to switch between games.

## Quick Method

```bash
# 1. List available games
curl http://localhost:8000/v1/games

# 2. Pick a game ID from the list
# 3. Update docker-compose.yaml to set GAME_ID=2025020199

# 4. Restart services
docker compose down ingestor && docker compose up -d ingestor

# 5. Check the results
curl http://localhost:8000/v1/games/2025020199/winprob/friendly
```

## API Endpoints

### List Today's Games
```bash
GET /v1/games
curl http://localhost:8000/v1/games
```

Returns:
- All NHL games scheduled for today
- Game IDs, teams, venues, times
- Game states (FUT, LIVE, OFF, etc.)

### Get Win Probability (Technical)
```bash
GET /v1/games/{game_id}/winprob
curl http://localhost:8000/v1/games/2024020589/winprob
```

Returns raw probability data.

### Get Win Probability (Human-Friendly)
```bash
GET /v1/games/{game_id}/winprob/friendly
curl http://localhost:8000/v1/games/2024020589/winprob/friendly
```

Returns:
- Team names
- Current score
- Formatted win percentages
- Confidence levels
- Situation details

### Get Instructions for a Game
```bash
POST /v1/games/{game_id}/start
curl -X POST http://localhost:8000/v1/games/2025020199/start
```

Returns instructions on how to start ingesting that game.

## Game ID Format

NHL game IDs follow this format: `YYYY0DGGG`
- `YYYY` = Season year (2024 = 2024-25 season)
- `D` = Game type (2 = Regular Season, 3 = Playoffs)
- `GGG` = Sequential game number

Examples:
- `2024020589` = Regular season game #589 in 2024-25
- `2023021234` = Regular season game #234 in 2023-24

## Data Sources

- **Completed Games**: Real NHL play-by-play data
- **Live Games**: Real-time events from NHL API
- **Future Games**: Synthetic simulation (until game starts)

## Web UI

Visit http://localhost:8000/docs for interactive API documentation with all endpoints.

