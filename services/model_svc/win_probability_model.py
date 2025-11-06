"""
WinProbabilityModel class for production inference.
This is a simplified version that loads trained models.
"""
import pickle
import pandas as pd

# Try to import ML libraries (lazy import to avoid errors if not available)
LIGHTGBM_AVAILABLE = False
XGBOOST_AVAILABLE = False
CATBOOST_AVAILABLE = False

# These will be imported when needed


class WinProbabilityModel:
    """Production model class for win probability prediction."""
    
    def __init__(self, model_type: str = "lightgbm", **kwargs):
        self.model_type = model_type
        self.model = None
        self.feature_columns = None
        self.config = kwargs
    
    def predict(self, X: pd.DataFrame, clip_probabilities: bool = True) -> pd.Series:
        """Predict win probability with optional calibration and clipping."""
        if self.model is None:
            raise ValueError("Model not loaded. Call load() first.")
        
        # Ensure same feature order
        X = X[self.feature_columns]
        
        # Get raw predictions
        if self.model_type == "xgboost":
            raw_probs = self.model.predict_proba(X)[:, 1]
        elif self.model_type == "lightgbm":
            raw_probs = self.model.predict(X)
        elif self.model_type == "catboost":
            raw_probs = self.model.predict_proba(X)[:, 1]
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
        
        # Apply calibration if available
        if hasattr(self, 'calibrator') and self.calibrator is not None:
            import numpy as np
            raw_probs_2d = raw_probs.reshape(-1, 1)
            calibrated_probs = self.calibrator.predict_proba(raw_probs_2d)[:, 1]
            probs = calibrated_probs
        else:
            probs = raw_probs
        
        # Clip probabilities to prevent extreme confidence (0.05 to 0.95)
        if clip_probabilities:
            import numpy as np
            probs = np.clip(probs, 0.05, 0.95)
        
        return pd.Series(probs)
    
    @classmethod
    def load(cls, filepath: str) -> 'WinProbabilityModel':
        """Load model from file."""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)
        
        instance = cls(
            model_type=model_data['model_type'],
            **model_data.get('config', {})
        )
        instance.model = model_data['model']
        instance.feature_columns = model_data['feature_columns']
        instance.calibrator = model_data.get('calibrator', None)
        
        return instance

