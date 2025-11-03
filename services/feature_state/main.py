import asyncio
import json
import os
import random
from typing import Dict

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

async def process_events():
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    await create_group_if_needed(r, STREAM_EVENTS, GROUP)
    states: Dict[str, GameState] = {}
    game_starts: Dict[str, float] = {}  # Track first event time per game

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

                    # Track first event time for this game
                    if game_id not in game_starts:
                        game_starts[game_id] = ts
                    
                    state = states.get(game_id) or GameState(game_id=game_id, ts=ts)
                    state.ts = ts - game_starts[game_id]  # Convert to relative time
                    state.strength = strength
                    state.empty_net = empty_net
                    state.last_event = ev
                    if ev == "GOAL":
                        state.goal(team)

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
