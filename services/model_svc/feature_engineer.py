"""
Feature engineering for production inference - matches training pipeline.
"""


def engineer_features(features: dict) -> dict:
    """
    Engineer features from raw game state for model prediction.
    
    This matches the feature engineering used during training.
    
    Args:
        features: Dictionary with raw features (home_score, away_score, seconds_elapsed, etc.)
    
    Returns:
        Dictionary with engineered features
    """
    home_score = int(features.get('home_score', 0))
    away_score = int(features.get('away_score', 0))
    seconds_elapsed = float(features.get('seconds_elapsed', 0.0))
    strength = features.get('strength', 'EV')
    last_event = features.get('last_event', 'FACEOFF')
    
    # Score features
    score_diff = home_score - away_score
    score_diff_abs = abs(score_diff)
    total_goals = home_score + away_score
    
    # Score ratio (avoid division by zero)
    score_ratio = (home_score / (away_score + 1)) if away_score > 0 else (home_score + 1)
    
    # Leading indicators
    home_leading = 1 if score_diff > 0 else 0
    away_leading = 1 if score_diff < 0 else 0
    tied = 1 if score_diff == 0 else 0
    
    # Time features
    minutes_elapsed = seconds_elapsed / 60.0
    period = int(minutes_elapsed / 20.0) + 1
    period = min(period, 7)  # Max 7 periods
    
    time_remaining = max(0.0, 3600.0 - seconds_elapsed)
    time_normalized = min(1.0, seconds_elapsed / 3600.0)
    
    is_regulation = 1 if period <= 3 else 0
    is_overtime = 1 if period == 4 else 0
    is_shootout = 1 if period > 4 else 0
    
    # Strength features (matching training pipeline)
    strength_PK = 1 if strength == 'PK' else 0
    
    home_pp = 1 if strength in ['PP', 'ENPP'] else 0
    away_pp = 1 if strength == 'PK' else 0
    home_pk = 1 if strength == 'PK' else 0
    away_pk = 1 if strength in ['PP', 'ENPP'] else 0
    
    # Recent event features
    last_event_GOAL = 1 if last_event == 'GOAL' else 0
    last_event_PENALTY = 1 if last_event == 'PENALTY' else 0
    last_event_SHOT = 1 if last_event == 'SHOT' else 0
    last_event_FACEOFF = 1 if last_event == 'FACEOFF' else 0
    
    recent_goal = last_event_GOAL
    recent_penalty = last_event_PENALTY
    recent_shot = last_event_SHOT
    
    # Momentum features (simplified - would need rolling window in production)
    # For now, use score change from initial state (assume 0-0 start)
    score_change_5min = score_diff  # Simplified - should be rolling window
    recent_goals = total_goals  # Simplified - should be rolling window
    
    # Build feature dict matching training pipeline column order
    # Only include features that the model was trained with
    feature_dict = {
        'seconds_elapsed': seconds_elapsed,
        'score_diff': score_diff,
        'score_diff_abs': score_diff_abs,
        'total_goals': total_goals,
        'score_ratio': score_ratio,
        'home_leading': home_leading,
        'away_leading': away_leading,
        'tied': tied,
        'minutes_elapsed': minutes_elapsed,
        'period': period,
        'time_remaining': time_remaining,
        'time_normalized': time_normalized,
        'is_regulation': is_regulation,
        'is_overtime': is_overtime,
        'is_shootout': is_shootout,
        'strength_PK': strength_PK,
        'home_pp': home_pp,
        'away_pp': away_pp,
        'home_pk': home_pk,
        'away_pk': away_pk,
        'score_change_5min': score_change_5min,
        'recent_goals': recent_goals,
        'last_event_FACEOFF': last_event_FACEOFF,
        'last_event_GOAL': last_event_GOAL,
        'last_event_PENALTY': last_event_PENALTY,
        'last_event_SHOT': last_event_SHOT,
        'recent_goal': recent_goal,
        'recent_penalty': recent_penalty,
        'recent_shot': recent_shot,
    }
    
    return feature_dict

