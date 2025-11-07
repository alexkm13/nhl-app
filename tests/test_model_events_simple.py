#!/usr/bin/env python3
"""Test that verifies events flow through the pipeline to generate predictions."""
import asyncio
import sys
from redis.asyncio import Redis

REDIS_URL = "redis://localhost:6379/0"

async def test_model_takes_events(game_id: str):
    """Test that the model processes events and generates predictions."""
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    
    try:
        print("\n" + "="*70)
        print("TEST: Verifying Model Processes Events")
        print(f"Game ID: {game_id}")
        print("="*70 + "\n")
        
        # Step 1: Clear existing data to start fresh
        print("Step 1: Clearing existing data for fresh test...")
        await redis.delete(f"state:{game_id}")
        await redis.delete(f"pred:{game_id}")
        await redis.delete(f"ingestion_status:{game_id}")
        print("  ✓ Cleared state and predictions")
        
        # Step 2: Get initial stream lengths
        print("\nStep 2: Checking initial stream state...")
        try:
            events_info = await redis.xinfo_stream("events")
            events_before = events_info.get("length", 0)
        except Exception:
            events_before = 0
        try:
            features_info = await redis.xinfo_stream("features")
            features_before = features_info.get("length", 0)
        except Exception:
            features_before = 0
        try:
            predictions_info = await redis.xinfo_stream("predictions")
            predictions_before = predictions_info.get("length", 0)
        except Exception:
            predictions_before = 0
        
        print(f"  Events stream: {events_before} messages")
        print(f"  Features stream: {features_before} messages")
        print(f"  Predictions stream: {predictions_before} messages")
        
        # Step 3: Start ingestion
        print("\nStep 3: Starting ingestion...")
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"http://localhost:8000/v1/games/{game_id}/start")
            if response.status_code != 200:
                print(f"  ✗ Failed to start ingestion: {response.status_code}")
                return
            print("  ✓ Ingestion started")
        
        # Step 4: Wait for ingestion to complete
        print("\nStep 4: Waiting for ingestion to process events...")
        max_wait = 30
        for i in range(max_wait // 2):
            status = await redis.hgetall(f"ingestion_status:{game_id}")
            if status and status.get("status") == "completed":
                print("  ✓ Ingestion completed")
                break
            elif status and status.get("status") == "failed":
                print(f"  ✗ Ingestion failed: {status.get('error')}")
                return
            await asyncio.sleep(2)
        
        # Step 5: Verify events were added
        print("\nStep 5: Verifying events were published...")
        try:
            events_info = await redis.xinfo_stream("events")
            events_after = events_info.get("length", 0)
        except Exception:
            events_after = 0
        events_added = events_after - events_before
        
        if events_added == 0:
            print("  ⚠ No new events added (may have been already processed)")
            # Check if events for this game exist
            recent_events = await redis.xrevrange("events", count=100)
            game_event_count = sum(1 for _, fields in recent_events 
                                 if game_id in fields.get("json", ""))
            print(f"  Found {game_event_count} existing events for this game in recent stream")
        else:
            print(f"  ✓ Added {events_added} events to stream")
        
        # Step 6: Wait for feature_state to process events
        print("\nStep 6: Waiting for feature_state to generate features...")
        max_wait = 20
        features_added = 0
        for i in range(max_wait // 2):
            try:
                features_info = await redis.xinfo_stream("features")
                features_after = features_info.get("length", 0)
            except Exception:
                features_after = 0
            features_added = features_after - features_before
            if features_added > 0:
                print(f"  ✓ Generated {features_added} features")
                break
            await asyncio.sleep(2)
        
        if features_added == 0:
            print("  ✗ No features generated - feature_state may not be processing events")
            return
        
        # Step 7: Wait for model_svc to generate predictions
        print("\nStep 7: Waiting for model_svc to generate predictions...")
        max_wait = 20
        prediction_generated = False
        for i in range(max_wait // 2):
            # Check predictions stream
            try:
                predictions_info = await redis.xinfo_stream("predictions")
                predictions_after = predictions_info.get("length", 0)
            except Exception:
                predictions_after = 0
            predictions_added = predictions_after - predictions_before
            
            # Check prediction cache
            pred_cache = await redis.hgetall(f"pred:{game_id}")
            
            if pred_cache:
                print("  ✓ Prediction generated and cached:")
                print(f"    p_home_win: {pred_cache.get('p_home_win')}")
                print(f"    model_id: {pred_cache.get('model_id')}")
                print(f"    timestamp: {pred_cache.get('ts')}")
                prediction_generated = True
                break
            elif predictions_added > 0:
                print(f"  Predictions in stream: {predictions_added}, but cache not updated yet...")
            
            await asyncio.sleep(2)
        
        if not prediction_generated:
            print("  ✗ No prediction in cache after waiting")
            print(f"  Predictions in stream: {predictions_added}")
            return
        
        # Step 8: Verify via API
        print("\nStep 8: Verifying via API endpoint...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"http://localhost:8000/v1/games/{game_id}/winprob")
            if response.status_code == 200:
                data = response.json()
                print("  ✓ API returned prediction:")
                print(f"    p_home_win: {data.get('p_home_win')}")
                print(f"    model_id: {data.get('model_id')}")
            else:
                print(f"  ✗ API failed: {response.status_code} - {response.text}")
        
        # Summary
        print(f"\n{'='*70}")
        print("TEST RESULTS")
        print(f"{'='*70}")
        print(f"✓ Events published: {events_added if events_added > 0 else 'Using existing'}")
        print(f"✓ Features generated: {features_added}")
        print(f"✓ Predictions generated: {prediction_generated}")
        print(f"\n{'='*70}")
        print("✓ SUCCESS: Model is processing events correctly!")
        print(f"{'='*70}\n")
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await redis.aclose()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        game_id = sys.argv[1]
    else:
        import httpx
        try:
            response = httpx.get("http://localhost:8000/v1/games", timeout=5.0)
            if response.status_code == 200:
                data = response.json()
                games = [g for g in data.get("games", []) if g.get("game_state") == "OFF"]
                if games:
                    game_id = str(games[0]["id"])
                    print(f"Using completed game: {game_id}")
                else:
                    print("No completed games found. Please provide a game ID.")
                    sys.exit(1)
            else:
                print("Failed to fetch games. Please provide a game ID.")
                sys.exit(1)
        except Exception as e:
            print(f"Error: {e}")
            print("Usage: python test_model_events_simple.py <game_id>")
            sys.exit(1)
    
    asyncio.run(test_model_takes_events(game_id))
