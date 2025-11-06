"""
Data loading and preprocessing for ML training pipeline.
"""

from typing import List, Optional, Tuple
import pandas as pd
import psycopg
from psycopg.rows import dict_row


class DataLoader:
    """Load and preprocess training data from TimescaleDB."""

    def __init__(self, database_url: str):
        self.database_url = database_url

    async def load_game_data(
        self, start_date: str, end_date: str, game_ids: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        Load game features and outcomes from database.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            game_ids: Optional list of specific game IDs to load

        Returns:
            DataFrame with features and labels
        """
        async with await psycopg.AsyncConnection.connect(
            self.database_url, row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cur:
                # Load features
                query = """
                    SELECT 
                        ts,
                        game_id,
                        home_score,
                        away_score,
                        strength,
                        last_event
                    FROM features
                    WHERE ts >= %s AND ts <= %s
                """
                params = [start_date, end_date]

                if game_ids:
                    placeholders = ",".join(["%s"] * len(game_ids))
                    query += f" AND game_id IN ({placeholders})"
                    params.extend(game_ids)

                query += " ORDER BY game_id, ts"

                await cur.execute(query, params)
                features_data = await cur.fetchall()

        if not features_data:
            raise ValueError(f"No data found between {start_date} and {end_date}")

        df = pd.DataFrame(features_data)
        df["ts"] = pd.to_datetime(df["ts"])

        return df

    async def load_game_outcomes(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Load final game outcomes from NHL API or database.

        Returns:
            DataFrame with game_id, home_won (0/1), final_home_score, final_away_score
        """
        # For now, we'll determine outcomes from the last feature snapshot
        # In production, you'd fetch from NHL API or maintain a games table
        async with await psycopg.AsyncConnection.connect(
            self.database_url, row_factory=dict_row
        ) as conn:
            async with conn.cursor() as cur:
                query = """
                    SELECT DISTINCT ON (game_id)
                        game_id,
                        home_score as final_home_score,
                        away_score as final_away_score,
                        ts
                    FROM features
                    WHERE ts >= %s AND ts <= %s
                    ORDER BY game_id, ts DESC
                """
                await cur.execute(query, [start_date, end_date])
                outcomes = await cur.fetchall()

        df = pd.DataFrame(outcomes)
        if len(df) == 0:
            raise ValueError("No game outcomes found")

        # Determine winner (home_won = 1 if home_score > away_score)
        df["home_won"] = (df["final_home_score"] > df["final_away_score"]).astype(int)

        return df

    async def load_game_stats(self, game_ids: List[str]) -> Optional[pd.DataFrame]:
        """
        Load additional game statistics from gateway API.

        This would fetch stats like shots, hits, faceoffs, etc. from the
        gateway's stats endpoint. For now, returns None - can be implemented
        by calling the gateway API or storing in database.
        """
        # TODO: Implement API call to gateway /v1/games/{game_id}/stats
        # or store stats in database during ingestion
        return None

    def create_training_samples(
        self,
        features_df: pd.DataFrame,
        outcomes_df: pd.DataFrame,
        min_time_elapsed: float = 60.0,  # Minimum 1 minute of game time
        max_time_elapsed: float = 3600.0,  # Maximum 60 minutes (overtime)
        sample_interval: float = 30.0,  # Sample every 30 seconds
    ) -> pd.DataFrame:
        """
        Create training samples from features and outcomes.

        Args:
            features_df: DataFrame with game features over time
            outcomes_df: DataFrame with final game outcomes
            min_time_elapsed: Minimum seconds into game to sample
            max_time_elapsed: Maximum seconds into game to sample
            sample_interval: Interval between samples in seconds

        Returns:
            DataFrame with one row per sample, including labels
        """
        samples = []

        for game_id in features_df["game_id"].unique():
            game_features = features_df[features_df["game_id"] == game_id].copy()
            game_features = game_features.sort_values("ts")

            # Get outcome for this game
            outcome = outcomes_df[outcomes_df["game_id"] == game_id]
            if len(outcome) == 0:
                continue

            home_won = outcome["home_won"].iloc[0]

            # Calculate time elapsed from game start
            game_start = game_features["ts"].min()
            game_features["seconds_elapsed"] = (
                game_features["ts"] - game_start
            ).dt.total_seconds()

            # Filter by time constraints
            game_features = game_features[
                (game_features["seconds_elapsed"] >= min_time_elapsed)
                & (game_features["seconds_elapsed"] <= max_time_elapsed)
            ]

            # Sample at intervals
            if len(game_features) > 0:
                # Sample every N seconds
                last_sample_time = -sample_interval
                for idx, row in game_features.iterrows():
                    if row["seconds_elapsed"] - last_sample_time >= sample_interval:
                        sample = row.to_dict()
                        sample["label"] = home_won
                        samples.append(sample)
                        last_sample_time = row["seconds_elapsed"]

        if not samples:
            raise ValueError("No training samples created")

        df = pd.DataFrame(samples)
        return df


async def load_training_data(
    database_url: str, train_start: str, train_end: str, test_start: str, test_end: str
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load training and test datasets.

    Returns:
        Tuple of (train_df, test_df)
    """
    loader = DataLoader(database_url)

    # Load training data
    train_features = await loader.load_game_data(train_start, train_end)
    train_outcomes = await loader.load_game_outcomes(train_start, train_end)
    train_samples = loader.create_training_samples(train_features, train_outcomes)

    # Load test data
    test_features = await loader.load_game_data(test_start, test_end)
    test_outcomes = await loader.load_game_outcomes(test_start, test_end)
    test_samples = loader.create_training_samples(test_features, test_outcomes)

    return train_samples, test_samples
