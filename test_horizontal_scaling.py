#!/usr/bin/env python3
"""
Test script to verify horizontal scaling of feature_state service.

This script:
1. Sends 10 events for a test game to Redis events stream
2. Events will be distributed round-robin to multiple consumers
3. Verifies final state in Redis is correct (all goals counted)
"""

import asyncio
import json
import time
from redis.asyncio import Redis

REDIS_URL = "redis://localhost:6379"
STREAM_EVENTS = "events"
TEST_GAME_ID = "test_game_scaling_001"


async def main():
    r = Redis.from_url(REDIS_URL, decode_responses=True)

    print("=" * 60)
    print("Horizontal Scaling Test for feature_state")
    print("=" * 60)

    # Reset state for test game
    await r.delete(f"state:{TEST_GAME_ID}")
    await r.delete(f"game_start_ts:{TEST_GAME_ID}")
    print(f"✓ Cleared state for test game: {TEST_GAME_ID}")

    # Create test events: 5 HOME goals, 3 AWAY goals
    events = []
    base_ts = time.time()

    # Goal 1: HOME
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "HOME",
        "ts": base_ts + 10,
        "strength": "EV",
        "empty_net": False,
        "player_id": 8471214,
    })

    # Goal 2: AWAY
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "AWAY",
        "ts": base_ts + 20,
        "strength": "EV",
        "empty_net": False,
        "player_id": 8476453,
    })

    # Goal 3: HOME
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "HOME",
        "ts": base_ts + 30,
        "strength": "PP",
        "empty_net": False,
        "player_id": 8471214,
    })

    # Goal 4: HOME
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "HOME",
        "ts": base_ts + 40,
        "strength": "EV",
        "empty_net": False,
        "player_id": 8477956,
    })

    # Goal 5: AWAY
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "AWAY",
        "ts": base_ts + 50,
        "strength": "EV",
        "empty_net": False,
        "player_id": 8476453,
    })

    # Goal 6: AWAY
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "AWAY",
        "ts": base_ts + 60,
        "strength": "EV",
        "empty_net": False,
        "player_id": 8478420,
    })

    # Goal 7: HOME
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "HOME",
        "ts": base_ts + 70,
        "strength": "EV",
        "empty_net": False,
        "player_id": 8471214,
    })

    # Goal 8: HOME
    events.append({
        "game_id": TEST_GAME_ID,
        "event_type": "GOAL",
        "team": "HOME",
        "ts": base_ts + 80,
        "strength": "EN",
        "empty_net": True,
        "player_id": 8471214,
    })

    print(f"\n✓ Created {len(events)} test events")
    print(f"  - Expected final score: HOME 5, AWAY 3")

    # Send events to stream
    print(f"\n⏳ Sending events to Redis stream '{STREAM_EVENTS}'...")
    for i, event in enumerate(events, 1):
        await r.xadd(STREAM_EVENTS, {"json": json.dumps(event)})
        print(f"  [{i}/{len(events)}] Sent: {event['team']} GOAL at ts={event['ts']:.0f}")
        await asyncio.sleep(0.1)  # Small delay to simulate real-time

    # Wait for processing
    print(f"\n⏳ Waiting 3 seconds for consumers to process events...")
    await asyncio.sleep(3)

    # Check final state in Redis
    print(f"\n📊 Checking final state in Redis...")
    state = await r.hgetall(f"state:{TEST_GAME_ID}")

    if not state:
        print("❌ ERROR: No state found in Redis!")
        print("   This indicates events were not processed.")
        return False

    home_score = int(state.get("home_score", 0))
    away_score = int(state.get("away_score", 0))

    print(f"\nFinal State:")
    print(f"  HOME: {home_score}")
    print(f"  AWAY: {away_score}")
    print(f"  Strength: {state.get('strength')}")
    print(f"  Last Event: {state.get('last_event')}")

    # Verify correctness
    print(f"\n{'=' * 60}")
    if home_score == 5 and away_score == 3:
        print("✅ TEST PASSED: State is consistent across replicas!")
        print("   All 8 goals were correctly counted despite round-robin distribution.")
        return True
    else:
        print(f"❌ TEST FAILED: State inconsistency detected!")
        print(f"   Expected: HOME 5, AWAY 3")
        print(f"   Got:      HOME {home_score}, AWAY {away_score}")
        print(f"   Difference: {abs(5 - home_score)} HOME goals, {abs(3 - away_score)} AWAY goals")
        return False

    await r.close()


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
