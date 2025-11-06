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

DATABASE_URL = os.environ.get('DATABASE_URL', '')

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Use improved trained model by default, fallback to baseline if not available
MODEL_ID = os.environ.get("MODEL_ID", "lightgbm_20251104_192617_53104e84")

# A/B testing configuration
AB_TEST_ENABLED = os.environ.get("AB_TEST_ENABLED", "false").lower() == "true"

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
    
    # Initialize A/B testing if enabled
    ab_router = None
    ab_tracker = None
    model_loaders = {}  # Cache for multiple models
    
    if AB_TEST_ENABLED:
        ab_router = create_ab_test_router()
        ab_tracker = create_ab_test_tracker(DATABASE_URL)
        
        if ab_router.is_enabled():
            print(f'[model_svc] A/B testing enabled with {len(ab_router.get_all_variants())} variants')
            for variant in ab_router.get_all_variants():
                if variant.enabled:
                    print(f'  - {variant.name} ({variant.model_id}): {variant.traffic_percentage}%')
                    # Pre-load all variants
                    loader = load_production_model(variant.model_id)
                    model_loaders[variant.model_id] = loader
                    print(f'    Loaded {loader.model_type} model')
        else:
            print('[model_svc] A/B testing configured but not enabled (single variant)')
            ab_router = None
    
    # Load default model if A/B testing not enabled
    if not ab_router:
        model_loader = load_production_model()
        model = model_loader.model
        model_type = model_loader.model_type
        print(f'[model_svc] Loaded {model_type} model: {MODEL_ID}')
    else:
        # Use first variant as default fallback
        default_variant = ab_router.get_all_variants()[0] if ab_router.get_all_variants() else None
        if default_variant:
            model_loader = model_loaders.get(default_variant.model_id) or load_production_model(default_variant.model_id)
            model = model_loader.model
            model_type = model_loader.model_type
        else:
            model_loader = load_production_model()
            model = model_loader.model
            model_type = model_loader.model_type

    while True:
        # Process pending messages first (if any), then new messages
        # This ensures we don't lose predictions from old messages
        try:
            # Try to claim pending messages older than 1 second (very short to process quickly)
            # xautoclaim returns (next_id, [(id, {fields}), ...])
            # Note: redis-py xautoclaim returns (next_id, [(id, {fields}), ...])
            claimed_result = await r.xautoclaim(STREAM_FEATURES, GROUP, CONSUMER, 1000, "-", count=10)
            # xautoclaim returns a list: [next_id, [(id, {fields}), ...], []]
            if claimed_result and isinstance(claimed_result, list) and len(claimed_result) >= 2:
                messages = claimed_result[1]  # Second element is the list of messages
                if messages and len(messages) > 0:  # Only process if we have messages
                    print(f"[model_svc] Claimed {len(messages)} pending messages")
                    for mid, fields in messages:
                        try:
                            import time as _t
                            _t0 = _t.perf_counter()
                            # Fields is a dict, extract json field
                            features = json.loads(fields.get("json") or "{}")
                            game_id = features["game_id"]
                            home = int(features["home_score"])
                            away = int(features["away_score"])
                            ts_relative = float(features["ts"])  # Relative time from game start
                            seconds_elapsed = ts_relative

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
                                    'home_score': home,
                                    'away_score': away,
                                    'seconds_elapsed': seconds_elapsed,
                                    'strength': features.get("strength", "EV"),
                                    'last_event': features.get("last_event", "FACEOFF"),
                                }
                                engineered_features = raw_features
                                
                                # Override prediction if game is at 0:00 with score differential
                                # Calculate time_remaining (regulation time is 3600 seconds)
                                time_remaining = max(0.0, 3600.0 - seconds_elapsed)
                                score_diff = home - away
                                
                                # If game clock shows 0:00 and there's a score differential, return 100% for winner
                                if time_remaining == 0.0 and score_diff != 0:
                                    if home > away:
                                        p_home = 1.0  # Home team wins
                                    elif away > home:
                                        p_home = 0.0  # Away team wins
                            else:
                                import pandas as pd
                                raw_features = {
                                    'home_score': home,
                                    'away_score': away,
                                    'seconds_elapsed': seconds_elapsed,
                                    'strength': features.get("strength", "EV"),
                                    'last_event': features.get("last_event", "FACEOFF"),
                                }
                                engineered_features = engineer_features(raw_features)
                                feature_df = pd.DataFrame([engineered_features])
                                # predict() returns a Series with calibration and clipping applied
                                p_home = float(selected_model.predict(feature_df, clip_probabilities=True).iloc[0])
                                
                                # Override prediction if game is at 0:00 with score differential
                                # Calculate time_remaining from engineered features
                                time_remaining = engineered_features.get('time_remaining', max(0.0, 3600.0 - seconds_elapsed))
                                score_diff = home - away
                                
                                # If game clock shows 0:00 and there's a score differential, return 100% for winner
                                if time_remaining == 0.0 and score_diff != 0:
                                    if home > away:
                                        p_home = 1.0  # Home team wins
                                    elif away > home:
                                        p_home = 0.0  # Away team wins
                            
                            # Calculate absolute timestamp for database storage
                            # We need to get game start time to convert relative time to absolute timestamp
                            import time as _time_module
                            try:
                                # Try to get game start time from Redis or calculate from current time
                                # For now, use current time minus relative time as approximation
                                # This will be fixed when we properly track game start times
                                current_absolute_ts = _time_module.time()
                                ts = current_absolute_ts
                                # If ts_relative is very large (> 1000000), it's probably already absolute
                                # Otherwise, it's relative time and we need to estimate absolute time
                                if ts_relative > 1000000:
                                    # Already absolute timestamp
                                    pass
                                else:
                                    # Relative time - estimate absolute time (current time minus relative time)
                                    # This is approximate but should work for recent games
                                    current_absolute_ts - ts_relative + ts_relative
                                    # Actually, if ts_relative is small (< 7200 = 2 hours), it's relative time
                                    # We should store it as relative time offset from game start
                                    # But for database, we need absolute timestamp
                                    # Use current time as base (will be corrected by history endpoint)
                            except Exception:
                                ts = _time_module.time()
                            
                            # Log prediction for A/B testing (after ts is set)
                            if ab_tracker and selected_variant:
                                from datetime import datetime
                                ab_tracker.log_prediction(
                                    game_id=game_id,
                                    model_id=selected_model_id,
                                    variant_name=selected_variant.name,
                                    prediction=p_home,
                                    features=engineered_features,
                                    timestamp=datetime.fromtimestamp(ts) if ts else None
                                )
                            
                            out = {
                                "game_id": game_id,
                                "ts": ts_relative,  # Store relative time in Redis
                                "model_id": selected_model_id,
                                "p_home_win": round(p_home, 4),
                            }
                            if selected_variant:
                                out["variant_name"] = selected_variant.name
                            sid = await r.xadd(STREAM_PREDICTIONS, {"json": json.dumps(out)})
                            await r.hset(f"pred:{game_id}", mapping={k: str(v) for k, v in out.items()})
                            await r.publish(f"pred_stream:{game_id}", json.dumps(out))

                            PRED_COUNTER.inc()
                            try:
                                if DATABASE_URL:
                                    # Get game start time from NHL API to calculate absolute timestamp
                                    import httpx
                                    game_start_ts = None
                                    try:
                                        async with httpx.AsyncClient(timeout=5.0) as client:
                                            game_data_response = await client.get(f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play")
                                            if game_data_response.status_code == 200:
                                                game_data = game_data_response.json()
                                                game_start_str = game_data.get("startTimeUTC", "")
                                                if game_start_str:
                                                    from datetime import datetime
                                                    game_start = datetime.fromisoformat(game_start_str.replace('Z', '+00:00'))
                                                    game_start_ts = game_start.timestamp()
                                    except Exception:
                                        pass  # Fallback to current time if we can't get game start
                                    
                                    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
                                        async with conn.cursor() as cur:
                                            # Calculate absolute timestamp from game start + relative time
                                            import time as _time_module
                                            if game_start_ts and ts_relative < 1000000:  # Valid relative time
                                                # Absolute timestamp = game start + relative time
                                                absolute_ts = game_start_ts + ts_relative
                                            elif ts_relative > 1000000:
                                                # Already absolute timestamp
                                                absolute_ts = ts_relative
                                            else:
                                                # Fallback: use current time (approximate)
                                                absolute_ts = _time_module.time()
                                            
                                            await cur.execute(
                                                "INSERT INTO predictions(ts, game_id, model_id, p_home_win) VALUES (to_timestamp(%s), %s, %s, %s)",
                                                (absolute_ts, game_id, selected_model_id, float(out["p_home_win"])),
                                            )
                                            await conn.commit()
                            except Exception as e:
                                print("[model_svc][db] insert error:", e)
                            finally:
                                PROC_TIME.observe(_t.perf_counter() - _t0)

                            await r.xack(STREAM_FEATURES, GROUP, mid)
                            print(f"[model_svc] {mid} -> pred id={sid} game={game_id} p_home={out['p_home_win']:.4f} model={selected_model_id} (pending)")
                        except Exception as e:
                            print(f"[model_svc] ERROR processing pending {mid}: {e}")
                            import traceback
                            traceback.print_exc()
                            try:
                                await r.xack(STREAM_FEATURES, GROUP, mid)
                            except Exception:
                                pass
                    continue  # Process pending messages first, then new ones
        except Exception as e:
            # If xautoclaim fails, continue to new messages
            print(f"[model_svc] xautoclaim error (ignoring): {e}")
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        
        # Then read new messages
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
                            'home_score': home,
                            'away_score': away,
                            'seconds_elapsed': seconds_elapsed,
                            'strength': features.get("strength", "EV"),
                            'last_event': features.get("last_event", "FACEOFF"),
                        }
                        engineered_features = raw_features
                    else:
                        # Trained model needs full engineered feature set
                        import pandas as pd
                        # Add raw features needed for engineering
                        raw_features = {
                            'home_score': home,
                            'away_score': away,
                            'seconds_elapsed': seconds_elapsed,
                            'strength': features.get("strength", "EV"),
                            'last_event': features.get("last_event", "FACEOFF"),
                        }
                        # Engineer features matching training pipeline
                        engineered_features = engineer_features(raw_features)
                        # Create DataFrame with engineered features
                        feature_df = pd.DataFrame([engineered_features])
                        # predict() returns a Series with calibration and clipping applied
                        p_home = float(selected_model.predict(feature_df, clip_probabilities=True).iloc[0])
                    
                    # Log prediction for A/B testing
                    if ab_tracker and selected_variant:
                        from datetime import datetime
                        ab_tracker.log_prediction(
                            game_id=game_id,
                            model_id=selected_model_id,
                            variant_name=selected_variant.name,
                            prediction=p_home,
                            features=engineered_features,
                            timestamp=datetime.fromtimestamp(ts) if ts else None
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
                                        (ts, game_id, selected_model_id, float(out["p_home_win"])),
                                    )
                                    await conn.commit()
                    except Exception as e:
                        print("[model_svc][db] insert error:", e)
                    finally:
                        PROC_TIME.observe(_t.perf_counter() - _t0)

                    await r.xack(STREAM_FEATURES, GROUP, mid)
                    print(f"[model_svc] {mid} -> pred id={sid} game={game_id} p_home={out['p_home_win']:.4f} model={selected_model_id}")
                except Exception as e:
                    print(f"[model_svc] ERROR processing {mid}: {e}")
                    import traceback
                    traceback.print_exc()
                    # Still acknowledge to avoid blocking
                    try:
                        await r.xack(STREAM_FEATURES, GROUP, mid)
                    except Exception:
                        pass

async def main():
    await run_model()

if __name__ == "__main__":
    asyncio.run(main())
