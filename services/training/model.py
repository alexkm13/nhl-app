"""
Model definitions and training for win probability prediction.
"""
import pickle
from typing import Dict, Optional
import numpy as np
import pandas as pd
import xgboost as xgb
import lightgbm as lgb
import catboost as cb


class WinProbabilityModel:
    """Base class for win probability models."""
    
    def __init__(self, model_type: str = "xgboost", **kwargs):
        self.model_type = model_type
        self.model = None
        self.feature_columns = None
        self.config = kwargs
    
    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None
    ):
        """Train the model."""
        self.feature_columns = X_train.columns.tolist()
        
        if self.model_type == "xgboost":
            self._train_xgboost(X_train, y_train, X_val, y_val)
        elif self.model_type == "lightgbm":
            self._train_lightgbm(X_train, y_train, X_val, y_val)
        elif self.model_type == "catboost":
            self._train_catboost(X_train, y_train, X_val, y_val)
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
    
    def _train_xgboost(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None
    ):
        """Train XGBoost model."""
        params = {
            'objective': 'binary:logistic',
            'eval_metric': 'logloss',
            'random_state': self.config.get('random_seed', 42),
            'n_estimators': self.config.get('n_estimators', 200),
            'max_depth': self.config.get('max_depth', 6),
            'learning_rate': self.config.get('learning_rate', 0.05),
            'subsample': self.config.get('subsample', 0.8),
            'colsample_bytree': self.config.get('colsample_bytree', 0.8),
            'min_child_weight': self.config.get('min_child_weight', 3),
            'reg_alpha': self.config.get('reg_alpha', 0.1),
            'reg_lambda': self.config.get('reg_lambda', 1.0),
        }
        
        self.model = xgb.XGBClassifier(**params)
        
        if X_val is not None and y_val is not None:
            self.model.fit(
                X_train,
                y_train,
                eval_set=[(X_val, y_val)],
                early_stopping_rounds=self.config.get('early_stopping_rounds', 20),
                verbose=False
            )
        else:
            self.model.fit(X_train, y_train)
    
    def _train_lightgbm(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None
    ):
        """Train LightGBM model."""
        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'random_state': self.config.get('random_seed', 42),
            'num_leaves': 31,
            'learning_rate': self.config.get('learning_rate', 0.05),
            'feature_fraction': self.config.get('colsample_bytree', 0.8),
            'bagging_fraction': self.config.get('subsample', 0.8),
            'bagging_freq': 5,
            'min_child_samples': self.config.get('min_child_weight', 3),
            'reg_alpha': self.config.get('reg_alpha', 0.1),
            'reg_lambda': self.config.get('reg_lambda', 1.0),
        }
        
        train_data = lgb.Dataset(X_train, label=y_train)
        
        if X_val is not None and y_val is not None:
            val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=self.config.get('n_estimators', 200),
                valid_sets=[val_data],
                callbacks=[
                    lgb.early_stopping(
                        stopping_rounds=self.config.get('early_stopping_rounds', 20)
                    )
                ]
            )
        else:
            self.model = lgb.train(
                params,
                train_data,
                num_boost_round=self.config.get('n_estimators', 200)
            )
    
    def _train_catboost(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None
    ):
        """Train CatBoost model."""
        params = {
            'loss_function': 'Logloss',
            'random_seed': self.config.get('random_seed', 42),
            'iterations': self.config.get('n_estimators', 200),
            'depth': self.config.get('max_depth', 6),
            'learning_rate': self.config.get('learning_rate', 0.05),
            'subsample': self.config.get('subsample', 0.8),
            'colsample_bylevel': self.config.get('colsample_bytree', 0.8),
            'min_child_samples': self.config.get('min_child_weight', 3),
            'l2_leaf_reg': self.config.get('reg_lambda', 1.0),
            'verbose': False,
        }
        
        self.model = cb.CatBoostClassifier(**params)
        
        if X_val is not None and y_val is not None:
            self.model.fit(
                X_train,
                y_train,
                eval_set=(X_val, y_val),
                early_stopping_rounds=self.config.get('early_stopping_rounds', 20),
                verbose=False
            )
        else:
            self.model.fit(X_train, y_train, verbose=False)
    
    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict win probability."""
        if self.model is None:
            raise ValueError("Model not trained. Call train() first.")
        
        # Ensure same feature order
        X = X[self.feature_columns]
        
        if self.model_type == "xgboost":
            return self.model.predict_proba(X)[:, 1]
        elif self.model_type == "lightgbm":
            return self.model.predict(X)
        elif self.model_type == "catboost":
            return self.model.predict_proba(X)[:, 1]
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
    
    def get_feature_importance(self) -> pd.DataFrame:
        """Get feature importance."""
        if self.model is None:
            raise ValueError("Model not trained.")
        
        if self.model_type == "xgboost":
            importance = self.model.feature_importances_
        elif self.model_type == "lightgbm":
            importance = self.model.feature_importance()
        elif self.model_type == "catboost":
            importance = self.model.feature_importances_
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")
        
        return pd.DataFrame({
            'feature': self.feature_columns,
            'importance': importance
        }).sort_values('importance', ascending=False)
    
    def save(self, filepath: str):
        """Save model to file."""
        if self.model is None:
            raise ValueError("Model not trained.")
        
        model_data = {
            'model': self.model,
            'model_type': self.model_type,
            'feature_columns': self.feature_columns,
            'config': self.config
        }
        
        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)
    
    @classmethod
    def load(cls, filepath: str) -> 'WinProbabilityModel':
        """Load model from file."""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)
        
        instance = cls(
            model_type=model_data['model_type'],
            **model_data['config']
        )
        instance.model = model_data['model']
        instance.feature_columns = model_data['feature_columns']
        
        return instance


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: Optional[pd.DataFrame] = None,
    y_val: Optional[pd.Series] = None,
    config: Optional[Dict] = None
) -> WinProbabilityModel:
    """Train a win probability model."""
    if config is None:
        config = {}
    
    model_type = config.get('model_type', 'xgboost')
    model = WinProbabilityModel(model_type=model_type, **config.get('hyperparameters', {}))
    
    model.train(X_train, y_train, X_val, y_val)
    
    return model

