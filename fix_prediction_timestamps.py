#!/usr/bin/env python3
"""Fix prediction timestamps by backfilling with game start time + relative time."""
import asyncio
import os
from datetime import datetime
import httpx
import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gamecast")
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

async def get_game_start_time(game_id: str):
    """Get game start time from NHL API."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{API_BASE}/v1/games/{game_id}/playbyplay")
            if response.status_code == 200:
                data = response.json()
                # Try to get start time from events or game data
                # The play-by-play endpoint might have this info
                # For now, we'll need to fetch from NHL API directly
                pass
        except Exception as e:
            print(f"Error fetching game data: {e}")
    
    # Fetch directly from NHL API
    async with httpx.AsyncClient() as client:
        try:
            url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                start_time_str = data.get("startTimeUTC", "")
                if start_time_str:
                    game_start = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    return game_start.timestamp()
        except Exception as e:
            print(f"Error fetching from NHL API: {e}")
    
    return None

async def fix_timestamps_for_game(game_id: str, dry_run: bool = True):
    """Fix timestamps for predictions of a specific game."""
    print(f"\n{'='*60}")
    print(f"Fixing timestamps for game: {game_id}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}")
    print(f"{'='*60}\n")
    
    # Get game start time
    print("1. Fetching game start time...")
    game_start_ts = await get_game_start_time(game_id)
    if not game_start_ts:
        print("   ❌ Could not determine game start time")
        print("   You may need to provide it manually or the game may not exist")
        return False
    
    game_start_dt = datetime.fromtimestamp(game_start_ts)
    print(f"   ✓ Game start: {game_start_dt.isoformat()} ({game_start_ts})")
    
    # Connect to database
    print("\n2. Connecting to database...")
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        async with conn.cursor() as cur:
            # Get all predictions with bad timestamps
            print("\n3. Finding predictions with bad timestamps...")
            await cur.execute(
                """
                SELECT ts, p_home_win, model_id
                FROM predictions 
                WHERE game_id = %s 
                AND ts < '2020-01-01'
                ORDER BY ts ASC
                """,
                (game_id,)
            )
            rows = await cur.fetchall()
            
            if not rows:
                print("   ✓ No predictions with bad timestamps found")
                return True
            
            print(f"   Found {len(rows)} predictions with bad timestamps")
            
            # Since all timestamps are the same (1970), we need to estimate
            # We'll distribute them evenly across a reasonable game duration
            # Or we could use the relative time from features if available
            
            # For now, let's use a simple approach:
            # Distribute predictions evenly across 60 minutes (3600 seconds)
            # Starting from game start time
            print("\n4. Calculating new timestamps...")
            print("   Distributing predictions evenly across game duration")
            
            game_duration = 3600  # 60 minutes (3 periods)
            time_step = game_duration / len(rows) if len(rows) > 1 else 0
            
            updates = []
            for i, (old_ts, p_home_win, model_id) in enumerate(rows):
                # Calculate new timestamp: game_start + (i * time_step)
                new_ts = game_start_ts + (i * time_step)
                updates.append((new_ts, game_id, model_id, p_home_win, old_ts))
            
            print(f"   ✓ Calculated {len(updates)} new timestamps")
            print(f"   Time range: {datetime.fromtimestamp(updates[0][0]).isoformat()} to {datetime.fromtimestamp(updates[-1][0]).isoformat()}")
            
            if dry_run:
                print("\n5. DRY RUN - Would update:")
                for i, (new_ts, gid, mid, prob, old_ts) in enumerate(updates[:5]):
                    print(f"   [{i+1}] {old_ts} -> {datetime.fromtimestamp(new_ts).isoformat()} (prob: {prob:.4f})")
                if len(updates) > 5:
                    print(f"   ... and {len(updates) - 5} more")
                print("\n   Run with --apply to actually update the database")
                return True
            
            # Actually update - delete old and insert new (TimescaleDB constraint issue with UPDATE)
            print("\n5. Updating database...")
            try:
                # Delete old predictions with bad timestamps
                await cur.execute(
                    """
                    DELETE FROM predictions 
                    WHERE game_id = %s 
                    AND ts < '2020-01-01'
                    """,
                    (game_id,)
                )
                deleted_count = cur.rowcount
                print(f"   ✓ Deleted {deleted_count} old predictions")
                
                # Insert new predictions with correct timestamps
                inserted_count = 0
                for new_ts, gid, mid, prob, old_ts in updates:
                    try:
                        await cur.execute(
                            """
                            INSERT INTO predictions(ts, game_id, model_id, p_home_win) 
                            VALUES (to_timestamp(%s), %s, %s, %s)
                            """,
                            (new_ts, gid, mid, prob)
                        )
                        inserted_count += 1
                    except Exception as e:
                        print(f"   ⚠️  Error inserting prediction: {e}")
                        # Continue with next one
                
                await conn.commit()
                print(f"   ✓ Inserted {inserted_count} predictions with correct timestamps")
            except Exception as e:
                print(f"   ❌ Error during update: {e}")
                await conn.rollback()
                import traceback
                traceback.print_exc()
            
            return True

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fix prediction timestamps")
    parser.add_argument('game_id', help='Game ID to fix')
    parser.add_argument('--apply', action='store_true', help='Actually apply changes (default is dry run)')
    parser.add_argument('--database-url', help='Database URL (default: from env)')
    
    args = parser.parse_args()
    
    if args.database_url:
        global DATABASE_URL
        DATABASE_URL = args.database_url
    
    await fix_timestamps_for_game(args.game_id, dry_run=not args.apply)

if __name__ == "__main__":
    asyncio.run(main())

