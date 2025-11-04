import asyncio
import os
import json
import random

import psycopg
from prometheus_client import Counter, Histogram, start_http_server
from redis.asyncio import Redis

from model import BaselineModel

DATABASE_URL = os.environ.get('DATABASE_URL', '')

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MODEL_ID = os.environ.get("MODEL_ID", "baseline-logit-v0")

STREAM_FEATURES = "features"
STREAM_PREDICTIONS = "predictions"
GROUP = "model_svc"
CONSUMER = f"model-{random.randint(1000,9999)}"

async def create_group_if_needed(r: Redis, stream: str, group: str):
    try:
        await r.xgroup_create(stream, group, id="$", mkstream=True)
        print(f"[model_svc] created group {group} on {stream}")
    except Exception:
        pass


# Prometheus metrics
PRED_COUNTER = Counter("model_predictions_total", "Total predictions produced")
PROC_TIME = Histogram("model_processing_seconds", "Model processing time", buckets=[0.005,0.01,0.025,0.05,0.1,0.25,0.5,1,2])

async def run_model():
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    await create_group_if_needed(r, STREAM_FEATURES, GROUP)
    start_http_server(9000)
    print('[model_svc] Prometheus metrics on :9000')
    model = BaselineModel()

    while True:
        resp = await r.xreadgroup(GROUP, CONSUMER, streams={STREAM_FEATURES: ">"}, count=10, block=1000)
        if not resp:
            continue

        for stream, messages in resp:
            for mid, fields in messages:
                try:
                    import time as _t
                    _t0 = _t.perf_counter()
                    features = json.loads(fields.get("json") or "{}")
                    game_id = features["game_id"]
                    home = int(features["home_score"])
                    away = int(features["away_score"])
                    ts = float(features["ts"])
                    # ts is already relative time from game start (computed in feature_state)
                    seconds_elapsed = ts

                    p_home = model.predict(home, away, seconds_elapsed)
                    out = {
                        "game_id": game_id,
                        "ts": ts,
                        "model_id": MODEL_ID,
                        "p_home_win": round(p_home, 4),
                    }
                    sid = await r.xadd(STREAM_PREDICTIONS, {"json": json.dumps(out)})
                    # Hot cache for REST
                    await r.hset(f"pred:{game_id}", mapping={k: str(v) for k, v in out.items()})
                    # Publish for WS broadcast
                    await r.publish(f"pred_stream:{game_id}", json.dumps(out))

                    
                    PRED_COUNTER.inc()
                    # Persist to TimescaleDB
                    try:
                        if DATABASE_URL:
                            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        "INSERT INTO predictions(ts, game_id, model_id, p_home_win) VALUES (to_timestamp(%s), %s, %s, %s)",
                                        (ts, game_id, MODEL_ID, float(out["p_home_win"])),
                                    )
                                    await conn.commit()
                    except Exception as e:
                        print("[model_svc][db] insert error:", e)
                    finally:
                        PROC_TIME.observe(_t.perf_counter() - _t0)

                    await r.xack(STREAM_FEATURES, GROUP, mid)
                    print(f"[model_svc] {mid} -> pred id={sid} game={game_id} p_home={out['p_home_win']}")
                except Exception as e:
                    print("[model_svc] error:", e)

async def main():
    await run_model()

if __name__ == "__main__":
    asyncio.run(main())
