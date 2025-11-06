#!/usr/bin/env python3
"""
Script to verify if the model service is running and generating predictions.
"""
import asyncio
import redis.asyncio as redis
import sys
import os

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

async def check_model_service():
    """Check if model service is running and generating predictions."""
    print("🔍 Checking Model Service Status...\n")
    
    try:
        # Connect to Redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        await r.ping()
        print("✅ Connected to Redis\n")
    except Exception as e:
        print(f"❌ Cannot connect to Redis: {e}")
        print(f"   REDIS_URL: {REDIS_URL}")
        return False
    
    try:
        # Check if model service has created the consumer group
        try:
            info = await r.xinfo_groups("features")
            print("✅ Features stream exists")
            print(f"   Consumer groups: {len(info)}")
            
            # Check if model_svc group exists
            model_svc_groups = [g for g in info if "model_svc" in g.get("name", "").lower()]
            if model_svc_groups:
                print(f"   ✅ Model service consumer group found: {model_svc_groups[0].get('name')}")
                print(f"      Pending: {model_svc_groups[0].get('pending', 0)}")
                print(f"      Consumers: {model_svc_groups[0].get('consumers', 0)}")
            else:
                print("   ⚠️  Model service consumer group not found")
        except Exception as e:
            print(f"   ⚠️  Features stream may not exist yet: {e}")
        
        print()
        
        # Check for predictions in Redis
        print("📊 Checking Predictions in Redis...")
        
        # Get all prediction keys
        pred_keys = await r.keys("pred:*")
        print(f"   Found {len(pred_keys)} game predictions in Redis")
        
        if pred_keys:
            print("\n   Sample predictions:")
            for key in pred_keys[:5]:  # Show first 5
                game_id = key.replace("pred:", "")
                pred_data = await r.hgetall(key)
                if pred_data:
                    p_home = pred_data.get("p_home_win", "N/A")
                    model_id = pred_data.get("model_id", "N/A")
                    ts = pred_data.get("ts", "N/A")
                    print(f"   - Game {game_id}:")
                    print(f"     P(home win): {p_home}")
                    print(f"     Model ID: {model_id}")
                    print(f"     Timestamp: {ts}")
        else:
            print("   ⚠️  No predictions found in Redis")
        
        print()
        
        # Check predictions stream
        print("📈 Checking Predictions Stream...")
        try:
            stream_length = await r.xlen("predictions")
            print(f"   Predictions stream length: {stream_length}")
            
            if stream_length > 0:
                # Get latest predictions
                latest = await r.xrevrange("predictions", count=5)
                print(f"   Latest {len(latest)} predictions:")
                for msg_id, fields in latest:
                    if fields.get("json"):
                        import json
                        pred = json.loads(fields["json"])
                        game_id = pred.get("game_id", "N/A")
                        p_home = pred.get("p_home_win", "N/A")
                        model_id = pred.get("model_id", "N/A")
                        print(f"     - Game {game_id}: P(home)={p_home}, Model={model_id}")
        except Exception as e:
            print(f"   ⚠️  Error checking predictions stream: {e}")
        
        print()
        
        # Check features stream
        print("🔧 Checking Features Stream...")
        try:
            features_length = await r.xlen("features")
            print(f"   Features stream length: {features_length}")
            
            if features_length > 0:
                # Get latest features
                latest_features = await r.xrevrange("features", count=3)
                print(f"   Latest {len(latest_features)} features:")
                for msg_id, fields in latest_features:
                    if fields.get("json"):
                        import json
                        feat = json.loads(fields["json"])
                        game_id = feat.get("game_id", "N/A")
                        print(f"     - Game {game_id}: {feat.get('home_score', 0)}-{feat.get('away_score', 0)}")
        except Exception as e:
            print(f"   ⚠️  Error checking features stream: {e}")
        
        print()
        
        # Summary
        print("📋 Summary:")
        if pred_keys:
            print("   ✅ Model service appears to be generating predictions")
        else:
            print("   ⚠️  No predictions found - model service may not be running or processing events")
        
        await r.aclose()
        return True
        
    except Exception as e:
        print(f"❌ Error checking model service: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(check_model_service())
    sys.exit(0 if success else 1)

