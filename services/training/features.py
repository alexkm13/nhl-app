"""
Feature engineering for win probability prediction.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple


class FeatureEngineer:
    """Engineer features from raw game data."""

    def __init__(self, config: Dict):
        self.config = config
        self.feature_config = config.get("features", {})

    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create engineered features from raw data.

        Args:
            df: DataFrame with raw game features

        Returns:
            DataFrame with engineered features
        """
        features_df = df.copy()

        # Score features
        if self.feature_config.get("include_score_features", True):
            features_df = self._add_score_features(features_df)

        # Time features
        if self.feature_config.get("include_time_features", True):
            features_df = self._add_time_features(features_df)

        # Strength features
        if self.feature_config.get("include_strength_features", True):
            features_df = self._add_strength_features(features_df)

        # Momentum features
        if self.feature_config.get("include_momentum_features", True):
            features_df = self._add_momentum_features(features_df)

        # Statistical features (if available)
        if self.feature_config.get("include_stat_features", True):
            features_df = self._add_stat_features(features_df)

        # Recent events
        if self.feature_config.get("include_recent_events", True):
            features_df = self._add_recent_event_features(features_df)

        return features_df

    def _add_score_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add score-related features."""
        df = df.copy()

        # Score differential
        df["score_diff"] = df["home_score"] - df["away_score"]
        df["score_diff_abs"] = abs(df["score_diff"])

        # Total goals
        df["total_goals"] = df["home_score"] + df["away_score"]

        # Score ratio (avoid division by zero)
        df["score_ratio"] = np.where(
            df["away_score"] > 0,
            df["home_score"] / (df["away_score"] + 1),
            df["home_score"] + 1,
        )

        # Leading indicator
        df["home_leading"] = (df["score_diff"] > 0).astype(int)
        df["away_leading"] = (df["score_diff"] < 0).astype(int)
        df["tied"] = (df["score_diff"] == 0).astype(int)

        return df

    def _add_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add time-related features."""
        df = df.copy()

        if "seconds_elapsed" not in df.columns:
            # Calculate from ts if needed
            df["seconds_elapsed"] = df.groupby("game_id")["ts"].transform(
                lambda x: (x - x.min()).dt.total_seconds()
            )

        # Time features
        df["minutes_elapsed"] = df["seconds_elapsed"] / 60.0
        df["period"] = (df["minutes_elapsed"] / 20.0).astype(int) + 1
        df["period"] = df["period"].clip(upper=7)  # Max 7 periods (OT + shootout)

        # Time remaining (assuming 60 min regulation)
        df["time_remaining"] = 3600.0 - df["seconds_elapsed"]
        df["time_remaining"] = df["time_remaining"].clip(lower=0)

        # Normalized time (0 to 1)
        df["time_normalized"] = df["seconds_elapsed"] / 3600.0
        df["time_normalized"] = df["time_normalized"].clip(upper=1.0)

        # Period indicator
        df["is_regulation"] = (df["period"] <= 3).astype(int)
        df["is_overtime"] = (df["period"] == 4).astype(int)
        df["is_shootout"] = (df["period"] > 4).astype(int)

        return df

    def _add_strength_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add strength situation features."""
        df = df.copy()

        # One-hot encode strength
        strength_dummies = pd.get_dummies(
            df["strength"], prefix="strength", dummy_na=False
        )
        df = pd.concat([df, strength_dummies], axis=1)

        # Power play indicators
        df["home_pp"] = (df["strength"].isin(["PP", "ENPP"])).astype(int)
        df["away_pp"] = (df["strength"] == "PK").astype(int)
        df["home_pk"] = (df["strength"] == "PK").astype(int)
        df["away_pk"] = (df["strength"].isin(["PP", "ENPP"])).astype(int)

        # Empty net
        if "empty_net" in df.columns:
            df["empty_net"] = df["empty_net"].astype(int)
        else:
            df["empty_net"] = (df["strength"].str.contains("EN", na=False)).astype(int)

        return df

    def _add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add momentum-related features."""
        df = df.copy()

        # Calculate rolling statistics per game
        window_size = self.feature_config.get("window_size_seconds", 300)

        for game_id in df["game_id"].unique():
            game_mask = df["game_id"] == game_id
            game_df = df[game_mask].sort_values("seconds_elapsed")

            # Rolling score change
            game_df["score_change_5min"] = game_df["score_diff"].diff().fillna(0)
            game_df["score_change_5min"] = (
                game_df["score_change_5min"]
                .rolling(
                    window=int(window_size / 30),  # Approx samples in window
                    min_periods=1,
                )
                .sum()
            )

            # Goals in last 5 minutes
            game_df["recent_goals"] = game_df["total_goals"].diff().fillna(0)
            game_df["recent_goals"] = (
                game_df["recent_goals"]
                .rolling(window=int(window_size / 30), min_periods=1)
                .sum()
            )

            df.loc[game_mask, "score_change_5min"] = game_df["score_change_5min"].values
            df.loc[game_mask, "recent_goals"] = game_df["recent_goals"].values

        return df

    def _add_stat_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add statistical features (shots, hits, faceoffs, etc.).

        Note: These would come from game stats API. For now, returns df as-is.
        """
        # TODO: Integrate with gateway stats API or database
        # Features would include:
        # - shots_for, shots_against
        # - shot_diff, shot_ratio
        # - corsi_for, corsi_against
        # - faceoff_win_pct
        # - hit_diff
        # - penalty_minutes
        # - power_play_opportunities
        # - etc.
        return df

    def _add_recent_event_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add features based on recent events."""
        df = df.copy()

        # One-hot encode last event
        event_dummies = pd.get_dummies(
            df["last_event"], prefix="last_event", dummy_na=False
        )
        df = pd.concat([df, event_dummies], axis=1)

        # Event type indicators
        df["recent_goal"] = (df["last_event"] == "GOAL").astype(int)
        df["recent_penalty"] = (df["last_event"] == "PENALTY").astype(int)
        df["recent_shot"] = (df["last_event"] == "SHOT").astype(int)

        return df

    def get_feature_columns(self, df: pd.DataFrame) -> List[str]:
        """Get list of feature column names (excluding metadata and labels)."""
        exclude_cols = {
            "ts",
            "game_id",
            "label",
            "home_score",
            "away_score",
            "strength",
            "last_event",
            "last_player_id",
            "empty_net",
        }
        return [col for col in df.columns if col not in exclude_cols]


def engineer_features(df: pd.DataFrame, config: Dict) -> Tuple[pd.DataFrame, List[str]]:
    """
    Main feature engineering function.

    Returns:
        Tuple of (feature_df, feature_columns)
    """
    engineer = FeatureEngineer(config)
    feature_df = engineer.create_features(df)
    feature_columns = engineer.get_feature_columns(feature_df)

    return feature_df, feature_columns
