"""
Utility functions for training pipeline.
"""

import os
import yaml
import json
import logging
from typing import Dict, Optional
from datetime import datetime
import pandas as pd


def setup_logging(log_level: str = "INFO", log_file: Optional[str] = None):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            *([logging.FileHandler(log_file)] if log_file else []),
        ],
    )
    return logging.getLogger(__name__)


def load_config(config_path: str) -> Dict:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config


def save_config(config: Dict, output_path: str):
    """Save configuration to YAML file."""
    with open(output_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def merge_configs(base_config: Dict, override_config: Dict) -> Dict:
    """Merge two configuration dictionaries."""
    merged = base_config.copy()

    for key, value in override_config.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value

    return merged


def create_experiment_dir(base_dir: str = "experiments") -> str:
    """Create a new experiment directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiment_dir = os.path.join(base_dir, f"experiment_{timestamp}")
    os.makedirs(experiment_dir, exist_ok=True)
    return experiment_dir


def save_experiment_results(
    experiment_dir: str, metrics: Dict, config: Dict, feature_importance: pd.DataFrame
):
    """Save experiment results to directory."""
    # Save metrics
    metrics_file = os.path.join(experiment_dir, "metrics.json")
    with open(metrics_file, "w") as f:
        json.dump(metrics, f, indent=2)

    # Save config
    config_file = os.path.join(experiment_dir, "config.yaml")
    save_config(config, config_file)

    # Save feature importance
    importance_file = os.path.join(experiment_dir, "feature_importance.csv")
    feature_importance.to_csv(importance_file, index=False)


def print_metrics(metrics: Dict, title: str = "Metrics"):
    """Pretty print metrics."""
    print(f"\n{title}:")
    print("-" * 50)
    for metric, value in metrics.items():
        if isinstance(value, float):
            print(f"  {metric:20s}: {value:.4f}")
        else:
            print(f"  {metric:20s}: {value}")
    print("-" * 50)


def validate_config(config: Dict) -> bool:
    """Validate configuration."""
    required_keys = ["training"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")

    training = config["training"]
    required_training_keys = ["model_type", "hyperparameters"]
    for key in required_training_keys:
        if key not in training:
            raise ValueError(f"Missing required training config key: {key}")

    return True
