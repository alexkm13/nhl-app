import asyncio
import json
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict

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
    MODEL_PREDICTION_INTERVAL_SECONDS,
    MODEL_PREDICTION_MAX_WORKERS,
    MODEL_PREDICTION_CRITICAL_TIME_SECONDS,
    MODEL_PREDICTION_CLOSE_GAME_THRESHOLD,
    SIGNIFICANT_EVENTS,
    CONDITIONAL_SIGNIFICANT_EVENTS,
    GAME_TOTAL_REGULATION_TIME_SECONDS,
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

# Prediction throttling configuration (can be overridden by env vars)
PREDICTION_INTERVAL = float(
    os.environ.get("PREDICTION_INTERVAL_SECONDS", MODEL_PREDICTION_INTERVAL_SECONDS)
)

# Force prediction interval - ensures predictions are generated regularly even if no significant events
FORCE_PREDICTION_INTERVAL = float(
    os.environ.get("FORCE_PREDICTION_INTERVAL_SECONDS", 30.0)
)  # Force prediction every 30 seconds

CONSUMER = f"model-{random.randint(CONSUMER_ID_MIN, CONSUMER_ID_MAX)}"
db_conn: Optional[psycopg.AsyncConnection] = None

# ThreadPool for non-blocking model inference
INFERENCE_EXECUTOR = ThreadPoolExecutor(max_workers=MODEL_PREDICTION_MAX_WORKERS)


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
        db_conn = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=DATABASE_AUTOCOMMIT)
    return db_conn


# Prometheus metrics
PRED_COUNTER = Counter("model_predictions_total", "Total predictions produced")
PRED_SKIPPED = Counter("model_predictions_skipped_total", "Predictions skipped by throttling")
INFERENCE_TIME = Histogram(
    "model_inference_seconds",
    "Pure model inference time",
    buckets=PROMETHEUS_LATENCY_BUCKETS,
)
PROC_TIME = Histogram(
    "model_processing_seconds",
    "Total processing time including feature engineering",
    buckets=PROMETHEUS_LATENCY_BUCKETS,
)


async def predict_async(model, model_type: str, raw_features: Dict) -> float:
    """
    Run model prediction asynchronously in thread pool to avoid blocking event loop.

    Args:
        model: Model instance (baseline or trained LightGBM)
        model_type: Type of model ("baseline" or trained model type)
        raw_features: Raw feature dictionary

    Returns:
        Predicted home team win probability (0.0 to 1.0)
    """
    loop = asyncio.get_event_loop()
    inference_start = time.perf_counter()

    if model_type == MODEL_TYPE_BASELINE:
        # Baseline model prediction (simple formula)
        home_score = raw_features.get("home_score", 0)
        away_score = raw_features.get("away_score", 0)
        seconds_elapsed = raw_features.get("seconds_elapsed", 0)

        # Run in executor to avoid blocking (even though it's fast)
        p_home = await loop.run_in_executor(
            INFERENCE_EXECUTOR,
            model.predict,
            home_score,
            away_score,
            seconds_elapsed,
        )
    else:
        # Trained model requires feature engineering
        import pandas as pd

        # Engineer features (fast, but run in executor for consistency)
        def _engineer_and_predict():
            engineered = engineer_features(raw_features)
            feature_df = pd.DataFrame([engineered])
            return float(model.predict(feature_df)[0])

        p_home = await loop.run_in_executor(INFERENCE_EXECUTOR, _engineer_and_predict)

    inference_time = time.perf_counter() - inference_start
    INFERENCE_TIME.observe(inference_time)

    if inference_time > 0.1:  # Log slow predictions (>100ms)
        logger.warning(
            f"Slow inference: {inference_time*1000:.1f}ms for model_type={model_type}"
        )

    return p_home


def should_predict(
    game_id: str,
    features: Dict,
    last_prediction_times: Dict[str, float],
    last_forced_prediction_times: Dict[str, float],
    current_time: float,
) -> bool:
    """
    Determine if we should generate a prediction for this feature event.

    Uses smart throttling to balance accuracy with performance:
    - Force prediction every FORCE_PREDICTION_INTERVAL seconds (ensures regular updates)
    - Always predict on significant events (goals, penalties)
    - Always predict in critical game moments (last 5 minutes)
    - Predict on shots/blocks in close games
    - Otherwise, throttle to configured interval

    Args:
        game_id: Game identifier
        features: Feature dictionary with game state
        last_prediction_times: Dict tracking last prediction time per game
        last_forced_prediction_times: Dict tracking last forced prediction time per game
        current_time: Current timestamp

    Returns:
        True if should predict, False if should skip
    """
    # Get game state
    last_event = features.get("last_event", "")
    home_score = int(features.get("home_score", 0))
    away_score = int(features.get("away_score", 0))
    seconds_elapsed = float(features.get("seconds_elapsed", 0))

    # Calculate time remaining
    time_remaining = GAME_TOTAL_REGULATION_TIME_SECONDS - seconds_elapsed
    score_diff = abs(home_score - away_score)

    # Check forced prediction timer - ensures predictions are generated regularly
    # This guarantees at least one prediction every FORCE_PREDICTION_INTERVAL seconds
    last_forced_pred_time = last_forced_prediction_times.get(game_id, 0)
    time_since_last_forced = current_time - last_forced_pred_time
    if time_since_last_forced >= FORCE_PREDICTION_INTERVAL:
        logger.debug(
            f"Forcing prediction due to timer: {time_since_last_forced:.1f}s since last forced prediction "
            f"(interval={FORCE_PREDICTION_INTERVAL}s)"
        )
        last_forced_prediction_times[game_id] = current_time
        return True

    # Always predict on significant events
    if last_event in SIGNIFICANT_EVENTS:
        logger.debug(f"Predicting on significant event: {last_event}")
        return True

    # Always predict in critical time (last 5 minutes)
    if time_remaining < MODEL_PREDICTION_CRITICAL_TIME_SECONDS:
        logger.debug(f"Predicting in critical time: {time_remaining:.0f}s remaining")
        return True

    # Predict on conditional events in close games
    if (
        score_diff <= MODEL_PREDICTION_CLOSE_GAME_THRESHOLD
        and last_event in CONDITIONAL_SIGNIFICANT_EVENTS
    ):
        logger.debug(f"Predicting on {last_event} in close game (diff={score_diff})")
        return True

    # Check time-based throttling
    last_pred_time = last_prediction_times.get(game_id, 0)
    time_since_last = current_time - last_pred_time

    if time_since_last >= PREDICTION_INTERVAL:
        logger.debug(
            f"Predicting due to interval: {time_since_last:.1f}s since last prediction"
        )
        return True

    # Skip this prediction
    logger.debug(
        f"Skipping prediction: {time_since_last:.1f}s since last "
        f"(interval={PREDICTION_INTERVAL}s, forced_interval={FORCE_PREDICTION_INTERVAL}s)"
    )
    return False


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

    # Track last prediction time per game for throttling
    last_prediction_times: Dict[str, float] = {}
    # Track last forced prediction time per game to ensure regular predictions
    last_forced_prediction_times: Dict[str, float] = {}

    logger.info(
        f"Prediction throttling: interval={PREDICTION_INTERVAL}s, "
        f"forced_interval={FORCE_PREDICTION_INTERVAL}s, "
        f"critical_time={MODEL_PREDICTION_CRITICAL_TIME_SECONDS}s, "
        f"close_game_threshold={MODEL_PREDICTION_CLOSE_GAME_THRESHOLD}"
    )

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
                            # Validate that timestamp is reasonable (not too far in past/future)
                            if game_start_ts < 0 or game_start_ts > time.time() + 86400:
                                logger.warning(f"Invalid game_start_ts from Redis: {game_start_ts}")
                                game_start_ts = None
                        except (TypeError, ValueError) as e:
                            logger.warning(f"Failed to parse game_start_ts from Redis: {e}")
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

                    # Prepare raw features for throttling check and prediction
                    raw_features = {
                        "home_score": home,
                        "away_score": away,
                        "seconds_elapsed": seconds_elapsed,
                        "strength": features.get("strength", "EV"),
                        "last_event": features.get("last_event", "FACEOFF"),
                    }

                    # Smart throttling: check if we should predict for this event
                    current_time = time.time()
                    if not should_predict(
                        game_id, raw_features, last_prediction_times, last_forced_prediction_times, current_time
                    ):
                        # Skip this prediction to reduce load
                        PRED_SKIPPED.inc()
                        await r.xack(STREAM_FEATURES, GROUP_MODEL_SVC, mid)
                        continue

                    # Run prediction asynchronously (non-blocking)
                    p_home = await predict_async(
                        selected_model, selected_model_type, raw_features
                    )

                    # Update last prediction time for this game
                    last_prediction_times[game_id] = current_time
                    # Also update forced prediction time if this was a forced prediction
                    # (handled in should_predict function)

                    # For A/B testing logging, get engineered features
                    if selected_model_type == MODEL_TYPE_BASELINE:
                        engineered_features = raw_features
                    else:
                        engineered_features = engineer_features(raw_features)

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

                    # Calculate actual prediction timestamp (wall-clock time)
                    prediction_timestamp = (
                        prediction_event_ts
                        if prediction_event_ts is not None
                        else time.time()
                    )
                    
                    out = {
                        "game_id": game_id,
                        "ts": ts,  # Relative time (seconds elapsed in game)
                        "timestamp": prediction_timestamp,  # Wall-clock timestamp for updated_at
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
                        # Close and reset connection on error
                        # Ensure connection is closed before setting to None to prevent leak
                        if db_conn:
                            try:
                                if not db_conn.closed:
                                    await db_conn.close()
                            except Exception as close_error:
                                logger.warning(f"Error closing DB connection: {close_error}")
                            finally:
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
