#!/usr/bin/env python3
"""
Script to ingest historical NHL games for training data.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
import httpx
import psycopg
from redis.asyncio import Redis

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NHL_API_BASE = "https://api-web.nhle.com/v1"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gamecast")


async def fetch_daily_schedule(date: str) -> list:
    """Fetch game IDs for a specific date."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{NHL_API_BASE}/schedule/{date}")
            if response.status_code == 200:
                data = response.json()
                game_ids = []
                
                # Parse schedule response
                if isinstance(data, dict) and "gameWeek" in data:
                    for week in data.get("gameWeek", []):
                        for day in week.get("games", []):
                            if isinstance(day, dict):
                                game_id = day.get("id")
                                if game_id:
                                    game_ids.append(str(game_id))
                
                return game_ids
    except Exception as e:
        print(f"[ingest] Error fetching schedule for {date}: {e}")
    return []


async def ingest_game(game_id: str, redis: Redis, database_url: str):
    """Ingest a single game."""
    try:
        # Fetch play-by-play data
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play")
            if response.status_code != 200:
                return False
            game_data = response.json()
        
        plays = game_data.get("plays", [])
        if not plays:
            return False
        
        # Get team IDs
        home_team = game_data.get("homeTeam", {})
        away_team = game_data.get("awayTeam", {})
        home_team_id = home_team.get("id")
        away_team_id = away_team.get("id")
        
        if not home_team_id or not away_team_id:
            return False
        
        # Get game start time
        game_start_str = game_data.get("startTimeUTC", "")
        game_start_ts = None
        if game_start_str:
            try:
                game_start = datetime.fromisoformat(game_start_str.replace('Z', '+00:00'))
                game_start_ts = game_start.timestamp()
            except (ValueError, AttributeError):
                pass
        
        # Process plays and create snapshots throughout the game
        state = {"home_score": 0, "away_score": 0, "strength": "EV", "last_event": "FACEOFF"}
        snapshots = []
        
        # Sort plays by timestamp
        sorted_plays = sorted(plays, key=lambda p: (
            p.get("periodDescriptor", {}).get("number", 1),
            p.get("timeInPeriod", "00:00")
        ))
        
        last_snapshot_time = None
        snapshot_interval = 30  # Create snapshot every 30 seconds
        
        for play in sorted_plays:
            type_code = play.get("typeCode")
            period = play.get("periodDescriptor", {}).get("number", 1)
            time_in_period = play.get("timeInPeriod", "00:00")
            
            # Calculate timestamp
            if game_start_ts:
                try:
                    minutes, seconds = map(int, time_in_period.split(":"))
                    elapsed_seconds = minutes * 60 + seconds
                    period_offset = (period - 1) * 1200
                    play_ts = game_start_ts + period_offset + elapsed_seconds
                except (ValueError, TypeError):
                    play_ts = game_start_ts + (period * 1200)
            else:
                play_ts = datetime.now().timestamp()
            
            # Update state based on play
            if type_code == 505:  # GOAL
                details = play.get("details", {})
                event_owner_team_id = details.get("eventOwnerTeamId")
                
                if event_owner_team_id == home_team_id:
                    state["home_score"] += 1
                elif event_owner_team_id == away_team_id:
                    state["away_score"] += 1
                state["last_event"] = "GOAL"
            elif type_code == 509:  # PENALTY
                state["last_event"] = "PENALTY"
            elif type_code == 502:  # FACEOFF
                state["last_event"] = "FACEOFF"
            elif type_code in [506, 507]:  # SHOT
                state["last_event"] = "SHOT"
            
            # Update strength situation
            situation_code = play.get("situationCode", "1551")
            if len(situation_code) >= 4:
                away_skaters = int(situation_code[1]) if situation_code[1].isdigit() else 5
                home_skaters = int(situation_code[3]) if situation_code[3].isdigit() else 5
                
                if away_skaters < home_skaters:
                    state["strength"] = "PP"
                elif home_skaters < away_skaters:
                    state["strength"] = "PK"
                else:
                    state["strength"] = "EV"
            
            # Create snapshot if enough time has passed
            if last_snapshot_time is None or (play_ts - last_snapshot_time) >= snapshot_interval:
                snapshots.append({
                    "ts": play_ts,
                    "game_id": game_id,
                    "home_score": state["home_score"],
                    "away_score": state["away_score"],
                    "strength": state["strength"],
                    "last_event": state["last_event"]
                })
                last_snapshot_time = play_ts
        
        # Store snapshots in database
        if database_url and snapshots:
            try:
                async with await psycopg.AsyncConnection.connect(database_url) as conn:
                    async with conn.cursor() as cur:
                        for snapshot in snapshots:
                            await cur.execute(
                                """INSERT INTO features(ts, game_id, home_score, away_score, strength, last_event)
                                   VALUES (to_timestamp(%s), %s, %s, %s, %s, %s)
                                   ON CONFLICT DO NOTHING""",
                                (snapshot["ts"], snapshot["game_id"], snapshot["home_score"],
                                 snapshot["away_score"], snapshot["strength"], snapshot["last_event"])
                            )
                        await conn.commit()
            except Exception as e:
                print(f"[ingest] DB error for game {game_id}: {e}")
        
        return True
    except Exception as e:
        print(f"[ingest] Error ingesting game {game_id}: {e}")
        return False


async def ingest_date_range(start_date: str, end_date: str):
    """Ingest all games in a date range."""
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    current = start
    total_games = 0
    successful = 0
    
    print(f"Starting ingestion from {start_date} to {end_date}")
    
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        print(f"\nFetching games for {date_str}...")
        
        game_ids = await fetch_daily_schedule(date_str)
        
        if game_ids:
            print(f"  Found {len(game_ids)} games")
            
            for game_id in game_ids:
                total_games += 1
                print(f"  Ingesting game {game_id}...", end="", flush=True)
                
                if await ingest_game(game_id, redis, DATABASE_URL):
                    successful += 1
                    print(" ✓")
                else:
                    print(" ✗")
        
        current += timedelta(days=1)
        
        # Rate limiting
        await asyncio.sleep(0.5)
    
    print(f"\n\nIngestion complete:")
    print(f"  Total games: {total_games}")
    print(f"  Successful: {successful}")
    print(f"  Failed: {total_games - successful}")
    
    await redis.aclose()


async def main():
    """Main function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest historical NHL games")
    parser.add_argument("--start-date", type=str, default="2022-10-01",
                       help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2024-10-01",
                       help="End date (YYYY-MM-DD)")
    parser.add_argument("--database-url", type=str, help="Database URL")
    
    args = parser.parse_args()
    
    if args.database_url:
        global DATABASE_URL
        DATABASE_URL = args.database_url
    
    await ingest_date_range(args.start_date, args.end_date)


if __name__ == "__main__":
    asyncio.run(main())

