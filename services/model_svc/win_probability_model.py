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
    
    def predict(self, X: pd.DataFrame) -> pd.Series:
        """Predict win probability."""
        if self.model is None:
            raise ValueError("Model not loaded. Call load() first.")
        
        # Ensure same feature order
        X = X[self.feature_columns]
        
        if self.model_type == "xgboost":
            import xgboost as xgb  # noqa: F401
            return pd.Series(self.model.predict_proba(X)[:, 1])
        elif self.model_type == "lightgbm":
            import lightgbm as lgb  # noqa: F401
            return pd.Series(self.model.predict(X))
        elif self.model_type == "catboost":
            import catboost as cb  # noqa: F401
            return pd.Series(self.model.predict_proba(X)[:, 1])
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
    
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
        
        return instance

