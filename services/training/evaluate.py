"""
Model evaluation metrics and utilities.
"""
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from sklearn.metrics import (
    log_loss,
    roc_auc_score,
    brier_score_loss,
    accuracy_score
)


def calculate_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    metrics: Optional[List[str]] = None
) -> Dict[str, float]:
    """
    Calculate evaluation metrics.
    
    Args:
        y_true: True binary labels
        y_pred: Predicted probabilities
        metrics: List of metric names to calculate
    
    Returns:
        Dictionary of metric names and values
    """
    if metrics is None:
        metrics = [
            'log_loss', 'brier_score', 'roc_auc', 'accuracy', 'calibration_error'
        ]
    
    results = {}
    
    if 'log_loss' in metrics:
        try:
            results['log_loss'] = log_loss(y_true, y_pred, labels=[0, 1])
        except ValueError:
            # If only one class present, return NaN
            results['log_loss'] = float('nan')
    
    if 'brier_score' in metrics:
        results['brier_score'] = brier_score_loss(y_true, y_pred)
    
    if 'roc_auc' in metrics:
        try:
            results['roc_auc'] = roc_auc_score(y_true, y_pred)
        except ValueError:
            results['roc_auc'] = np.nan
    
    if 'accuracy' in metrics:
        y_pred_binary = (y_pred >= 0.5).astype(int)
        results['accuracy'] = accuracy_score(y_true, y_pred_binary)
    
    if 'calibration_error' in metrics:
        results['calibration_error'] = calculate_calibration_error(y_true, y_pred)
    
    return results


def calculate_calibration_error(
    y_true: np.ndarray, y_pred: np.ndarray, n_bins: int = 10
) -> float:
    """
    Calculate expected calibration error (ECE).
    
    Args:
        y_true: True binary labels
        y_pred: Predicted probabilities
        n_bins: Number of bins for calibration
    
    Returns:
        Expected calibration error
    """
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    bin_lowers = bin_boundaries[:-1]
    bin_uppers = bin_boundaries[1:]
    
    ece = 0.0
    for bin_lower, bin_upper in zip(bin_lowers, bin_uppers):
        # Find predictions in this bin
        in_bin = (y_pred > bin_lower) & (y_pred <= bin_upper)
        prop_in_bin = in_bin.mean()
        
        if prop_in_bin > 0:
            # Calculate accuracy in this bin
            accuracy_in_bin = y_true[in_bin].mean()
            # Average predicted probability in this bin
            avg_confidence_in_bin = y_pred[in_bin].mean()
            # Add to ECE
            ece += np.abs(avg_confidence_in_bin - accuracy_in_bin) * prop_in_bin
    
    return ece


def evaluate_by_time_period(
    df: pd.DataFrame,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    time_col: str = 'seconds_elapsed'
) -> pd.DataFrame:
    """
    Evaluate model performance by time periods.
    
    Args:
        df: DataFrame with time information
        y_true: True labels
        y_pred: Predicted probabilities
        time_col: Column name for time elapsed
    
    Returns:
        DataFrame with metrics by time period
    """
    df_eval = df.copy()
    df_eval['y_true'] = y_true
    df_eval['y_pred'] = y_pred
    
    # Define time periods
    df_eval['period_label'] = pd.cut(
        df_eval[time_col],
        bins=[0, 600, 1200, 1800, 2400, 3000, np.inf],
        labels=['0-10min', '10-20min', '20-30min', '30-40min', '40-50min', '50min+']
    )
    
    results = []
    for period in df_eval['period_label'].cat.categories:
        period_data = df_eval[df_eval['period_label'] == period]
        if len(period_data) > 0:
            metrics = calculate_metrics(
                period_data['y_true'].values,
                period_data['y_pred'].values
            )
            metrics['period'] = period
            metrics['n_samples'] = len(period_data)
            results.append(metrics)
    
    return pd.DataFrame(results)


def evaluate_by_score_differential(
    df: pd.DataFrame,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    score_diff_col: str = 'score_diff'
) -> pd.DataFrame:
    """
    Evaluate model performance by score differential.
    
    Args:
        df: DataFrame with score differential
        y_true: True labels
        y_pred: Predicted probabilities
        score_diff_col: Column name for score differential
    
    Returns:
        DataFrame with metrics by score differential
    """
    df_eval = df.copy()
    df_eval['y_true'] = y_true
    df_eval['y_pred'] = y_pred
    
    # Define score differential bins
    df_eval['score_diff_label'] = pd.cut(
        df_eval[score_diff_col],
        bins=[-np.inf, -3, -2, -1, 0, 1, 2, 3, np.inf],
        labels=['-4+', '-3', '-2', '-1', '0', '+1', '+2', '+3+']
    )
    
    results = []
    for diff_label in df_eval['score_diff_label'].cat.categories:
        diff_data = df_eval[df_eval['score_diff_label'] == diff_label]
        if len(diff_data) > 0:
            metrics = calculate_metrics(
                diff_data['y_true'].values,
                diff_data['y_pred'].values
            )
            metrics['score_diff'] = diff_label
            metrics['n_samples'] = len(diff_data)
            results.append(metrics)
    
    return pd.DataFrame(results)


def evaluate_model(
    model,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    df_test: pd.DataFrame,
    metrics: Optional[List[str]] = None
) -> Dict:
    """
    Comprehensive model evaluation.
    
    Args:
        model: Trained model
        X_test: Test features
        y_test: Test labels
        df_test: Test DataFrame with metadata
        metrics: List of metrics to calculate
    
    Returns:
        Dictionary with evaluation results
    """
    # Predictions
    y_pred = model.predict(X_test)
    
    # Overall metrics
    overall_metrics = calculate_metrics(y_test.values, y_pred, metrics)
    
    # Evaluation by time period
    time_period_metrics = evaluate_by_time_period(df_test, y_test.values, y_pred)
    
    # Evaluation by score differential
    score_diff_metrics = evaluate_by_score_differential(df_test, y_test.values, y_pred)
    
    # Feature importance
    feature_importance = model.get_feature_importance()
    
    return {
        'overall_metrics': overall_metrics,
        'time_period_metrics': time_period_metrics,
        'score_diff_metrics': score_diff_metrics,
        'feature_importance': feature_importance,
        'predictions': y_pred,
        'n_samples': len(y_test)
    }

