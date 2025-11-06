#!/usr/bin/env python3
"""Test script to verify events flow through the pipeline to the model."""
import asyncio
import json
import time
import sys
from redis.asyncio import Redis

REDIS_URL = "redis://localhost:6379/0"

async def check_stream_length(redis: Redis, stream_name: str) -> int:
    """Check the length of a Redis stream."""
    try:
        info = await redis.xinfo_stream(stream_name)
        return info.get("length", 0)
    except Exception as e:
        print(f"  Error checking {stream_name}: {e}")
        return 0

async def check_redis_key(redis: Redis, key: str) -> dict:
    """Check if a Redis key exists and return its value."""
    try:
        value = await redis.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception as e:
        print(f"  Error checking {key}: {e}")
        return None

async def check_redis_hash(redis: Redis, key: str) -> dict:
    """Check if a Redis hash exists and return its values."""
    try:
        values = await redis.hgetall(key)
        return values if values else None
    except Exception as e:
        print(f"  Error checking {key}: {e}")
        return None

async def test_model_events_flow(game_id: str):
    """Test that events flow through the pipeline to the model."""
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    
    try:
        print(f"\n{'='*60}")
        print(f"Testing Event Flow for Game: {game_id}")
        print(f"{'='*60}\n")
        
        # Step 1: Check initial state
        print("Step 1: Checking initial state...")
        events_before = await check_stream_length(redis, "events")
        features_before = await check_stream_length(redis, "features")
        predictions_before = await check_stream_length(redis, "predictions")
        state_before = await check_redis_hash(redis, f"state:{game_id}")
        pred_before = await check_redis_hash(redis, f"pred:{game_id}")
        
        print(f"  Events stream length: {events_before}")
        print(f"  Features stream length: {features_before}")
        print(f"  Predictions stream length: {predictions_before}")
        print(f"  Game state exists: {state_before is not None}")
        print(f"  Prediction exists: {pred_before is not None}")
        
        # Step 2: Trigger ingestion
        print(f"\nStep 2: Triggering ingestion for game {game_id}...")
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"http://localhost:8000/v1/games/{game_id}/start")
            if response.status_code == 200:
                print(f"  ✓ Ingestion started: {response.json()}")
            else:
                print(f"  ✗ Failed to start ingestion: {response.status_code} - {response.text}")
                return
        
        # Step 3: Wait for ingestion to process
        print(f"\nStep 3: Waiting for ingestion to process events...")
        max_wait = 30  # seconds
        wait_time = 0
        ingestion_complete = False
        
        while wait_time < max_wait:
            status = await check_redis_hash(redis, f"ingestion_status:{game_id}")
            if status:
                status_value = status.get("status", "")
                print(f"  Ingestion status: {status_value} (waited {wait_time}s)")
                if status_value == "complete":
                    ingestion_complete = True
                    break
                elif status_value == "failed":
                    error = status.get("error", "Unknown error")
                    print(f"  ✗ Ingestion failed: {error}")
                    return
            await asyncio.sleep(2)
            wait_time += 2
        
        if not ingestion_complete:
            print(f"  ⚠ Ingestion did not complete within {max_wait} seconds")
        
        # Step 4: Check events stream
        print(f"\nStep 4: Checking events stream...")
        events_after = await check_stream_length(redis, "events")
        events_added = events_after - events_before
        print(f"  Events stream length: {events_after} (added {events_added} events)")
        
        if events_added == 0:
            print("  ✗ No events were added to the stream!")
            return
        else:
            print(f"  ✓ Events were added to the stream")
        
        # Step 5: Wait for feature_state to process events
        print(f"\nStep 5: Waiting for feature_state to process events...")
        max_wait = 20
        wait_time = 0
        
        while wait_time < max_wait:
            features_after = await check_stream_length(redis, "features")
            features_added = features_after - features_before
            print(f"  Features stream length: {features_after} (added {features_added} features, waited {wait_time}s)")
            
            if features_added > 0:
                print(f"  ✓ Features were generated from events")
                break
            
            await asyncio.sleep(2)
            wait_time += 2
        
        if features_added == 0:
            print("  ✗ No features were generated!")
            print("  This indicates feature_state is not processing events from the stream")
            return
        
        # Step 6: Check game state
        print(f"\nStep 6: Checking game state...")
        state_after = await check_redis_hash(redis, f"state:{game_id}")
        if state_after:
            print(f"  ✓ Game state exists:")
            print(f"    Home score: {state_after.get('home_score', 'N/A')}")
            print(f"    Away score: {state_after.get('away_score', 'N/A')}")
            print(f"    Strength: {state_after.get('strength', 'N/A')}")
            print(f"    Last event: {state_after.get('last_event', 'N/A')}")
        else:
            print("  ✗ Game state not found")
        
        # Step 7: Wait for model_svc to process features
        print(f"\nStep 7: Waiting for model_svc to generate predictions...")
        max_wait = 20
        wait_time = 0
        
        while wait_time < max_wait:
            predictions_after = await check_stream_length(redis, "predictions")
            predictions_added = predictions_after - predictions_before
            pred_after = await check_redis_hash(redis, f"pred:{game_id}")
            
            print(f"  Predictions stream length: {predictions_after} (added {predictions_added} predictions, waited {wait_time}s)")
            
            if pred_after:
                print(f"  ✓ Prediction exists in cache:")
                print(f"    Game ID: {pred_after.get('game_id', 'N/A')}")
                print(f"    Home win probability: {pred_after.get('p_home_win', 'N/A')}")
                print(f"    Model ID: {pred_after.get('model_id', 'N/A')}")
                print(f"    Timestamp: {pred_after.get('ts', 'N/A')}")
                break
            
            await asyncio.sleep(2)
            wait_time += 2
        
        if not pred_after:
            print("  ✗ No predictions were generated!")
            print("  This indicates model_svc is not processing features from the stream")
            return
        
        # Step 8: Verify via API endpoint
        print(f"\nStep 8: Verifying via API endpoint...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"http://localhost:8000/v1/games/{game_id}/winprob")
            if response.status_code == 200:
                data = response.json()
                print(f"  ✓ API endpoint returned prediction:")
                print(f"    Game ID: {data.get('game_id')}")
                print(f"    Home win probability: {data.get('p_home_win')}")
                print(f"    Model ID: {data.get('model_id')}")
            else:
                print(f"  ✗ API endpoint failed: {response.status_code} - {response.text}")
        
        # Summary
        print(f"\n{'='*60}")
        print("TEST SUMMARY")
        print(f"{'='*60}")
        print(f"✓ Events added to stream: {events_added}")
        print(f"✓ Features generated: {features_added}")
        print(f"✓ Predictions generated: {predictions_added}")
        print(f"✓ Game state updated: {state_after is not None}")
        print(f"✓ Prediction cached: {pred_after is not None}")
        print(f"\n{'='*60}")
        print("✓ SUCCESS: Events are flowing through the pipeline to the model!")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await redis.aclose()

if __name__ == "__main__":
    # Get game ID from command line or use a default
    if len(sys.argv) > 1:
        game_id = sys.argv[1]
    else:
        # Try to get a recent game ID
        import httpx
        try:
            response = httpx.get("http://localhost:8000/v1/games", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                games = data.get("games", [])
                if games:
                    game_id = str(games[0]["id"])
                    print(f"Using game ID: {game_id}")
                else:
                    print("No games found. Please provide a game ID as argument.")
                    sys.exit(1)
            else:
                print("Failed to fetch games. Please provide a game ID as argument.")
                sys.exit(1)
        except Exception as e:
            print(f"Error fetching games: {e}")
            print("Please provide a game ID as argument: python test_model_events.py <game_id>")
            sys.exit(1)
    
    asyncio.run(test_model_events_flow(game_id))

