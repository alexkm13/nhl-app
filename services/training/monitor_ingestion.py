#!/usr/bin/env python3
"""
Monitor ingestion progress and notify when complete.
"""
import time
import subprocess
import sys
from datetime import datetime


def check_process_running():
    """Check if ingestion process is still running."""
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            check=True
        )
        return "ingest_historical.py.*2020-10-01" in result.stdout or \
               "ingest_historical.py --start-date 2020-10-01" in result.stdout
    except Exception:
        return False


def get_game_count():
    """Get current game count in database."""
    try:
        result = subprocess.run(
            [
                "docker", "compose", "exec", "-T", "timescaledb",
                "psql", "-U", "postgres", "-d", "gamecast",
                "-c", "SELECT COUNT(DISTINCT game_id) as games FROM features WHERE ts >= '2020-10-01' AND ts < '2024-10-01';"
            ],
            capture_output=True,
            text=True,
            check=True
        )
        # Parse output to get game count
        lines = result.stdout.strip().split('\n')
        for line in lines:
            if line.strip().isdigit():
                return int(line.strip())
        # Try to find number in output
        for line in lines:
            parts = line.split('|')
            if len(parts) >= 2:
                try:
                    return int(parts[1].strip())
                except ValueError:
                    continue
        return None
    except Exception as e:
        print(f"Error checking game count: {e}")
        return None


def main():
    """Monitor ingestion and notify when complete."""
    print(f"[{datetime.now()}] Starting ingestion monitor...")
    print("Monitoring ingestion from 2020-10-01 to 2024-09-30")
    print("Press Ctrl+C to stop monitoring\n")
    
    last_count = 0
    stable_count = 0
    check_interval = 60  # Check every 60 seconds
    
    while True:
        try:
            # Check if process is running
            is_running = check_process_running()
            
            # Get current game count
            game_count = get_game_count()
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if game_count is not None:
                if game_count > last_count:
                    print(f"[{current_time}] ✓ Process running - {game_count} games ingested (increased from {last_count})")
                    last_count = game_count
                    stable_count = 0
                elif game_count == last_count:
                    stable_count += 1
                    if is_running:
                        print(f"[{current_time}] ⏳ Process running - {game_count} games ingested (no change for {stable_count} checks)")
                    else:
                        print(f"[{current_time}] ⚠️ Process not found - {game_count} games ingested")
                else:
                    print(f"[{current_time}] ⚠️ Game count decreased: {game_count} (was {last_count})")
                    last_count = game_count
            else:
                print(f"[{current_time}] ⚠️ Could not get game count")
            
            # Check if ingestion is complete
            if not is_running:
                if stable_count >= 3:  # Wait 3 checks to confirm it's done
                    print(f"\n{'='*60}")
                    print(f"[{datetime.now()}] ✅ INGESTION COMPLETE!")
                    print(f"{'='*60}")
                    print(f"Final game count: {game_count}")
                    print("\nYou can now retrain the model with:")
                    print("  cd services/training")
                    print("  export DATABASE_URL='postgresql://postgres:postgres@localhost:5432/gamecast'")
                    print("  python3 train.py --database-url \"$DATABASE_URL\" --config config.yaml --save-model")
                    print(f"{'='*60}\n")
                    sys.exit(0)
                else:
                    stable_count += 1
            
            # Wait before next check
            time.sleep(check_interval)
            
        except KeyboardInterrupt:
            print(f"\n[{datetime.now()}] Monitoring stopped by user")
            print(f"Current game count: {game_count}")
            sys.exit(0)
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}")
            time.sleep(check_interval)


if __name__ == "__main__":
    main()

