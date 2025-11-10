import asyncio
import json
import logging
import os
import random
import sys
from typing import Dict, Optional

import psycopg
from redis.asyncio import Redis

# Add parent directory to path for common imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from common.constants import (
    REDIS_DEFAULT_URL,
    STREAM_EVENTS,
    STREAM_FEATURES,
    GROUP_FEATURE_STATE,
    CONSUMER_ID_MIN,
    CONSUMER_ID_MAX,
    DATABASE_AUTOCOMMIT,
    EVENT_PROCESSING_COUNT,
    EVENT_PROCESSING_BLOCK_MS,
)
from common.logging_config import setup_logger
from state import GameState

# Configure logging
logger = setup_logger("feature_state", level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", REDIS_DEFAULT_URL)
CONSUMER = f"fs-{random.randint(CONSUMER_ID_MIN, CONSUMER_ID_MAX)}"
db_conn: Optional[psycopg.AsyncConnection] = None


async def create_group_if_needed(r: Redis, stream: str, group: str) -> None:
    """
    Create a Redis consumer group if it doesn't exist.

    Args:
        r: Redis client instance
        stream: Stream name
        group: Consumer group name
    """
    try:
        # MKSTREAM ensures the stream exists
        await r.xgroup_create(stream, group, id="$", mkstream=True)
        logger.info(f"Created consumer group {group} on stream {stream}")
    except Exception as e:
        # Group probably exists, log at debug level
        logger.debug(f"Consumer group {group} already exists on {stream}: {e}")


async def get_db_connection() -> Optional[psycopg.AsyncConnection]:
    """
    Return a cached async DB connection to avoid reconnecting per event.

    Returns:
        Database connection or None if DATABASE_URL not configured
    """
    global db_conn
    if not DATABASE_URL:
        return None
    if db_conn is None or db_conn.closed:
        db_conn = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=DATABASE_AUTOCOMMIT)
    return db_conn


async def process_events() -> None:
    """
    Main event processing loop. Reads from events stream and produces features.
    """
    global db_conn
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    await create_group_if_needed(r, STREAM_EVENTS, GROUP_FEATURE_STATE)
    states: Dict[str, GameState] = {}
    game_starts: Dict[str, float] = {}  # Track first event time per game

    logger.info(f"Feature state service started. Consumer: {CONSUMER}")

    while True:
        resp = await r.xreadgroup(
            GROUP_FEATURE_STATE,
            CONSUMER,
            streams={STREAM_EVENTS: ">"},
            count=EVENT_PROCESSING_COUNT,
            block=EVENT_PROCESSING_BLOCK_MS,
        )
        if not resp:
            continue

        for _, messages in resp:
            for mid, fields in messages:
                try:
                    payload = json.loads(fields.get("json") or "{}")
                    game_id = payload["game_id"]
                    ev = payload["event_type"]
                    team = payload["team"]
                    ts = payload["ts"]
                    strength = payload.get("strength", "EV")
                    empty_net = payload.get("empty_net", False)
                    player_id = payload.get("player_id")

                    # Check if we need to reset this game's state (new ingestion)
                    reset_flag = await r.get(f"reset_game:{game_id}")
                    if reset_flag:
                        # Reset in-memory state for this game
                        if game_id in states:
                            del states[game_id]
                        if game_id in game_starts:
                            del game_starts[game_id]
                        # Clear the reset flag
                        await r.delete(f"reset_game:{game_id}")
                        await r.delete(f"game_start_ts:{game_id}")
                        logger.info(f"Reset state for game {game_id}")

                    # Track first event time for this game
                    if game_id not in game_starts:
                        cached_start = await r.get(f"game_start_ts:{game_id}")
                        start_ts = None
                        if cached_start:
                            try:
                                start_ts = float(cached_start)
                            except (TypeError, ValueError):
                                start_ts = None
                        if start_ts is None:
                            start_ts = ts
                            await r.set(f"game_start_ts:{game_id}", str(ts))
                        game_starts[game_id] = start_ts

                    relative_ts = max(0.0, ts - game_starts[game_id])
                    state = states.get(game_id) or GameState(
                        game_id=game_id, ts=relative_ts
                    )
                    state.ts = relative_ts
                    state.strength = strength
                    state.empty_net = empty_net
                    # Only update last_event and last_player_id if this event has a player
                    # This prevents showing "None" for events like stoppages or game-end
                    if player_id is not None:
                        state.last_event = ev
                        state.last_player_id = player_id
                    if ev == "GOAL":
                        state.goal(team)

                    states[game_id] = state

                    features = state.model_dump()

                    # Persist to TimescaleDB using a shared connection
                    try:
                        conn = await get_db_connection()
                        if conn:
                            async with conn.cursor() as cur:
                                await cur.execute(
                                    "INSERT INTO features(ts, game_id, home_score, away_score, strength, last_event) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s)",
                                    (
                                        ts,
                                        game_id,
                                        features["home_score"],
                                        features["away_score"],
                                        features["strength"],
                                        features["last_event"],
                                    ),
                                )
                    except Exception as e:
                        logger.error(f"Database insert error: {e}", exc_info=True)
                        # Close and reset the global connection on error
                        if db_conn:
                            try:
                                await db_conn.close()
                            except Exception:
                                pass
                        db_conn = None

                    await r.xadd(STREAM_FEATURES, {"json": json.dumps(features)})
                    # cache state
                    await r.hset(
                        f"state:{game_id}",
                        mapping={k: str(v) for k, v in features.items()},
                    )
                    await r.xack(STREAM_EVENTS, GROUP_FEATURE_STATE, mid)
                    logger.info(
                        f"Processed event {mid} for game {game_id}: {features['home_score']}-{features['away_score']} ({features['strength']})"
                    )
                except Exception as e:
                    logger.error(f"Error processing event: {e}", exc_info=True)


async def main() -> None:
    """Main entry point for feature state service."""
    try:
        await process_events()
    except KeyboardInterrupt:
        logger.info("Feature state service shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in feature state service: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
