import asyncio
import json
import os
import random
import time

import psycopg
from redis.asyncio import Redis

from events import GameEvent

DATABASE_URL = os.environ.get('DATABASE_URL', '')

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
GAME_ID = os.environ.get("GAME_ID", "TEST_GAME")

STREAM_EVENTS = "events"
GROUP = "ingestors"
CONSUMER = f"producer-{random.randint(1000,9999)}"  # not used for producer but kept symmetrical

async def ensure_streams(r: Redis):
    # Create an empty stream so downstream groups can be created safely.
    await r.xadd(STREAM_EVENTS, {"bootstrap": "1"}, id="*")

async def produce_synthetic_game(r: Redis, game_id: str):
    print(f"[ingestor] starting synthetic game for {game_id}")
    start = time.time()
    clock_total = 20 * 60  # 20 minutes demo

    t = 0.0
    random.seed(42)
    while t < clock_total:
        await asyncio.sleep(0.5)  # emit ~2 events/sec

        # Random event selection
        ev_choice = random.choices(
            ["SHOT", "FACEOFF", "HIT", "PENALTY"],
            weights=[0.6, 0.1, 0.2, 0.1],
            k=1,
        )[0]
        team = random.choice(["HOME", "AWAY"])

        # Occasional goals
        if ev_choice == "SHOT" and random.random() < 0.07:
            ev_choice = "GOAL"

        strength = "EV"
        if random.random() < 0.08:
            strength = random.choice(["PP", "PK"])

        now = time.time()
        payload = GameEvent(
            game_id=game_id,
            ts=now,
            team=team,
            event_type=ev_choice,
            strength=strength,
            x=random.uniform(-100, 100),
            y=random.uniform(-42.5, 42.5),
            shot_quality=random.random(),
        ).model_dump()

        
        # Insert into TimescaleDB (optional)
        try:
            if DATABASE_URL:
                async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "INSERT INTO events(ts, game_id, team, event_type, strength, x, y, shot_quality) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s)",
                            (now, game_id, team, ev_choice, strength, payload["x"], payload["y"], payload["shot_quality"]),
                        )
                        await conn.commit()
        except Exception as e:
            print("[ingestor][db] insert error:", e)

        sid = await r.xadd(STREAM_EVENTS, {"json": json.dumps(payload)})
        print(f"[ingestor] XADD events id={sid} {payload['event_type']} team={team}")
        t = now - start

    print("[ingestor] game complete.")

async def main():
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await ensure_streams(r)
        await produce_synthetic_game(r, GAME_ID)
    finally:
        await r.aclose()

if __name__ == "__main__":
    asyncio.run(main())
