# API.md (initial)

## GET /v1/games/{game_id}/winprob
Returns the latest win probability for `game_id`.
- 200: `{ "game_id": "...", "p_home_win": 0.63, "model_id": "baseline-logit-v0", "ts": 1712345678.12 }`
- 404 if no prediction yet.

## WS /v1/stream/{game_id}
Sends a JSON message whenever a new prediction for that `game_id` is produced.
Message schema is same as GET response.
