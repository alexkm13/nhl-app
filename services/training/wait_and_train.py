#!/usr/bin/env python3
"""
Wait for historical data ingestion to complete, then train the model.
"""
import asyncio
import os
import sys
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gamecast")
START_DATE = "2019-10-01"
END_DATE = "2022-06-30"
MIN_GAMES = 2000  # Minimum games needed before training (roughly 2/3 of expected data)


async def check_data_availability():
    """Check if we have enough data for training."""
    try:
        async with await psycopg.AsyncConnection.connect(
            DATABASE_URL, row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cur:
                # Count games in date range
                await cur.execute(
                    """
                    SELECT COUNT(DISTINCT game_id) as game_count,
                           COUNT(*) as sample_count
                    FROM features
                    WHERE ts >= %s AND ts <= %s
                    """,
                    [START_DATE, END_DATE]
                )
                result = await cur.fetchone()
                return result['game_count'], result['sample_count']
    except Exception as e:
        print(f"Error checking data: {e}")
        return 0, 0


async def wait_for_data():
    """Wait until we have enough data."""
    print(f"Waiting for at least {MIN_GAMES} games to be ingested...")
    print(f"Date range: {START_DATE} to {END_DATE}")
    
    while True:
        game_count, sample_count = await check_data_availability()
        print(f"\rGames ingested: {game_count}, Samples: {sample_count:,}", end="", flush=True)
        
        if game_count >= MIN_GAMES:
            print(f"\n\n✓ Enough data available! ({game_count} games, {sample_count:,} samples)")
            return True
        
        # Check every 30 seconds
        await asyncio.sleep(30)


async def train_model():
    """Train the model once data is available."""
    print("\nStarting model training...")
    
    # Import and run training
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from train import main
    
    # Run training with the updated config
    await main()


async def main():
    """Main function."""
    print("=" * 60)
    print("Historical Data Ingestion Monitor & Training")
    print("=" * 60)
    
    # Wait for data
    await wait_for_data()
    
    # Train model
    await train_model()


if __name__ == "__main__":
    asyncio.run(main())

