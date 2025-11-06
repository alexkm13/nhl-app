#!/usr/bin/env python3
"""
Run A/B test and generate predictions for analysis.
"""
import os
import sys
import asyncio
from typing import Optional
import psycopg

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model_svc.model_loader import load_production_model
from model_svc.feature_engineer import engineer_features
import pandas as pd


async def generate_predictions_from_features(
    db_url: str,
    redis_url: str,
    model_id: str,
    days: int = 7,
    limit: Optional[int] = None
):
    """
    Generate predictions from existing features in database.
    
    Args:
        db_url: Database URL
        redis_url: Redis URL
        model_id: Model ID to use
        days: Number of days to process
        limit: Optional limit on number of predictions
    """
    print(f"Loading model: {model_id}")
    model_loader = load_production_model(model_id)
    model = model_loader.model
    model_type = model_loader.model_type
    
    print(f"Model type: {model_type}")
    print(f"Processing features from last {days} days...")
    
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # Get features
            query = """
                SELECT DISTINCT ON (game_id, ts)
                    ts,
                    game_id,
                    home_score,
                    away_score,
                    strength,
                    last_event
                FROM features
                WHERE ts >= NOW() - INTERVAL %s
                ORDER BY game_id, ts, home_score DESC
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            cur.execute(query, (f"{days} days",))
            
            features_list = cur.fetchall()
            print(f"Found {len(features_list)} feature snapshots")
            
            if not features_list:
                print("No features found. Run ingestor first.")
                return
            
            # Generate predictions
            predictions = []
            for row in features_list:
                ts, game_id, home_score, away_score, strength, last_event = row
                
                try:
                    # Calculate seconds elapsed (simplified - would need game start time)
                    # For now, use timestamp as proxy
                    seconds_elapsed = 0  # Would need to calculate from game start
                    
                    # Prepare features
                    if model_type == "baseline":
                        p_home = model.predict(home_score, away_score, seconds_elapsed)
                        raw_features = {
                            'home_score': home_score,
                            'away_score': away_score,
                            'seconds_elapsed': seconds_elapsed,
                            'strength': strength or 'EV',
                            'last_event': last_event or 'FACEOFF',
                        }
                    else:
                        # Trained model
                        raw_features = {
                            'home_score': home_score,
                            'away_score': away_score,
                            'seconds_elapsed': seconds_elapsed,  # Would need actual game time
                            'strength': strength or 'EV',
                            'last_event': last_event or 'FACEOFF',
                        }
                        engineered_features = engineer_features(raw_features)
                        feature_df = pd.DataFrame([engineered_features])
                        p_home = float(model.predict(feature_df)[0])
                    
                    # Store prediction
                    predictions.append({
                        'ts': ts,
                        'game_id': game_id,
                        'model_id': model_id,
                        'p_home_win': p_home,
                        'home_score': home_score,
                        'away_score': away_score,
                    })
                    
                    if len(predictions) % 100 == 0:
                        print(f"Generated {len(predictions)} predictions...")
                        
                except Exception as e:
                    print(f"Error generating prediction for {game_id} at {ts}: {e}")
                    continue
            
            # Insert predictions into database
            print(f"Inserting {len(predictions)} predictions into database...")
            insert_count = 0
            with conn.cursor() as insert_cur:
                for pred in predictions:
                    try:
                        insert_cur.execute(
                            """
                            INSERT INTO predictions (ts, game_id, model_id, p_home_win)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                            """,
                            (pred['ts'], pred['game_id'], pred['model_id'], pred['p_home_win'])
                        )
                        insert_count += 1
                    except Exception as e:
                        print(f"Error inserting prediction: {e}")
                        continue
                
                conn.commit()
            
            print(f"Inserted {insert_count} predictions")
            return predictions


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate predictions for A/B testing")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"),
                       help="Database URL")
    parser.add_argument("--redis-url", default=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
                       help="Redis URL")
    parser.add_argument("--model-id", default="lightgbm_20251104_115151_e21578a7",
                       help="Model ID to use")
    parser.add_argument("--days", type=int, default=7,
                       help="Number of days to process")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of predictions")
    
    args = parser.parse_args()
    
    if not args.db_url:
        print("Error: DATABASE_URL not provided")
        sys.exit(1)
    
    # Run async function
    asyncio.run(generate_predictions_from_features(
        args.db_url,
        args.redis_url,
        args.model_id,
        args.days,
        args.limit
    ))


if __name__ == "__main__":
    main()

