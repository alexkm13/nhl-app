#!/usr/bin/env python3
"""
Main training script for win probability prediction model.
"""

import os
import sys
import asyncio
import argparse
from sklearn.model_selection import train_test_split

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import load_training_data
from features import engineer_features
from model import WinProbabilityModel
from evaluate import evaluate_model
from registry import ModelRegistry
from utils import (
    setup_logging,
    load_config,
    merge_configs,
    create_experiment_dir,
    save_experiment_results,
    print_metrics,
    validate_config,
)


async def main():
    """Main training function."""
    parser = argparse.ArgumentParser(description="Train win probability model")
    parser.add_argument(
        "--config", type=str, default="config.yaml", help="Path to configuration file"
    )
    parser.add_argument(
        "--model-type",
        type=str,
        choices=["xgboost", "lightgbm", "catboost"],
        help="Override model type from config",
    )
    parser.add_argument("--epochs", type=int, help="Override n_estimators")
    parser.add_argument("--learning-rate", type=float, help="Override learning rate")
    parser.add_argument("--max-depth", type=int, help="Override max depth")
    parser.add_argument("--database-url", type=str, help="Override database URL")
    parser.add_argument("--experiment-dir", type=str, help="Experiment directory")
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--save-model", action="store_true", help="Save model to registry"
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_logging(args.log_level)
    logger.info("Starting training pipeline")

    # Load configuration
    if not os.path.exists(args.config):
        logger.error(f"Config file not found: {args.config}")
        sys.exit(1)

    config = load_config(args.config)
    validate_config(config)

    # Override config with command line arguments
    override_config = {}
    if args.model_type:
        override_config["training"] = {"model_type": args.model_type}
    if args.epochs:
        if "training" not in override_config:
            override_config["training"] = {}
        if "hyperparameters" not in override_config["training"]:
            override_config["training"]["hyperparameters"] = {}
        override_config["training"]["hyperparameters"]["n_estimators"] = args.epochs
    if args.learning_rate:
        if "training" not in override_config:
            override_config["training"] = {}
        if "hyperparameters" not in override_config["training"]:
            override_config["training"]["hyperparameters"] = {}
        override_config["training"]["hyperparameters"]["learning_rate"] = (
            args.learning_rate
        )
    if args.max_depth:
        if "training" not in override_config:
            override_config["training"] = {}
        if "hyperparameters" not in override_config["training"]:
            override_config["training"]["hyperparameters"] = {}
        override_config["training"]["hyperparameters"]["max_depth"] = args.max_depth

    config = merge_configs(config, override_config)

    # Get database URL
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error(
            "DATABASE_URL not provided. Set environment variable or use --database-url"
        )
        sys.exit(1)

    # Create experiment directory
    if args.experiment_dir:
        experiment_dir = args.experiment_dir
        os.makedirs(experiment_dir, exist_ok=True)
    else:
        experiment_dir = create_experiment_dir()

    logger.info(f"Experiment directory: {experiment_dir}")

    # Load training data
    logger.info("Loading training data...")
    training_config = config["training"]

    try:
        train_df, test_df = await load_training_data(
            database_url,
            training_config["train_start_date"],
            training_config["train_end_date"],
            training_config["test_start_date"],
            training_config["test_end_date"],
        )
        logger.info(
            f"Loaded {len(train_df)} training samples, {len(test_df)} test samples"
        )
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        sys.exit(1)

    # Engineer features
    logger.info("Engineering features...")
    train_features_df, feature_columns = engineer_features(train_df, config)
    test_features_df, _ = engineer_features(test_df, config)

    # Prepare features and labels
    X_train = train_features_df[feature_columns]
    y_train = train_features_df["label"]

    X_test = test_features_df[feature_columns]
    y_test = test_features_df["label"]

    # Split training data for validation
    validation_split = training_config.get("validation_split", 0.2)
    if validation_split > 0:
        X_train_split, X_val_split, y_train_split, y_val_split = train_test_split(
            X_train,
            y_train,
            test_size=validation_split,
            random_state=config["training"].get("random_seed", 42),
            stratify=y_train,
        )
    else:
        X_train_split, X_val_split = X_train, None
        y_train_split, y_val_split = y_train, None

    # Train model
    logger.info(f"Training {training_config['model_type']} model...")
    model_config = {
        "model_type": training_config["model_type"],
        "random_seed": training_config.get("random_seed", 42),
        **training_config.get("hyperparameters", {}),
    }

    model = WinProbabilityModel(
        model_type=model_config["model_type"], **model_config.get("hyperparameters", {})
    )
    model.train(X_train_split, y_train_split, X_val_split, y_val_split)

    # Evaluate model
    logger.info("Evaluating model...")
    evaluation_results = evaluate_model(
        model,
        X_test,
        y_test,
        test_features_df,
        metrics=training_config.get("metrics", []),
    )

    # Print results
    print_metrics(evaluation_results["overall_metrics"], "Overall Metrics")

    # Save experiment results
    save_experiment_results(
        experiment_dir,
        evaluation_results["overall_metrics"],
        config,
        evaluation_results["feature_importance"],
    )

    # Save model
    model_filepath = os.path.join(experiment_dir, "model.pkl")
    model.save(model_filepath)
    logger.info(f"Model saved to {model_filepath}")

    # Register model if requested
    if args.save_model:
        logger.info("Registering model in registry...")
        registry = ModelRegistry()
        model_id = registry.register_model(
            model,
            training_config["model_type"],
            config,
            evaluation_results["overall_metrics"],
            evaluation_results["feature_importance"],
            model_filepath,
        )
        logger.info(f"Model registered with ID: {model_id}")
        print(f"\nModel ID: {model_id}")
        print("To activate this model, run:")
        print(f"  registry.set_active_model('{model_id}')")

    # Print feature importance
    print("\nTop 10 Most Important Features:")
    print(evaluation_results["feature_importance"].head(10).to_string(index=False))

    logger.info("Training completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
