#!/usr/bin/env python3
"""
Run model improvements and A/B testing.
"""

import os
import sys
import argparse
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model import WinProbabilityModel
from evaluate import evaluate_model
from registry import ModelRegistry
from utils import setup_logging, load_config
from sklearn.model_selection import train_test_split
import pandas as pd


async def train_improved_model(config_path: str, save_model: bool = True):
    """Train improved model with better hyperparameters."""
    print("=" * 80)
    print("Training Improved Model")
    print("=" * 80)

    # Load configuration
    config = load_config(config_path)
    training_config = config["training"]

    # Setup logging
    setup_logging(training_config.get("log_level", "INFO"))

    # Load data
    print("\nLoading training data...")
    from data import DataLoader

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not provided")
        return None

    loader = DataLoader(db_url)

    # Load training data
    train_data = await loader.load_game_data(
        start_date=training_config["train_start_date"],
        end_date=training_config["train_end_date"],
    )

    # Load test data
    test_data = await loader.load_game_data(
        start_date=training_config["test_start_date"],
        end_date=training_config["test_end_date"],
    )

    if train_data is None or train_data.empty:
        print("Error: No training data loaded")
        return None

    print(f"Loaded {len(train_data)} training samples, {len(test_data)} test samples")

    # Create training samples
    print("\nCreating training samples...")
    train_samples = loader.create_training_samples(
        train_data,
        await loader.load_game_outcomes(
            training_config["train_start_date"], training_config["train_end_date"]
        ),
    )
    test_samples = loader.create_training_samples(
        test_data,
        await loader.load_game_outcomes(
            training_config["test_start_date"], training_config["test_end_date"]
        ),
    )

    if train_samples is None or train_samples.empty:
        print("Error: No training samples created")
        return None

    print(
        f"Created {len(train_samples)} training samples, {len(test_samples)} test samples"
    )

    # Engineer features
    print("\nEngineering features...")
    from features import FeatureEngineer

    feature_engineer = FeatureEngineer(training_config)
    train_features_df = feature_engineer.create_features(train_samples)
    test_features_df = feature_engineer.create_features(test_samples)

    # Get feature columns (exclude metadata)
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
    feature_columns = [
        col for col in train_features_df.columns if col not in exclude_cols
    ]

    X_train = train_features_df[feature_columns]
    y_train = train_features_df["label"]
    X_test = test_features_df[feature_columns]
    y_test = test_features_df["label"]

    print(f"Features: {len(feature_columns)}")
    print(f"Training samples: {len(X_train)}")
    print(f"Test samples: {len(X_test)}")

    # Model configuration
    model_config = training_config.get("model", {})
    model_type = model_config.get("model_type", "lightgbm")
    hyperparameters = model_config.get("hyperparameters", {}).copy()

    # Calculate scale_pos_weight for better calibration
    if isinstance(y_train, pd.Series):
        pos_weight = (len(y_train) - y_train.sum()) / y_train.sum()
    else:
        pos_weight = (len(y_train) - sum(y_train)) / sum(y_train)
    hyperparameters["scale_pos_weight"] = pos_weight
    print(f"\nScale pos weight: {pos_weight:.3f}")

    # Split training data for validation
    X_train_split, X_val_split, y_train_split, y_val_split = train_test_split(
        X_train,
        y_train,
        test_size=training_config.get("validation_split", 0.2),
        random_state=training_config.get("random_seed", 42),
        stratify=y_train,
    )

    print(
        f"\nTraining split: {len(X_train_split)} train, {len(X_val_split)} validation"
    )

    # Split training data for validation
    X_train_split, X_val_split, y_train_split, y_val_split = train_test_split(
        X_train,
        y_train,
        test_size=training_config.get("validation_split", 0.2),
        random_state=training_config.get("random_seed", 42),
        stratify=y_train,
    )

    print(
        f"\nTraining split: {len(X_train_split)} train, {len(X_val_split)} validation"
    )

    # Train model
    print(f"\nTraining {model_type} model with improved hyperparameters...")
    model = WinProbabilityModel(model_type=model_type, **hyperparameters)

    model.train(X_train_split, y_train_split, X_val_split, y_val_split)

    # Evaluate
    print("\nEvaluating model...")
    # Create test DataFrame with predictions
    test_df = test_features_df.copy()
    test_df["prediction"] = model.predict(X_test)

    # Convert y_test to Series if needed
    if not isinstance(y_test, pd.Series):
        y_test_series = pd.Series(y_test)
    else:
        y_test_series = y_test

    evaluation_results = evaluate_model(model, X_test, y_test_series, test_df)

    print("\n" + "=" * 80)
    print("Evaluation Results")
    print("=" * 80)

    # Extract overall metrics
    overall = evaluation_results.get("overall_metrics", {})
    for metric, value in overall.items():
        if isinstance(value, (int, float)):
            print(f"  {metric:20s}: {value:.4f}")

    # Compare to baseline
    print("\n" + "-" * 80)
    print("Comparison to Previous Model")
    print("-" * 80)

    # Load previous model metrics
    registry = ModelRegistry()
    prev_model_id = "lightgbm_20251104_115151_e21578a7"
    prev_model_info = registry.get_model_info(prev_model_id)

    if prev_model_info:
        prev_metrics = prev_model_info.get("metadata", {}).get("metrics", {})
        print("\nPrevious Model Metrics:")
        for metric, value in prev_metrics.items():
            print(f"  {metric:20s}: {value:.4f}")

        print("\nImprovements:")
        overall = evaluation_results.get("overall_metrics", {})
        for metric in overall.keys():
            if metric in prev_metrics:
                prev_val = prev_metrics[metric]
                new_val = overall[metric]
                diff = new_val - prev_val
                pct = (diff / prev_val * 100) if prev_val != 0 else 0

                # For metrics where lower is better
                if metric in ["log_loss", "brier_score", "calibration_error"]:
                    if diff < 0:
                        print(
                            f"  {metric:20s}: {diff:.4f} ({abs(pct):.2f}% improvement)"
                        )
                    else:
                        print(f"  {metric:20s}: {diff:+.4f} ({abs(pct):.2f}% worse)")
                else:
                    # For metrics where higher is better
                    if diff > 0:
                        print(
                            f"  {metric:20s}: {diff:+.4f} ({abs(pct):.2f}% improvement)"
                        )
                    else:
                        print(f"  {metric:20s}: {diff:.4f} ({abs(pct):.2f}% worse)")

    # Save model
    if save_model:
        print("\n" + "=" * 80)
        print("Saving Model")
        print("=" * 80)

        # Save model first to get filepath
        experiment_dir = os.path.join(
            "experiments", f"experiment_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        os.makedirs(experiment_dir, exist_ok=True)
        model_filepath = os.path.join(experiment_dir, "model.pkl")
        model.save(model_filepath)

        model_id = registry.register_model(
            model=model,
            model_type=model_type,
            config=training_config,
            metrics=evaluation_results.get("overall_metrics", {}),
            feature_importance=model.get_feature_importance(),
            model_filepath=model_filepath,
        )

        print(f"\nModel registered with ID: {model_id}")
        print(f"To use this model, set MODEL_ID={model_id}")
        print("To run A/B test, set AB_TEST_ENABLED=true and configure variants")

    return model, evaluation_results


async def main_async():
    parser = argparse.ArgumentParser(description="Train improved model")
    parser.add_argument(
        "--config", default="config_improved.yaml", help="Config file path"
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL"), help="Database URL"
    )
    parser.add_argument(
        "--save-model", action="store_true", default=True, help="Save model to registry"
    )

    args = parser.parse_args()

    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    await train_improved_model(config_path=args.config, save_model=args.save_model)


def main():
    import asyncio

    asyncio.run(main_async())


if __name__ == "__main__":
    main()
