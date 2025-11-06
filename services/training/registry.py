"""
Model registry and versioning.
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Dict, Optional
import pandas as pd


class ModelRegistry:
    """Model registry for versioning and tracking."""

    def __init__(self, registry_dir: str = "models"):
        self.registry_dir = registry_dir
        os.makedirs(registry_dir, exist_ok=True)

        # Create registry index file
        self.index_file = os.path.join(registry_dir, "registry.json")
        if not os.path.exists(self.index_file):
            with open(self.index_file, "w") as f:
                json.dump({}, f)

    def _load_index(self) -> Dict:
        """Load registry index."""
        with open(self.index_file, "r") as f:
            return json.load(f)

    def _save_index(self, index: Dict):
        """Save registry index."""
        with open(self.index_file, "w") as f:
            json.dump(index, f, indent=2)

    def _generate_model_id(self, model_type: str, config: Dict) -> str:
        """Generate unique model ID from config."""
        config_str = json.dumps(config, sort_keys=True)
        hash_str = hashlib.md5(config_str.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{model_type}_{timestamp}_{hash_str}"

    def register_model(
        self,
        model,
        model_type: str,
        config: Dict,
        metrics: Dict,
        feature_importance: pd.DataFrame,
        model_filepath: str,
    ) -> str:
        """
        Register a model in the registry.

        Args:
            model: Trained model
            model_type: Type of model (xgboost, lightgbm, etc.)
            config: Training configuration
            metrics: Evaluation metrics
            feature_importance: Feature importance DataFrame
            model_filepath: Path to saved model file

        Returns:
            Model ID
        """
        model_id = self._generate_model_id(model_type, config)

        # Create model directory
        model_dir = os.path.join(self.registry_dir, model_id)
        os.makedirs(model_dir, exist_ok=True)

        # Save metadata
        metadata = {
            "model_id": model_id,
            "model_type": model_type,
            "timestamp": datetime.now().isoformat(),
            "config": config,
            "metrics": metrics,
            "model_file": model_filepath,
            "feature_columns": model.feature_columns,
        }

        metadata_file = os.path.join(model_dir, "metadata.json")
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        # Save feature importance
        feature_importance_file = os.path.join(model_dir, "feature_importance.csv")
        feature_importance.to_csv(feature_importance_file, index=False)

        # Update registry index
        index = self._load_index()
        index[model_id] = {
            "model_type": model_type,
            "timestamp": metadata["timestamp"],
            "metrics": metrics,
            "model_dir": model_dir,
            "is_active": False,  # New models not active by default
        }
        self._save_index(index)

        return model_id

    def list_models(self) -> pd.DataFrame:
        """List all registered models."""
        index = self._load_index()
        if not index:
            return pd.DataFrame()

        records = []
        for model_id, info in index.items():
            record = {
                "model_id": model_id,
                "model_type": info["model_type"],
                "timestamp": info["timestamp"],
                "is_active": info.get("is_active", False),
                **info["metrics"],
            }
            records.append(record)

        return pd.DataFrame(records).sort_values("timestamp", ascending=False)

    def get_model_info(self, model_id: str) -> Optional[Dict]:
        """Get information about a specific model."""
        index = self._load_index()
        if model_id not in index:
            return None

        info = index[model_id].copy()
        metadata_file = os.path.join(info["model_dir"], "metadata.json")

        if os.path.exists(metadata_file):
            with open(metadata_file, "r") as f:
                info["metadata"] = json.load(f)

        return info

    def set_active_model(self, model_id: str):
        """Set a model as the active (production) model."""
        index = self._load_index()
        if model_id not in index:
            raise ValueError(f"Model {model_id} not found in registry")

        # Deactivate all other models
        for mid in index:
            index[mid]["is_active"] = False

        # Activate this model
        index[model_id]["is_active"] = True
        self._save_index(index)

    def get_active_model(self) -> Optional[str]:
        """Get the active model ID."""
        index = self._load_index()
        for model_id, info in index.items():
            if info.get("is_active", False):
                return model_id
        return None
