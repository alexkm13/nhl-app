import asyncio
import json
import os
import random
import time
from typing import Dict

import httpx
import psycopg
from redis.asyncio import Redis
from state import GameState

DATABASE_URL = os.environ.get('DATABASE_URL', '')

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
STREAM_EVENTS = "events"
STREAM_FEATURES = "features"
GROUP = "feature_state"
CONSUMER = f"fs-{random.randint(1000,9999)}"

async def create_group_if_needed(r: Redis, stream: str, group: str):
    try:
        # MKSTREAM ensures the stream exists
        await r.xgroup_create(stream, group, id="$", mkstream=True)
        print(f"[feature_state] created group {group} on {stream}")
    except Exception:
        # Group probably exists
        pass

async def fetch_boxscore_score(game_id: str) -> tuple[int, int]:
    """Fetch current score from NHL boxscore API."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            boxscore_response = await client.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/boxscore")
            if boxscore_response.status_code == 200:
                boxscore_data = boxscore_response.json()
                home_team = boxscore_data.get("homeTeam", {})
                away_team = boxscore_data.get("awayTeam", {})
                current_home_score = home_team.get("score", 0) or boxscore_data.get("homeScore", 0)
                current_away_score = away_team.get("score", 0) or boxscore_data.get("awayScore", 0)
                return (int(current_home_score), int(current_away_score))
    except Exception as e:
        print(f"[feature_state] Error fetching boxscore for {game_id}: {e}")
    return (None, None)

async def sync_state_with_boxscore(state: GameState, game_id: str) -> bool:
    """Sync game state with current boxscore. Returns True if sync occurred."""
    home_score, away_score = await fetch_boxscore_score(game_id)
    if home_score is not None and away_score is not None:
        if state.home_score != home_score or state.away_score != away_score:
            old_score = f"{state.home_score}-{state.away_score}"
            state.home_score = home_score
            state.away_score = away_score
            print(f"[feature_state] Synced state for {game_id}: {old_score} -> {home_score}-{away_score}")
            return True
    return False

async def process_events():
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    await create_group_if_needed(r, STREAM_EVENTS, GROUP)
    states: Dict[str, GameState] = {}
    game_starts: Dict[str, float] = {}  # Track first event time per game
    last_boxscore_sync: Dict[str, float] = {}  # Track last boxscore sync per game

    while True:
        resp = await r.xreadgroup(GROUP, CONSUMER, streams={STREAM_EVENTS: ">"}, count=10, block=1000)
        if not resp:
            continue

        for stream, messages in resp:
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
                        if game_id in last_boxscore_sync:
                            del last_boxscore_sync[game_id]
                        
                        # CRITICAL: Sync state with current boxscore after reset
                        # This ensures we don't lose the current score when resetting
                        home_score, away_score = await fetch_boxscore_score(game_id)
                        if home_score is not None and away_score is not None:
                            if home_score > 0 or away_score > 0:
                                # Initialize state with current score
                                state = GameState(game_id=game_id, ts=ts)
                                state.home_score = home_score
                                state.away_score = away_score
                                states[game_id] = state
                                print(f"[feature_state] Reset state for game {game_id} - synced with boxscore: {home_score}-{away_score}")
                            else:
                                print(f"[feature_state] Reset state for game {game_id} - no score in boxscore, starting from 0-0")
                        else:
                            print(f"[feature_state] Reset state for game {game_id} - could not fetch boxscore, starting from 0-0")
                        
                        # Clear the reset flag
                        await r.delete(f"reset_game:{game_id}")

                    # Track first event time for this game
                    if game_id not in game_starts:
                        game_starts[game_id] = ts
                    
                    # Initialize state for new game, sync with boxscore if first time
                    state = states.get(game_id)
                    if state is None:
                        # New game - initialize state and sync with boxscore
                        state = GameState(game_id=game_id, ts=ts)
                        home_score, away_score = await fetch_boxscore_score(game_id)
                        if home_score is not None and away_score is not None:
                            state.home_score = home_score
                            state.away_score = away_score
                            print(f"[feature_state] Initialized state for {game_id} - synced with boxscore: {home_score}-{away_score}")
                            # If game has already started (score > 0), skip old events and use current state
                            if home_score > 0 or away_score > 0:
                                # Game has already started - skip processing old events
                                # Instead, publish current state immediately
                                state.ts = ts - game_starts[game_id] if game_id in game_starts else 0
                                features = state.model_dump()
                                await r.xadd(STREAM_FEATURES, {"json": json.dumps(features)})
                                await r.hset(f"state:{game_id}", mapping={k: str(v) for k, v in features.items()})
                                await r.set(f"last_published_score:{game_id}", f"{home_score}-{away_score}")
                                print(f"[feature_state] Published initial state for {game_id}: {home_score}-{away_score} (skipping old events)")
                        states[game_id] = state
                        last_boxscore_sync[game_id] = ts
                    else:
                        # Existing state - ALWAYS sync with boxscore before processing event
                        # This ensures state is always correct before generating features
                        synced = await sync_state_with_boxscore(state, game_id)
                        if synced:
                            # If sync occurred, publish updated features immediately
                            # Use current timestamp for the features
                            state.ts = ts - game_starts[game_id]  # Ensure relative time is correct
                            features = state.model_dump()
                            await r.xadd(STREAM_FEATURES, {"json": json.dumps(features)})
                            await r.hset(f"state:{game_id}", mapping={k: str(v) for k, v in features.items()})
                            print(f"[feature_state] Published updated features for {game_id} after boxscore sync: {features['home_score']}-{features['away_score']}")
                        
                        # ALWAYS check if we need to publish current state features
                        # This ensures model has latest score even if no sync occurred
                        # Check if last published feature matches current state
                        current_state_score = f"{state.home_score}-{state.away_score}"
                        last_sync_score_key = f"last_published_score:{game_id}"
                        last_published_score = await r.get(last_sync_score_key)
                        
                        if last_published_score != current_state_score:
                            # Publish current state features to ensure model has latest score
                            state.ts = ts - game_starts[game_id]  # Ensure relative time is correct
                            features = state.model_dump()
                            await r.xadd(STREAM_FEATURES, {"json": json.dumps(features)})
                            await r.hset(f"state:{game_id}", mapping={k: str(v) for k, v in features.items()})
                            await r.set(last_sync_score_key, current_state_score)
                            print(f"[feature_state] Published current state features for {game_id}: {features['home_score']}-{features['away_score']}")
                        
                        # Update last sync time
                        last_boxscore_sync[game_id] = time.time()
                    state.ts = ts - game_starts[game_id]  # Convert to relative time
                    state.strength = strength
                    state.empty_net = empty_net
                    # Update last_event and last_player_id if this event has a player
                    # This prevents showing "None" for events like stoppages or game-end
                    if player_id is not None:
                        state.last_event = ev
                        state.last_player_id = player_id
                    
                    # CRITICAL: Update score BEFORE updating last_event for goals
                    # This ensures score change is reflected immediately
                    if ev == "GOAL":
                        state.goal(team)
                        # Ensure last_event is set to GOAL for goal events (even if player_id is None)
                        state.last_event = "GOAL"
                        print(f"[feature_state] GOAL! {team} scores - {game_id}: {state.home_score}-{state.away_score}")

                    states[game_id] = state

                    features = state.model_dump()
                    
                    # Persist to TimescaleDB
                    try:
                        if DATABASE_URL:
                            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        "INSERT INTO features(ts, game_id, home_score, away_score, strength, last_event) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s)",
                                        (ts, game_id, features["home_score"], features["away_score"], features["strength"], features["last_event"]),
                                    )
                                    await conn.commit()
                    except Exception as e:
                        print("[feature_state][db] insert error:", e)

                    # CRITICAL: Only publish features if we have a valid state
                    # Skip publishing if state is 0-0 and we know the actual score is different
                    # This prevents publishing stale 0-0 features
                    if features['home_score'] == 0 and features['away_score'] == 0:
                        # Check if boxscore has different score
                        home_score_check, away_score_check = await fetch_boxscore_score(game_id)
                        if home_score_check is not None and away_score_check is not None:
                            if home_score_check > 0 or away_score_check > 0:
                                # Actual score is different - update state and skip this event
                                state.home_score = home_score_check
                                state.away_score = away_score_check
                                features = state.model_dump()
                                # Don't publish this stale 0-0 feature
                                await r.xack(STREAM_EVENTS, GROUP, mid)
                                continue

                    await r.xadd(STREAM_FEATURES, {"json": json.dumps(features)})
                    # cache state
                    await r.hset(f"state:{game_id}", mapping={k: str(v) for k, v in features.items()})
                    await r.xack(STREAM_EVENTS, GROUP, mid)
                    print(f"[feature_state] {mid} -> features for {game_id}: {features['home_score']}-{features['away_score']} ({features['strength']})")
                except Exception as e:
                    print("[feature_state] error:", e)

async def main():
    await process_events()

if __name__ == "__main__":
    asyncio.run(main())
