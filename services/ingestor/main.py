import asyncio
import json
import os
import random
import time

import psycopg
from nhlpy import NHLClient
from redis.asyncio import Redis

from events import GameEvent

DATABASE_URL = os.environ.get('DATABASE_URL', '')

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
GAME_ID = os.environ.get("GAME_ID", "TEST_GAME")

STREAM_EVENTS = "events"
GROUP = "ingestors"
CONSUMER = f"producer-{random.randint(1000,9999)}"  # not used for producer but kept symmetrical

async def ensure_streams(r: Redis):
    # Create an empty stream so downstream groups can be created safely.
    await r.xadd(STREAM_EVENTS, {"bootstrap": "1"}, id="*")

async def produce_synthetic_game(r: Redis, game_id: str):
    print(f"[ingestor] starting synthetic game for {game_id}")
    start = time.time()
    clock_total = 20 * 60  # 20 minutes demo

    t = 0.0
    random.seed(42)
    while t < clock_total:
        await asyncio.sleep(0.5)  # emit ~2 events/sec

        # Random event selection
        ev_choice = random.choices(
            ["SHOT", "FACEOFF", "HIT", "PENALTY"],
            weights=[0.6, 0.1, 0.2, 0.1],
            k=1,
        )[0]
        team = random.choice(["HOME", "AWAY"])

        # Occasional goals
        if ev_choice == "SHOT" and random.random() < 0.07:
            ev_choice = "GOAL"

        strength = "EV"
        if random.random() < 0.08:
            strength = random.choice(["PP", "PK"])

        now = time.time()
        payload = GameEvent(
            game_id=game_id,
            ts=now,
            team=team,
            event_type=ev_choice,
            strength=strength,
            x=random.uniform(-100, 100),
            y=random.uniform(-42.5, 42.5),
            shot_quality=random.random(),
        ).model_dump()

        
        # Insert into TimescaleDB (optional)
        try:
            if DATABASE_URL:
                async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "INSERT INTO events(ts, game_id, team, event_type, strength, x, y, shot_quality) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s)",
                            (now, game_id, team, ev_choice, strength, payload["x"], payload["y"], payload["shot_quality"]),
                        )
                        await conn.commit()
        except Exception as e:
            print("[ingestor][db] insert error:", e)

        sid = await r.xadd(STREAM_EVENTS, {"json": json.dumps(payload)})
        print(f"[ingestor] XADD events id={sid} {payload['event_type']} team={team}")
        t = now - start

    print("[ingestor] game complete.")

async def fetch_nhl_game_data(nhl_client: NHLClient, game_id: str):
    """Fetch live or completed NHL game data"""
    try:
        # Try to get play-by-play data
        game_data = nhl_client.game_center.play_by_play(game_id)
        
        if not game_data or not isinstance(game_data, dict):
            return None
        
        # Extract plays list
        plays = game_data.get("plays", [])
        
        if isinstance(plays, list) and len(plays) > 0:
            # Return full game data including team IDs
            return game_data
        
        # Try boxscore as fallback
        boxscore = nhl_client.game_center.boxscore(game_id)
        if boxscore:
            return {"status": "completed", "plays": []}
        
        return None
    except Exception as e:
        print(f"[ingestor][nhl] Error fetching game {game_id}: {e}")
        return None

async def produce_nhl_game(r: Redis, nhl_client: NHLClient, game_id: str):
    """Produce events from real NHL game data"""
    print(f"[ingestor] Fetching NHL game data for {game_id}")
    
    game_data = await fetch_nhl_game_data(nhl_client, game_id)
    
    if not game_data:
        print(f"[ingestor] Could not fetch NHL data for {game_id}, falling back to synthetic")
        await produce_synthetic_game(r, game_id)
        return
    
    # If we have live game data, extract events
    plays = game_data.get("plays", [])
    
    if not plays:
        print(f"[ingestor] No play-by-play data available, using synthetic")
        await produce_synthetic_game(r, game_id)
        return
    
    # Get team IDs once
    home_team_id = game_data.get("homeTeam", {}).get("id")
    away_team_id = game_data.get("awayTeam", {}).get("id")
    
    print(f"[ingestor] Processing {len(plays)} events from NHL API")
    
    # Process real NHL events
    for play in plays:
        type_code = str(play.get("typeCode", ""))
        type_desc = play.get("typeDescKey", "")
        
        # Map NHL event type codes to our event types
        type_mapping = {
            "502": "FACEOFF",
            "503": "HIT",
            "504": "HIT",  # giveaway
            "505": "GOAL",
            "506": "SHOT",
            "507": "SHOT",  # missed-shot
            "508": "BLOCK",
            "509": "PENALTY",
        }
        
        # Skip non-relevant events
        if type_code in ["520", "516", "517"]:  # period-start, stoppage, period-end
            continue
        
        mapped_type = type_mapping.get(type_code, "SHOT")
        if mapped_type == "SHOT" and type_desc == "missed-shot":
            mapped_type = "SHOT"  # Keep as SHOT
        
        # Determine team from event owner
        details = play.get("details", {})
        event_owner_id = details.get("eventOwnerTeamId")
        
        # Match event owner to home/away
        if event_owner_id == home_team_id:
            team = "HOME"
        elif event_owner_id == away_team_id:
            team = "AWAY"
        else:
            # Fallback to defending side if eventOwnerTeamId not available
            team = "HOME" if details.get("homeTeamDefendingSide") else "AWAY"
        
        # Get situation/strength
        situation = play.get("situationCode", "1551")  # e.g., "1551" = 5v5
        strength = "EV"
        if situation[0] != situation[2]:  # Different numbers = power play
            if int(situation[0]) > int(situation[2]):
                strength = "PP"
            else:
                strength = "PK"
        
        # Get timestamp
        time_in_period = play.get("timeInPeriod", "00:00")
        period = play.get("periodDescriptor", {}).get("number", 1)
        
        # Convert time to seconds from start
        minutes, seconds = map(int, time_in_period.split(":"))
        total_seconds = (period - 1) * 1200 + (20 - minutes) * 60 + (60 - seconds)
        timestamp = time.time() - total_seconds  # Approximate timestamp
        
        # Get coordinates if available
        x = details.get("xCoordInFeet", random.uniform(-100, 100))
        y = details.get("yCoordInFeet", random.uniform(-42.5, 42.5))
        
        payload = GameEvent(
            game_id=game_id,
            ts=timestamp,
            team=team,
            event_type=mapped_type,
            strength=strength,
            x=x,
            y=y,
            shot_quality=random.random(),
        ).model_dump()
        
        # Insert into TimescaleDB
        try:
            if DATABASE_URL:
                async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            "INSERT INTO events(ts, game_id, team, event_type, strength, x, y, shot_quality) VALUES (to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s)",
                            (timestamp, game_id, team, mapped_type, strength, payload["x"], payload["y"], payload["shot_quality"]),
                        )
                        await conn.commit()
        except Exception as e:
            print(f"[ingestor][db] insert error: {e}")
        
        sid = await r.xadd(STREAM_EVENTS, {"json": json.dumps(payload)})
        print(f"[ingestor] XADD events id={sid} {mapped_type} team={team}")
        
        await asyncio.sleep(0.1)  # Small delay between events
    
    print("[ingestor] NHL game events processed")

async def main():
    r = Redis.from_url(REDIS_URL, decode_responses=True)
    nhl_client = NHLClient()
    
    try:
        await ensure_streams(r)
        
        # Try NHL API first, fall back to synthetic
        if GAME_ID != "TEST_GAME":
            await produce_nhl_game(r, nhl_client, GAME_ID)
        else:
            await produce_synthetic_game(r, GAME_ID)
    finally:
        await r.aclose()

if __name__ == "__main__":
    asyncio.run(main())
