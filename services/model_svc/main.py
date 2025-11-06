import asyncio
import os
import json
import random

import psycopg
from prometheus_client import Counter, Histogram, start_http_server
from redis.asyncio import Redis

from model_loader import load_production_model
from feature_engineer import engineer_features
from ab_testing import create_ab_test_router, create_ab_test_tracker

DATABASE_URL = os.environ.get("DATABASE_URL", "")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Use improved trained model by default, fallback to baseline if not available
MODEL_ID = os.environ.get("MODEL_ID", "lightgbm_20251104_121934_d9b5b03f")

# A/B testing configuration
AB_TEST_ENABLED = os.environ.get("AB_TEST_ENABLED", "false").lower() == "true"

STREAM_FEATURES = "features"
STREAM_PREDICTIONS = "predictions"
GROUP = "model_svc"
CONSUMER = f"model-{random.randint(1000, 9999)}"


async def create_group_if_needed(r: Redis, stream: str, group: str):
    try:
        await r.xgroup_create(stream, group, id="$", mkstream=True)
        print(f"[model_svc] created group {group} on {stream}")
    except Exception:
        pass


# Prometheus metrics
PRED_COUNTER = Counter("model_predictions_total", "Total predictions produced")
PROC_TIME = Histogram(
    "model_processing_seconds",
    "Model processing time",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2],
)


async def run_model():
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    await create_group_if_needed(r, STREAM_FEATURES, GROUP)
    start_http_server(9000)
    print("[model_svc] Prometheus metrics on :9000")

    # Initialize A/B testing if enabled
    ab_router = None
    ab_tracker = None
    model_loaders = {}  # Cache for multiple models

    if AB_TEST_ENABLED:
        ab_router = create_ab_test_router()
        ab_tracker = create_ab_test_tracker(DATABASE_URL)

        if ab_router.is_enabled():
            print(
                f"[model_svc] A/B testing enabled with {len(ab_router.get_all_variants())} variants"
            )
            for variant in ab_router.get_all_variants():
                if variant.enabled:
                    print(
                        f"  - {variant.name} ({variant.model_id}): {variant.traffic_percentage}%"
                    )
                    # Pre-load all variants
                    loader = load_production_model(variant.model_id)
                    model_loaders[variant.model_id] = loader
                    print(f"    Loaded {loader.model_type} model")
        else:
            print("[model_svc] A/B testing configured but not enabled (single variant)")
            ab_router = None

    # Load default model if A/B testing not enabled
    if not ab_router:
        model_loader = load_production_model()
        model = model_loader.model
        model_type = model_loader.model_type
        print(f"[model_svc] Loaded {model_type} model: {MODEL_ID}")
    else:
        # Use first variant as default fallback
        default_variant = (
            ab_router.get_all_variants()[0] if ab_router.get_all_variants() else None
        )
        if default_variant:
            model_loader = model_loaders.get(
                default_variant.model_id
            ) or load_production_model(default_variant.model_id)
            model = model_loader.model
            model_type = model_loader.model_type
        else:
            model_loader = load_production_model()
            model = model_loader.model
            model_type = model_loader.model_type

    while True:
        resp = await r.xreadgroup(
            GROUP, CONSUMER, streams={STREAM_FEATURES: ">"}, count=10, block=1000
        )
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

                    # A/B testing: select variant if enabled
                    selected_variant = None
                    selected_model = model
                    selected_model_type = model_type
                    selected_model_id = MODEL_ID

                    if ab_router and ab_router.is_enabled():
                        variant = ab_router.select_variant(game_id=game_id)
                        if variant:
                            selected_variant = variant
                            selected_model_id = variant.model_id
                            # Get or load model for this variant
                            if variant.model_id in model_loaders:
                                variant_loader = model_loaders[variant.model_id]
                            else:
                                variant_loader = load_production_model(variant.model_id)
                                model_loaders[variant.model_id] = variant_loader

                            selected_model = variant_loader.model
                            selected_model_type = variant_loader.model_type

                    # Prepare features for prediction
                    if selected_model_type == "baseline":
                        p_home = selected_model.predict(home, away, seconds_elapsed)
                        raw_features = {
                            "home_score": home,
                            "away_score": away,
                            "seconds_elapsed": seconds_elapsed,
                            "strength": features.get("strength", "EV"),
                            "last_event": features.get("last_event", "FACEOFF"),
                        }
                        engineered_features = raw_features
                    else:
                        # Trained model needs full engineered feature set
                        import pandas as pd

                        # Add raw features needed for engineering
                        raw_features = {
                            "home_score": home,
                            "away_score": away,
                            "seconds_elapsed": seconds_elapsed,
                            "strength": features.get("strength", "EV"),
                            "last_event": features.get("last_event", "FACEOFF"),
                        }
                        # Engineer features matching training pipeline
                        engineered_features = engineer_features(raw_features)
                        # Create DataFrame with engineered features
                        feature_df = pd.DataFrame([engineered_features])
                        p_home = float(selected_model.predict(feature_df)[0])

                    # Log prediction for A/B testing
                    if ab_tracker and selected_variant:
                        from datetime import datetime

                        ab_tracker.log_prediction(
                            game_id=game_id,
                            model_id=selected_model_id,
                            variant_name=selected_variant.name,
                            prediction=p_home,
                            features=engineered_features,
                            timestamp=datetime.fromtimestamp(ts) if ts else None,
                        )

                    out = {
                        "game_id": game_id,
                        "ts": ts,
                        "model_id": selected_model_id,
                        "p_home_win": round(p_home, 4),
                    }
                    if selected_variant:
                        out["variant_name"] = selected_variant.name
                    sid = await r.xadd(STREAM_PREDICTIONS, {"json": json.dumps(out)})
                    # Hot cache for REST
                    await r.hset(
                        f"pred:{game_id}", mapping={k: str(v) for k, v in out.items()}
                    )
                    # Publish for WS broadcast
                    await r.publish(f"pred_stream:{game_id}", json.dumps(out))

                    PRED_COUNTER.inc()
                    # Persist to TimescaleDB
                    # Note: ts in features is relative game time (0-3600s), not Unix timestamp
                    # We need to store the actual prediction timestamp (current time) for history queries
                    # The relative time is stored in the 'ts' field of the prediction output for reference
                    try:
                        if DATABASE_URL:
                            import time

                            # Use current Unix timestamp for database storage
                            # This allows history queries to work correctly with game start time calculation
                            prediction_timestamp = time.time()
                            async with await psycopg.AsyncConnection.connect(
                                DATABASE_URL
                            ) as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        "INSERT INTO predictions(ts, game_id, model_id, p_home_win) VALUES (to_timestamp(%s), %s, %s, %s)",
                                        (
                                            prediction_timestamp,
                                            game_id,
                                            selected_model_id,
                                            float(out["p_home_win"]),
                                        ),
                                    )
                                    await conn.commit()
                    except Exception as e:
                        print("[model_svc][db] insert error:", e)
                    finally:
                        PROC_TIME.observe(_t.perf_counter() - _t0)

                    await r.xack(STREAM_FEATURES, GROUP, mid)
                    print(
                        f"[model_svc] {mid} -> pred id={sid} game={game_id} p_home={out['p_home_win']}"
                    )
                except Exception as e:
                    print("[model_svc] error:", e)


async def main():
    await run_model()


if __name__ == "__main__":
    asyncio.run(main())
