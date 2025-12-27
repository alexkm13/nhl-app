"""
Model loading utilities for production model service.
"""

import os
from typing import Optional
from model import BaselineModel

# Try to import trained model, fallback if not available
try:
    from win_probability_model import WinProbabilityModel

    TRAINED_MODEL_AVAILABLE = True
except ImportError:
    try:
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "training"))
        from model import WinProbabilityModel

        TRAINED_MODEL_AVAILABLE = True
    except ImportError:
        WinProbabilityModel = None
        TRAINED_MODEL_AVAILABLE = False


class ModelLoader:
    """Load models for production inference."""

    def __init__(
        self, model_path: Optional[str] = None, model_id: Optional[str] = None
    ):
        """
        Initialize model loader.

        Args:
            model_path: Direct path to model file
            model_id: Model ID from registry (looks in models/registry/)
        """
        self.model_path = model_path
        self.model_id = model_id
        self.model = None
        self.model_type = None

    def load(self):
        """Load the model."""
        if self.model_path:
            # Load from direct path
            if os.path.exists(self.model_path):
                if WinProbabilityModel is None:
                    raise ImportError(
                        "Trained model class not available. Install training dependencies."
                    )
                self.model = WinProbabilityModel.load(self.model_path)
                self.model_type = "trained"
            else:
                raise FileNotFoundError(f"Model file not found: {self.model_path}")
        elif self.model_id:
            # Load from registry - try multiple possible locations
            # First try mounted volumes (Docker)
            # Try direct model path first (works for any model ID)
            possible_paths = [
                # Mounted volumes in Docker
                os.path.join("/app", "models", self.model_id, "model.pkl"),
            ]

            # Try experiment path only if model_id matches expected pattern (type_timestamp_hash)
            # Handle non-standard model IDs gracefully
            model_id_parts = self.model_id.split('_')
            if len(model_id_parts) >= 3:
                try:
                    # Assume format: type_timestamp_hash
                    possible_paths.append(
                        os.path.join(
                            "/app",
                            "experiments",
                            f"experiment_{model_id_parts[1]}_{model_id_parts[2]}",
                            "model.pkl",
                        )
                    )
                except (IndexError, ValueError):
                    # If parsing fails, skip experiment path
                    pass

            # Also try relative paths (local development)
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            training_dir = os.path.join(base_dir, "services", "training")
            possible_paths.extend(
                [
                    os.path.join(training_dir, "models", self.model_id, "model.pkl"),
                ]
            )

            # Try experiment path for relative paths too (if pattern matches)
            if len(model_id_parts) >= 3:
                try:
                    possible_paths.append(
                        os.path.join(
                            training_dir,
                            "experiments",
                            f"experiment_{model_id_parts[1]}_{model_id_parts[2]}",
                            "model.pkl",
                        )
                    )
                except (IndexError, ValueError):
                    pass

            # Try loading from registry metadata to get exact path
            # Try both mounted volume and relative paths
            registry_paths = [
                os.path.join("/app", "models", "registry.json"),  # Docker mount
                os.path.join(training_dir, "models", "registry.json"),  # Local
            ]

            for registry_index in registry_paths:
                if os.path.exists(registry_index):
                    import json

                    with open(registry_index, "r") as f:
                        registry = json.load(f)
                    if self.model_id in registry:
                        model_info = registry[self.model_id]

                        # Check metadata file for exact model path
                        registry_dir = os.path.dirname(registry_index)
                        model_dir_path = os.path.join(registry_dir, self.model_id)
                        metadata_file = os.path.join(model_dir_path, "metadata.json")
                        if os.path.exists(metadata_file):
                            with open(metadata_file, "r") as f:
                                metadata = json.load(f)
                                model_file_path = metadata.get("model_file", "")
                                if model_file_path:
                                    # Resolve relative path
                                    if not os.path.isabs(model_file_path):
                                        # Model file path is relative to training directory
                                        # Convert to absolute path based on where we found registry
                                        if registry_dir.startswith("/app"):
                                            # In Docker: experiments/experiment_.../model.pkl -> /app/experiments/...
                                            model_file_path = os.path.join(
                                                "/app", model_file_path
                                            )
                                        else:
                                            # Local: experiments/... -> training_dir/experiments/...
                                            model_file_path = os.path.join(
                                                training_dir, model_file_path
                                            )
                                    if os.path.exists(model_file_path):
                                        possible_paths.insert(0, model_file_path)

                        # Try relative path from registry (model_dir field)
                        model_dir = model_info.get("model_dir", "")
                        if model_dir:
                            # Handle relative path - model_dir is like "models/lightgbm_..."
                            if model_dir.startswith("models/"):
                                if registry_dir.startswith("/app"):
                                    model_path = os.path.join(
                                        "/app", model_dir, "model.pkl"
                                    )
                                else:
                                    model_path = os.path.join(
                                        training_dir, model_dir, "model.pkl"
                                    )
                            else:
                                model_path = os.path.join(
                                    registry_dir, model_dir, "model.pkl"
                                )
                            if os.path.exists(model_path):
                                possible_paths.insert(0, model_path)
                    break  # Found registry, no need to check other paths

            model_file = None
            for path in possible_paths:
                if path and os.path.exists(path):
                    model_file = path
                    break

            if model_file:
                if WinProbabilityModel is None:
                    raise ImportError(
                        "Trained model class not available. Install training dependencies (lightgbm, pandas)."
                    )
                self.model = WinProbabilityModel.load(model_file)
                self.model_type = "trained"
            else:
                raise FileNotFoundError(
                    f"Model {self.model_id} not found. Tried paths: {possible_paths}"
                )
        else:
            # Fallback to baseline model
            self.model = BaselineModel()
            self.model_type = "baseline"

        return self.model

    def predict(self, features: dict) -> float:
        """
        Predict win probability from features.

        Args:
            features: Dictionary with feature values

        Returns:
            Win probability (0.0 to 1.0)
        """
        if self.model is None:
            self.load()

        if self.model_type == "baseline":
            # Baseline model uses simple interface
            return self.model.predict(
                features.get("home_score", 0),
                features.get("away_score", 0),
                features.get("seconds_elapsed", 0.0),
            )
        else:
            # Trained model needs DataFrame with all features
            try:
                import pandas as pd
            except ImportError:
                raise ImportError(
                    "pandas required for trained models. Install training dependencies."
                )
            # Create DataFrame with all required features
            # This should match the feature engineering used during training
            feature_df = pd.DataFrame([features])
            return float(self.model.predict(feature_df)[0])


def load_production_model(model_id: Optional[str] = None) -> ModelLoader:
    """
    Load the production model.

    Args:
        model_id: Optional model ID from registry. If None, uses MODEL_ID env var or baseline.

    Returns:
        ModelLoader instance with loaded model
    """
    model_id = model_id or os.environ.get("MODEL_ID")

    if model_id and model_id != "baseline-logit-v0":
        # Try to load from registry first
        loader = ModelLoader(model_id=model_id)
        try:
            loader.load()
            return loader
        except (FileNotFoundError, ImportError) as e:
            # Fallback to baseline if model not found or dependencies missing
            print(f"[model_loader] Could not load trained model {model_id}: {e}")
            print("[model_loader] Falling back to baseline model")
            pass

    # Fallback to baseline
    return ModelLoader()
