import asyncio
import json
import logging
import os
import random
import sys
import time
from typing import Optional

import psycopg
from prometheus_client import Counter, Histogram, start_http_server
from redis.asyncio import Redis

# Add parent directory to path for common imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from common.constants import (
    REDIS_DEFAULT_URL,
    STREAM_FEATURES,
    STREAM_PREDICTIONS,
    GROUP_MODEL_SVC,
    CONSUMER_ID_MIN,
    CONSUMER_ID_MAX,
    DATABASE_AUTOCOMMIT,
    EVENT_PROCESSING_COUNT,
    EVENT_PROCESSING_BLOCK_MS,
    PROMETHEUS_PORT,
    PROMETHEUS_LATENCY_BUCKETS,
    MODEL_DEFAULT_ID,
    MODEL_TYPE_BASELINE,
)
from common.logging_config import setup_logger
from model_loader import load_production_model
from feature_engineer import engineer_features
from ab_testing import create_ab_test_router, create_ab_test_tracker

# Configure logging
logger = setup_logger("model_svc", level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
REDIS_URL = os.environ.get("REDIS_URL", REDIS_DEFAULT_URL)
MODEL_ID = os.environ.get("MODEL_ID", MODEL_DEFAULT_ID)

# A/B testing configuration
AB_TEST_ENABLED = os.environ.get("AB_TEST_ENABLED", "false").lower() == "true"

CONSUMER = f"model-{random.randint(CONSUMER_ID_MIN, CONSUMER_ID_MAX)}"
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
        await r.xgroup_create(stream, group, id="$", mkstream=True)
        logger.info(f"Created consumer group {group} on stream {stream}")
    except Exception as e:
        logger.debug(f"Consumer group {group} already exists on {stream}: {e}")


async def get_db_connection() -> Optional[psycopg.AsyncConnection]:
    """
    Return a cached async DB connection for inserts.

    Returns:
        Database connection or None if DATABASE_URL not configured
    """
    global db_conn
    if not DATABASE_URL:
        return None
    if db_conn is None or db_conn.closed:
        db_conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
        db_conn.autocommit = DATABASE_AUTOCOMMIT
    return db_conn


# Prometheus metrics
PRED_COUNTER = Counter("model_predictions_total", "Total predictions produced")
PROC_TIME = Histogram(
    "model_processing_seconds",
    "Model processing time",
    buckets=PROMETHEUS_LATENCY_BUCKETS,
)


async def run_model() -> None:
    """
    Main model inference loop. Reads features and produces predictions.
    """
    global db_conn
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    await create_group_if_needed(r, STREAM_FEATURES, GROUP_MODEL_SVC)
    start_http_server(PROMETHEUS_PORT)
    logger.info(f"Prometheus metrics available on port {PROMETHEUS_PORT}")
    logger.info(f"Model service started. Consumer: {CONSUMER}")

    # Initialize A/B testing if enabled
    ab_router = None
    ab_tracker = None
    model_loaders = {}  # Cache for multiple models

    if AB_TEST_ENABLED:
        ab_router = create_ab_test_router()
        ab_tracker = create_ab_test_tracker(DATABASE_URL)

        if ab_router.is_enabled():
            logger.info(
                f"A/B testing enabled with {len(ab_router.get_all_variants())} variants"
            )
            for variant in ab_router.get_all_variants():
                if variant.enabled:
                    logger.info(
                        f"  - {variant.name} ({variant.model_id}): {variant.traffic_percentage}%"
                    )
                    # Pre-load all variants
                    loader = load_production_model(variant.model_id)
                    model_loaders[variant.model_id] = loader
                    logger.info(f"    Loaded {loader.model_type} model")
        else:
            logger.info("A/B testing configured but not enabled (single variant)")
            ab_router = None

    # Load default model if A/B testing not enabled
    if not ab_router:
        model_loader = load_production_model()
        model = model_loader.model
        model_type = model_loader.model_type
        logger.info(f"Loaded {model_type} model: {MODEL_ID}")
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
            GROUP_MODEL_SVC,
            CONSUMER,
            streams={STREAM_FEATURES: ">"},
            count=EVENT_PROCESSING_COUNT,
            block=EVENT_PROCESSING_BLOCK_MS,
        )
        if not resp:
            continue

        for _, messages in resp:
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
                    game_start_ts = None
                    start_ts_raw = await r.get(f"game_start_ts:{game_id}")
                    if start_ts_raw is not None:
                        try:
                            game_start_ts = float(start_ts_raw)
                        except (TypeError, ValueError):
                            game_start_ts = None
                    prediction_event_ts = (
                        game_start_ts + seconds_elapsed
                        if game_start_ts is not None
                        else None
                    )

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
                    if selected_model_type == MODEL_TYPE_BASELINE:
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
                            timestamp=(
                                datetime.fromtimestamp(prediction_event_ts)
                                if prediction_event_ts
                                else None
                            ),
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
                    conn: Optional[psycopg.AsyncConnection] = None
                    try:
                        if DATABASE_URL:
                            prediction_timestamp = (
                                prediction_event_ts
                                if prediction_event_ts is not None
                                else time.time()
                            )
                            conn = await get_db_connection()
                            if conn:
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
                    except Exception as e:
                        logger.error(f"Database insert error: {e}", exc_info=True)
                        if conn:
                            await conn.close()
                        db_conn = None
                    finally:
                        PROC_TIME.observe(_t.perf_counter() - _t0)

                    await r.xack(STREAM_FEATURES, GROUP_MODEL_SVC, mid)
                    logger.info(
                        f"Prediction {sid} for game {game_id}: p_home={out['p_home_win']}"
                    )
                except Exception as e:
                    logger.error(f"Error processing feature event: {e}", exc_info=True)


async def main() -> None:
    """Main entry point for model service."""
    try:
        await run_model()
    except KeyboardInterrupt:
        logger.info("Model service shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in model service: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
