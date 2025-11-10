#!/usr/bin/env python3
"""
Test script to verify API resilience when NHL API is unavailable.

This script tests three scenarios:
1. Normal operation (NHL API available)
2. Fallback to cached metadata (NHL API unavailable, but game was cached before)
3. Fallback to provided team names (NHL API unavailable, no cache)
"""

import asyncio
import httpx
from redis.asyncio import Redis

GATEWAY_URL = "http://localhost:8000"
REDIS_URL = "redis://localhost:6379"
TEST_GAME_ID = "2024020999"  # Fake game ID that won't exist in NHL API


async def test_normal_operation():
    """Test 1: Normal operation with NHL API available"""
    print("\n" + "=" * 60)
    print("Test 1: Normal Operation (NHL API Available)")
    print("=" * 60)

    # Use a real game ID that should exist
    real_game_id = "2024020001"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(f"{GATEWAY_URL}/v1/games/{real_game_id}/start")
            print(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"✓ Response: {data}")
                print(f"  - Game ID: {data.get('game_id')}")
                print(f"  - Matchup: {data.get('matchup')}")
                print(f"  - Mode: {data.get('mode')}")
                print(f"  - NHL API Available: {data.get('nhl_api_available')}")
                return True
            else:
                print(f"✗ Unexpected status code: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
        except Exception as e:
            print(f"✗ Error: {e}")
            return False


async def test_cached_metadata():
    """Test 2: Fallback to cached metadata (NHL API unavailable but cache exists)"""
    print("\n" + "=" * 60)
    print("Test 2: Cached Metadata Fallback")
    print("=" * 60)

    # First, manually cache team metadata for a fake game
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    cache_game_id = "2024020888"

    await r.hset(
        f"game_metadata:{cache_game_id}",
        mapping={
            "home_team": "Bruins",
            "away_team": "Canadiens",
            "cached_at": str(asyncio.get_event_loop().time()),
        },
    )
    print(f"✓ Cached team metadata for game {cache_game_id}")

    # Try to start ingestion (will fail NHL API but use cache)
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(f"{GATEWAY_URL}/v1/games/{cache_game_id}/start")
            print(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"✓ Response: {data}")
                print(f"  - Game ID: {data.get('game_id')}")
                print(f"  - Matchup: {data.get('matchup')}")
                print(f"  - Mode: {data.get('mode')}")
                print(f"  - NHL API Available: {data.get('nhl_api_available')}")

                # Verify it used cached data
                if data.get("matchup") == "Canadiens @ Bruins" and data.get("mode") == "synthetic":
                    print("✓ Successfully used cached metadata")
                    return True
                else:
                    print("✗ Did not use cached metadata as expected")
                    return False
            else:
                print(f"✗ Unexpected status code: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
        except Exception as e:
            print(f"✗ Error: {e}")
            return False
        finally:
            await r.close()


async def test_provided_team_names():
    """Test 3: Fallback to provided team names (NHL API unavailable, no cache)"""
    print("\n" + "=" * 60)
    print("Test 3: Provided Team Names Fallback")
    print("=" * 60)

    # Use a fake game ID with no cache and provide team names
    uncached_game_id = "2024020777"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Clear any existing cache
            r = Redis.from_url(REDIS_URL, decode_responses=True)
            await r.delete(f"game_metadata:{uncached_game_id}")
            await r.close()

            # Start ingestion with provided team names
            response = await client.post(
                f"{GATEWAY_URL}/v1/games/{uncached_game_id}/start",
                params={"home_team": "Lightning", "away_team": "Panthers"},
            )
            print(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"✓ Response: {data}")
                print(f"  - Game ID: {data.get('game_id')}")
                print(f"  - Matchup: {data.get('matchup')}")
                print(f"  - Mode: {data.get('mode')}")
                print(f"  - NHL API Available: {data.get('nhl_api_available')}")

                # Verify it used provided team names
                if data.get("matchup") == "Panthers @ Lightning" and data.get("mode") == "synthetic":
                    print("✓ Successfully used provided team names")
                    return True
                else:
                    print("✗ Did not use provided team names as expected")
                    return False
            else:
                print(f"✗ Unexpected status code: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
        except Exception as e:
            print(f"✗ Error: {e}")
            return False


async def test_generic_fallback():
    """Test 4: Ultimate fallback to generic names"""
    print("\n" + "=" * 60)
    print("Test 4: Generic Fallback (No API, No Cache, No Params)")
    print("=" * 60)

    uncached_game_id = "2024020666"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Clear any existing cache
            r = Redis.from_url(REDIS_URL, decode_responses=True)
            await r.delete(f"game_metadata:{uncached_game_id}")
            await r.close()

            # Start ingestion without team names (will use "Home" and "Away")
            response = await client.post(f"{GATEWAY_URL}/v1/games/{uncached_game_id}/start")
            print(f"Status Code: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"✓ Response: {data}")
                print(f"  - Game ID: {data.get('game_id')}")
                print(f"  - Matchup: {data.get('matchup')}")
                print(f"  - Mode: {data.get('mode')}")
                print(f"  - NHL API Available: {data.get('nhl_api_available')}")

                # Verify it used generic names
                if data.get("matchup") == "Away @ Home" and data.get("mode") == "synthetic":
                    print("✓ Successfully used generic fallback")
                    return True
                else:
                    print("✗ Did not use generic fallback as expected")
                    return False
            else:
                print(f"✗ Unexpected status code: {response.status_code}")
                print(f"  Response: {response.text}")
                return False
        except Exception as e:
            print(f"✗ Error: {e}")
            return False


async def main():
    print("=" * 60)
    print("API Resilience Test Suite")
    print("=" * 60)

    results = []

    # Run all tests
    results.append(("Normal Operation", await test_normal_operation()))
    results.append(("Cached Metadata", await test_cached_metadata()))
    results.append(("Provided Team Names", await test_provided_team_names()))
    results.append(("Generic Fallback", await test_generic_fallback()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! API is resilient to NHL API failures.")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed.")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
