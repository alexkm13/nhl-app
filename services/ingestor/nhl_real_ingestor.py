import asyncio
import json
import os
import time

import psycopg
from nhlpy import NHLClient
from redis.asyncio import Redis

import sys

sys.path.insert(0, os.path.dirname(__file__))
from events import GameEvent

DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
GAME_ID = os.environ.get("GAME_ID", "2024020589")

STREAM_EVENTS = "events"

# Event type mapping from NHL API to our format
EVENT_TYPE_MAP = {
    "faceoff": "FACEOFF",
    "shot": "SHOT",
    "missed-shot": "SHOT",
    "blocked-shot": "BLOCK",
    "goal": "GOAL",
    "hit": "HIT",
    "penalty": "PENALTY",
    "takeaway": "SHOT",
    "giveaway": "SHOT",
}

STRENGTH_MAP = {
    "1551": "EV",  # Even strength 5v5
    "1441": "PP",  # Power play
    "1542": "PK",  # Penalty kill
}


async def stream_nhl_game_events(r: Redis, game_id: str):
    """Stream real game events from NHL API"""
    print(f"[nhl-ingestor] Starting NHL API stream for game {game_id}")

    client = NHLClient()
    processed_events = set()

    while True:
        try:
            # Get play-by-play data
            pbp_data = client.game_center.play_by_play(game_id)

            if not pbp_data:
                print(f"[nhl-ingestor] No data for game {game_id}")
                await asyncio.sleep(10)
                continue

            # Check game state
            game_state = pbp_data.get("gameState", "UNKNOWN")
            print(f"[nhl-ingestor] Game state: {game_state}")

            # If game is finished, exit
            if game_state in ["OFF", "FINAL", "FINAL", "GAME_END"]:
                print(f"[nhl-ingestor] Game {game_id} is finished")
                break

            # Get home and away team IDs
            home_team_id = pbp_data.get("homeTeam", {}).get("id")
            away_team_id = pbp_data.get("awayTeam", {}).get("id")

            # Process plays
            plays = pbp_data.get("plays", [])

            for play in plays:
                event_id = play.get("eventId")

                # Skip already processed events
                if event_id in processed_events:
                    continue

                type_key = play.get("typeDescKey", "")
                details = play.get("details", {})

                # Skip non-game events
                if type_key in ["period-start", "period-end", "game-end"]:
                    continue

                # Map event type
                event_type = EVENT_TYPE_MAP.get(type_key, "SHOT")

                # Determine team (HOME or AWAY)
                owner_team_id = details.get("eventOwnerTeamId")
                if owner_team_id == home_team_id:
                    team = "HOME"
                elif owner_team_id == away_team_id:
                    team = "AWAY"
                else:
                    continue  # Skip if can't determine team

                # Get strength situation
                situation_code = play.get("situationCode", "1551")
                strength = STRENGTH_MAP.get(situation_code, "EV")

                # Get coordinates with validation
                x = details.get("xCoord")
                y = details.get("yCoord")

                # Validate coordinates are numeric
                try:
                    if x is not None:
                        x = float(x)
                    if y is not None:
                        y = float(y)
                except (ValueError, TypeError):
                    logger = logging.getLogger("nhl-ingestor")
                    logger.warning(f"Invalid coordinates x={x}, y={y}, setting to None")
                    x, y = None, None

                # Create timestamp
                now = time.time()

                # Create event
                payload = GameEvent(
                    game_id=game_id,
                    ts=now,
                    team=team,
                    event_type=event_type,
                    strength=strength,
                    x=x,
                    y=y,
                ).model_dump()

                # Send to stream
                sid = await r.xadd(STREAM_EVENTS, {"json": json.dumps(payload)})
                print(f"[nhl-ingestor] XADD events id={sid} {event_type} team={team}")

                # Mark as processed
                processed_events.add(event_id)

                # Persist to DB if configured
                try:
                    if DATABASE_URL:
                        async with await psycopg.AsyncConnection.connect(
                            DATABASE_URL, autocommit=True
                        ) as conn:
                            async with conn.cursor() as cur:
                                await cur.execute(
                                    "INSERT INTO events(ts, game_id, team, event_type, strength, x, y) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s, %s)",
                                    (now, game_id, team, event_type, strength, x, y),
                                )
                                # No commit needed with autocommit=True
                except Exception as e:
                    logger = logging.getLogger("nhl-ingestor")
                    logger.error(f"Database insert error: {e}", exc_info=True)

            # Poll every 5 seconds for updates (slower to avoid rate limiting)
            await asyncio.sleep(5)

        except Exception as e:
            print(f"[nhl-ingestor] Error streaming events: {e}")
            import traceback

            traceback.print_exc()
            await asyncio.sleep(10)  # Wait longer on error


async def main():
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await stream_nhl_game_events(r, GAME_ID)
    finally:
        await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
