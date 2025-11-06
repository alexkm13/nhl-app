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
    
    # CRITICAL: Score-time interaction features
    # These help the model understand that score matters more at different times
    # A 1-goal lead with 10 min left is different than 1-goal lead with 1 min left
    score_diff_time_interaction = score_diff * (time_remaining / 3600.0)  # Score diff weighted by time remaining
    # Urgency: score_diff per minute remaining (higher when time is low)
    # When time is low, urgency is high - score changes matter more
    score_diff_urgency = score_diff / max(1.0, time_remaining / 60.0)  # Score diff per minute remaining
    # Late game impact: amplifies score_diff when time_normalized is high (late in game)
    # time_normalized = 0.9 means late in game, so we multiply by time_normalized
    # This makes score_diff matter MORE as the game progresses
    late_game_score_impact = score_diff * time_normalized  # Amplifies score_diff late in game
    # Early game dampening: reduces score_diff impact early in game
    # This prevents 1-goal leads from being over-weighted early
    # Use negative value to reduce early game impact
    early_game_dampening = -score_diff * (1.0 - time_normalized)  # Negative early (reduces impact), near zero late
    # Early game penalty: explicitly penalizes early game leads
    early_game_score_penalty = -score_diff * (1.0 - time_normalized) * 0.3  # Reduces early game score impact
    
    # Strength features (matching training pipeline)
    strength_EV = 1 if strength == 'EV' else 0
    strength_PK = 1 if strength == 'PK' else 0
    
    home_pp = 1 if strength in ['PP', 'ENPP'] else 0
    away_pp = 1 if strength == 'PK' else 0
    home_pk = 1 if strength == 'PK' else 0
    away_pk = 1 if strength in ['PP', 'ENPP'] else 0
    
    # CRITICAL: Power play interaction features (moderate impact)
    # Power plays are advantages, but not overwhelming
    # Home team on PP: increases win probability moderately
    # Away team on PP: decreases win probability moderately
    home_pp_advantage = home_pp  # Home has man advantage
    away_pp_advantage = away_pp  # Away has man advantage
    
    # Power play + score lead = moderate advantage boost
    home_pp_with_lead = home_pp * home_leading * 0.5  # Home PP + leading (reduced impact)
    away_pp_with_lead = away_pp * away_leading * 0.5  # Away PP + leading (reduced impact)
    
    # Power play + late game = moderate advantage (scaled down)
    home_pp_late_game = home_pp * time_normalized * 0.5  # Home PP late in game (reduced)
    away_pp_late_game = away_pp * time_normalized * 0.5  # Away PP late in game (reduced)
    
    # Power play + score diff interaction (normalized to prevent excessive impact)
    # When on PP, score_diff matters slightly more
    home_pp_score_boost = home_pp * score_diff * 0.3  # Home PP + score diff (reduced)
    away_pp_score_boost = away_pp * score_diff * 0.3  # Away PP + score diff (reduced)
    
    # Power play urgency (normalized to prevent extreme values)
    # PP late in game matters more, but not excessively
    home_pp_urgency = home_pp * (1.0 / max(1.0, time_remaining / 60.0)) * 0.5  # Home PP urgency (reduced)
    away_pp_urgency = away_pp * (1.0 / max(1.0, time_remaining / 60.0)) * 0.5  # Away PP urgency (reduced)
    
    # Recent event features
    last_event_GOAL = 1 if last_event == 'GOAL' else 0
    last_event_PENALTY = 1 if last_event == 'PENALTY' else 0
    last_event_SHOT = 1 if last_event == 'SHOT' else 0
    last_event_FACEOFF = 1 if last_event == 'FACEOFF' else 0
    last_event_GAME_END = 1 if last_event == 'GAME_END' else 0
    
    recent_goal = last_event_GOAL
    recent_penalty = last_event_PENALTY
    recent_shot = last_event_SHOT
    
    # Goal impact feature - amplify score_diff when a goal just happened
    # This makes the model react more strongly to goals
    goal_just_scored = 1 if last_event == 'GOAL' else 0
    score_diff_after_goal = score_diff * goal_just_scored  # Amplify score_diff when goal happens
    # Magnitude of score change impact (higher when goal just happened)
    goal_impact = abs(score_diff) * goal_just_scored  # Amplify impact when goal happens
    
    # Momentum features (simplified - would need rolling window in production)
    # For now, use score change from initial state (assume 0-0 start)
    score_change_5min = score_diff  # Simplified - should be rolling window
    recent_goals = total_goals  # Simplified - should be rolling window
    
    # Score momentum - how much the score changed recently
    score_momentum = score_diff  # Will be enhanced by goal impact features
    
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
        'strength_EV': strength_EV,
        'strength_PK': strength_PK,
        'home_pp': home_pp,
        'away_pp': away_pp,
        'home_pk': home_pk,
        'away_pk': away_pk,
        'home_pp_advantage': home_pp_advantage,
        'away_pp_advantage': away_pp_advantage,
        'home_pp_with_lead': home_pp_with_lead,
        'away_pp_with_lead': away_pp_with_lead,
        'home_pp_late_game': home_pp_late_game,
        'away_pp_late_game': away_pp_late_game,
        'home_pp_score_boost': home_pp_score_boost,
        'away_pp_score_boost': away_pp_score_boost,
        'home_pp_urgency': home_pp_urgency,
        'away_pp_urgency': away_pp_urgency,
        'score_change_5min': score_change_5min,
        'recent_goals': recent_goals,
        'last_event_FACEOFF': last_event_FACEOFF,
        'last_event_GAME_END': last_event_GAME_END,
        'last_event_GOAL': last_event_GOAL,
        'last_event_PENALTY': last_event_PENALTY,
        'last_event_SHOT': last_event_SHOT,
        'recent_goal': recent_goal,
        'recent_penalty': recent_penalty,
        'recent_shot': recent_shot,
        'goal_just_scored': goal_just_scored,
        'score_diff_after_goal': score_diff_after_goal,
        'goal_impact': goal_impact,
        'score_momentum': score_momentum,
        'score_diff_time_interaction': score_diff_time_interaction,
        'score_diff_urgency': score_diff_urgency,
        'late_game_score_impact': late_game_score_impact,
        'early_game_dampening': early_game_dampening,
        'early_game_score_penalty': early_game_score_penalty,
    }
    
    return feature_dict

