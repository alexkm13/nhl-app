import asyncio
import json
import logging
import os
import random
import sys
import time
from datetime import datetime

import httpx
import psycopg
from redis.asyncio import Redis

# Add parent directory to path for common imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from common.constants import (
    NHL_API_BASE_URL,
    NHL_API_TIMEOUT_SECONDS,
    REDIS_DEFAULT_URL,
    STREAM_EVENTS,
    CONSUMER_ID_MIN,
    CONSUMER_ID_MAX,
    SYNTHETIC_GAME_DURATION_SECONDS,
    EVENT_PROCESSING_SLEEP_SECONDS,
    EVENT_WEIGHT_SHOT,
    EVENT_WEIGHT_FACEOFF,
    EVENT_WEIGHT_HIT,
    EVENT_WEIGHT_PENALTY,
    PROBABILITY_SHOT_IS_GOAL,
    PROBABILITY_POWER_PLAY,
    STRENGTH_EVEN,
    STRENGTH_POWER_PLAY,
    STRENGTH_PENALTY_KILL,
    RINK_X_MIN,
    RINK_X_MAX,
    RINK_Y_MIN,
    RINK_Y_MAX,
)
from common.logging_config import setup_logger
from events import GameEvent

# Configure logging
logger = setup_logger("ingestor", level=logging.INFO)


async def fetch_nhl_play_by_play(game_id: str) -> dict:
    """
    Fetch play-by-play data directly from NHL API.

    Args:
        game_id: NHL game ID to fetch

    Returns:
        Game data dictionary or None if fetch failed
    """
    try:
        async with httpx.AsyncClient(timeout=NHL_API_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{NHL_API_BASE_URL}/gamecenter/{game_id}/play-by-play"
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(
                    f"NHL API returned status {response.status_code} for game {game_id}"
                )
                return None
    except Exception as e:
        logger.error(
            f"Error fetching NHL play-by-play for game {game_id}: {e}", exc_info=True
        )
        return None


DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", REDIS_DEFAULT_URL)
GAME_ID = os.environ.get("GAME_ID", "TEST_GAME")
CONSUMER = f"producer-{random.randint(CONSUMER_ID_MIN, CONSUMER_ID_MAX)}"


async def ensure_streams(r: Redis) -> None:
    """
    Create event stream if it doesn't exist.

    Args:
        r: Redis client instance
    """
    # Create an empty stream so downstream groups can be created safely.
    await r.xadd(STREAM_EVENTS, {"bootstrap": "1"}, id="*")


async def produce_synthetic_game(r: Redis, game_id: str) -> None:
    """
    Produce synthetic game events for testing/demo purposes.

    Args:
        r: Redis client instance
        game_id: Game ID to generate events for
    """
    logger.info(f"Starting synthetic game for {game_id}")
    start = time.time()
    clock_total = SYNTHETIC_GAME_DURATION_SECONDS

    t = 0.0
    random.seed(42)
    while t < clock_total:
        await asyncio.sleep(EVENT_PROCESSING_SLEEP_SECONDS)  # emit ~2 events/sec

        # Random event selection
        ev_choice = random.choices(
            ["SHOT", "FACEOFF", "HIT", "PENALTY"],
            weights=[
                EVENT_WEIGHT_SHOT,
                EVENT_WEIGHT_FACEOFF,
                EVENT_WEIGHT_HIT,
                EVENT_WEIGHT_PENALTY,
            ],
            k=1,
        )[0]
        team = random.choice(["HOME", "AWAY"])

        # Occasional goals
        if ev_choice == "SHOT" and random.random() < PROBABILITY_SHOT_IS_GOAL:
            ev_choice = "GOAL"

        strength = STRENGTH_EVEN
        if random.random() < PROBABILITY_POWER_PLAY:
            strength = random.choice([STRENGTH_POWER_PLAY, STRENGTH_PENALTY_KILL])

        now = time.time()
        payload = GameEvent(
            game_id=game_id,
            ts=now,
            team=team,
            event_type=ev_choice,
            strength=strength,
            x=random.uniform(RINK_X_MIN, RINK_X_MAX),
            y=random.uniform(RINK_Y_MIN, RINK_Y_MAX),
            shot_quality=random.random(),
        ).model_dump()

        # Insert into TimescaleDB (optional)
        try:
            if DATABASE_URL:
                async with await psycopg.AsyncConnection.connect(
                    DATABASE_URL, autocommit=True
                ) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "INSERT INTO events(ts, game_id, team, event_type, strength, x, y, shot_quality) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s)",
                            (
                                now,
                                game_id,
                                team,
                                ev_choice,
                                strength,
                                payload["x"],
                                payload["y"],
                                payload["shot_quality"],
                            ),
                        )
                        # No commit needed with autocommit=True
        except Exception as e:
            logger.error(f"Database insert error: {e}", exc_info=True)

        sid = await r.xadd(STREAM_EVENTS, {"json": json.dumps(payload)})
        logger.debug(f"Published event {sid}: {payload['event_type']} team={team}")
        t = now - start

    logger.info("Synthetic game complete")


async def fetch_nhl_game_data(game_id: str):
    """
    Fetch live or completed NHL game data.

    Args:
        game_id: NHL game ID to fetch

    Returns:
        Game data dictionary or None if unavailable
    """
    try:
        # Try to get play-by-play data
        game_data = await fetch_nhl_play_by_play(game_id)

        if not game_data or not isinstance(game_data, dict):
            return None

        # Extract plays list
        plays = game_data.get("plays", [])

        if isinstance(plays, list) and len(plays) > 0:
            # Return full game data including team IDs
            return game_data

        return None
    except Exception as e:
        logger.error(f"Error fetching NHL game {game_id}: {e}", exc_info=True)
        return None


async def produce_nhl_game(r: Redis, game_id: str) -> None:
    """
    Produce events from real NHL game data.

    Args:
        r: Redis client instance
        game_id: NHL game ID to ingest
    """
    logger.info(f"Fetching NHL game data for {game_id}")

    game_data = await fetch_nhl_game_data(game_id)

    if not game_data:
        logger.warning(
            f"Could not fetch NHL data for {game_id}, falling back to synthetic"
        )
        await produce_synthetic_game(r, game_id)
        return

    # If we have live game data, extract events
    plays = game_data.get("plays", [])

    if not plays:
        logger.warning("No play-by-play data available, using synthetic")
        await produce_synthetic_game(r, game_id)
        return

    # Get team IDs once
    home_team_id = game_data.get("homeTeam", {}).get("id")
    away_team_id = game_data.get("awayTeam", {}).get("id")

    logger.info(f"Processing {len(plays)} events from NHL API")

    # Process real NHL events
    for play in plays:
        type_code = str(play.get("typeCode", ""))
        type_desc = play.get("typeDescKey", "")

        # Map NHL event type codes to our event types
        type_mapping = {
            "502": "FACEOFF",
            "503": "HIT",
            "504": "HIT",  # giveaway
            "505": "GOAL",
            "506": "SHOT",
            "507": "SHOT",  # missed-shot
            "508": "BLOCK",
            "509": "PENALTY",
        }

        # Skip non-relevant events
        if type_code in [
            "520",
            "516",
            "517",
            "524",
        ]:  # period-start, stoppage, period-end, game-end
            continue

        mapped_type = type_mapping.get(type_code, "SHOT")
        if mapped_type == "SHOT" and type_desc == "missed-shot":
            mapped_type = "SHOT"  # Keep as SHOT

        # Determine team from event owner
        details = play.get("details", {})
        event_owner_id = details.get("eventOwnerTeamId")

        # Match event owner to home/away
        if event_owner_id == home_team_id:
            team = "HOME"
        elif event_owner_id == away_team_id:
            team = "AWAY"
        else:
            # Missing eventOwnerTeamId - need fallback logic
            # For goals, use consistent scoring team logic
            if mapped_type == "GOAL":
                # For goals, use scoringPlayerId to determine team if available
                logger.warning(
                    f"Goal missing eventOwnerTeamId for game {game_id}, using defending side logic"
                )
                # Use the scoring team - if homeTeamDefendingSide is "right",
                # home is defending, so away scored (opposite of defending)
                defending_side = play.get("homeTeamDefendingSide")
                if defending_side:
                    team = "AWAY" if defending_side == "right" else "HOME"
                else:
                    # Last resort: assume home team
                    logger.error(
                        f"Goal missing both eventOwnerTeamId and homeTeamDefendingSide for game {game_id}"
                    )
                    team = "HOME"
            else:
                # For non-crucial events, fallback to defending side if available
                defending_side = play.get("homeTeamDefendingSide")
                if defending_side:
                    team = "HOME" if defending_side == "right" else "AWAY"
                else:
                    # Default to home team if no defending side info
                    team = "HOME"

        # Get situation/strength from NHL API situationCode
        # Format: ABCD where B=away_skaters, D=home_skaters
        # E.g., "1551" = 5v5 even strength, "1451" = 4v5, "0651" = 6v1 (empty net)
        situation = play.get("situationCode", "1551")

        # Validate and parse situationCode with bounds checking
        try:
            if len(situation) >= 4 and situation.isdigit():
                away_skaters = int(situation[1])
                home_skaters = int(situation[3])
                # Sanity check: skaters should be 0-6
                if not (0 <= away_skaters <= 6 and 0 <= home_skaters <= 6):
                    logger.warning(f"Invalid situationCode {situation}, using defaults")
                    away_skaters, home_skaters = 5, 5
            else:
                logger.warning(f"Malformed situationCode {situation}, using defaults")
                away_skaters, home_skaters = 5, 5
        except (ValueError, IndexError):
            logger.warning(f"Failed to parse situationCode {situation}, using defaults")
            away_skaters, home_skaters = 5, 5

        # Detect empty net situations (6 skaters or 0 skaters = goalie pulled)
        empty_net = False
        if (
            away_skaters == 6
            or home_skaters == 6
            or away_skaters == 0
            or home_skaters == 0
        ):
            empty_net = True

        # Determine strength from the event-owning team's perspective
        if team == "HOME":
            # For home team: check home skaters vs away skaters
            if empty_net:
                # Empty net situations
                if home_skaters == 6:
                    # Home has empty net (6 skaters)
                    if away_skaters < 5:
                        strength = (
                            "ENPP"  # Empty net + power play (opponent has < 5 skaters)
                        )
                    else:
                        strength = "EN"  # Empty net even strength (6v5)
                elif away_skaters == 6:
                    # Away has empty net (6 skaters) - HOME is defending against empty net
                    if home_skaters < 5:
                        strength = "PK"  # HOME is shorthanded (penalty kill situation)
                    else:
                        strength = (
                            "PK"  # HOME defending against empty net (disadvantage)
                        )
                elif home_skaters == 0:
                    # Home goalie pulled (0 skaters = empty net)
                    strength = "PK"  # Home is shorthanded
                elif away_skaters == 0:
                    # Away goalie pulled (0 skaters = empty net)
                    strength = "PP"  # Home is on power play
            elif home_skaters == 5 and away_skaters == 5:
                strength = "EV"
            elif home_skaters > away_skaters:
                strength = "PP"  # Home has more skaters = home power play
            elif home_skaters < away_skaters:
                if home_skaters < 5:
                    strength = (
                        "SH"  # Shorthanded (not penalty kill, just fewer skaters)
                    )
                else:
                    strength = "PK"  # Home has fewer skaters = home penalty kill
            else:
                strength = "EV"
        else:  # team == "AWAY"
            # For away team: check away skaters vs home skaters
            if empty_net:
                # Empty net situations
                if away_skaters == 6:
                    # Away has empty net (6 skaters)
                    if home_skaters < 5:
                        strength = (
                            "ENPP"  # Empty net + power play (opponent has < 5 skaters)
                        )
                    else:
                        strength = "EN"  # Empty net even strength (6v5)
                elif home_skaters == 6:
                    # Home has empty net (6 skaters) - AWAY is defending against empty net
                    if away_skaters < 5:
                        strength = "PK"  # AWAY is shorthanded (penalty kill situation)
                    else:
                        strength = (
                            "PK"  # AWAY defending against empty net (disadvantage)
                        )
                elif away_skaters == 0:
                    # Away goalie pulled (0 skaters = empty net)
                    strength = "PK"  # Away is shorthanded
                elif home_skaters == 0:
                    # Home goalie pulled (0 skaters = empty net)
                    strength = "PP"  # Away is on power play
            elif away_skaters == 5 and home_skaters == 5:
                strength = "EV"
            elif away_skaters > home_skaters:
                strength = "PP"  # Away has more skaters = away power play
            elif away_skaters < home_skaters:
                if away_skaters < 5:
                    strength = (
                        "SH"  # Shorthanded (not penalty kill, just fewer skaters)
                    )
                else:
                    strength = "PK"  # Away has fewer skaters = away penalty kill
            else:
                strength = "EV"

        # Get timestamp from game start and period time
        time_in_period = play.get("timeInPeriod", "00:00")
        period = play.get("periodDescriptor", {}).get("number", 1)

        # Parse game start time from NHL API
        game_start_str = game_data.get("startTimeUTC", "")

        if game_start_str:
            try:
                # Parse game start time (format: "YYYY-MM-DDTHH:MM:SSZ")
                game_start = datetime.fromisoformat(
                    game_start_str.replace("Z", "+00:00")
                )
                game_start_ts = game_start.timestamp()

                # Calculate elapsed time in period: timeInPeriod is MM:SS elapsed
                minutes, seconds = map(int, time_in_period.split(":"))
                elapsed_seconds = minutes * 60 + seconds  # Time elapsed in period

                # Total seconds from game start
                period_offset = (period - 1) * 1200  # 20 minutes per period
                total_elapsed = period_offset + elapsed_seconds
                timestamp = game_start_ts + total_elapsed
            except Exception:
                # Fallback to approximate timestamp
                timestamp = time.time()
        else:
            timestamp = time.time()

        # Get coordinates if available
        x = details.get("xCoord", random.uniform(-100, 100))
        y = details.get("yCoord", random.uniform(-42.5, 42.5))

        # Extract player ID based on event type
        player_id = None
        if mapped_type == "FACEOFF":
            player_id = details.get("winningPlayerId")
        elif mapped_type == "GOAL":
            player_id = details.get("scoringPlayerId")
        elif mapped_type in ["SHOT", "BLOCK"]:
            player_id = details.get("shootingPlayerId")
        elif mapped_type == "HIT":
            player_id = details.get("hittingPlayerId")
        elif mapped_type == "PENALTY":
            player_id = details.get("playerId")

        payload = GameEvent(
            game_id=game_id,
            ts=timestamp,
            team=team,
            event_type=mapped_type,
            strength=strength,
            empty_net=empty_net,
            player_id=player_id,
            x=x,
            y=y,
            shot_quality=random.random(),
        ).model_dump()

        # Insert into TimescaleDB
        try:
            if DATABASE_URL:
                async with await psycopg.AsyncConnection.connect(
                    DATABASE_URL, autocommit=True
                ) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "INSERT INTO events(ts, game_id, team, event_type, strength, x, y, shot_quality) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s)",
                            (
                                timestamp,
                                game_id,
                                team,
                                mapped_type,
                                strength,
                                payload["x"],
                                payload["y"],
                                payload["shot_quality"],
                            ),
                        )
                        # No commit needed with autocommit=True
        except Exception as e:
            logger.error(f"Database insert error: {e}", exc_info=True)

        sid = await r.xadd(STREAM_EVENTS, {"json": json.dumps(payload)})
        logger.debug(f"XADD events id={sid} {mapped_type} team={team}")

        # Minimal delay for fast ingestion (0.01s = ~100 events/sec)
        await asyncio.sleep(0.01)

    logger.info("NHL game events processed")


async def main():
    r = Redis.from_url(REDIS_URL, decode_responses=True)

    try:
        await ensure_streams(r)

        # Try NHL API first, fall back to synthetic
        if GAME_ID != "TEST_GAME":
            await produce_nhl_game(r, GAME_ID)
        else:
            await produce_synthetic_game(r, GAME_ID)
    finally:
        await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
