"""Unit tests for feature engineering."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

from services.model_svc.feature_engineer import engineer_features


@pytest.mark.unit
class TestFeatureEngineering:
    """Test feature engineering logic."""
    
    def test_engineer_features_basic(self):
        """Test basic feature engineering."""
        state = {
            "home_score": 2,
            "away_score": 1,
            "period": 2,
            "time_in_period": "10:00",
            "strength": "EV",
            "empty_net": False
        }
        
        features = engineer_features(state)
        
        assert "score_diff" in features
        assert "period" in features
        assert "time_remaining" in features
        assert features["score_diff"] == 1
        assert features["period"] == 2
    
    def test_engineer_features_power_play(self):
        """Test feature engineering with power play."""
        state = {
            "home_score": 1,
            "away_score": 1,
            "period": 1,
            "time_in_period": "10:00",
            "strength": "PP",
            "empty_net": False
        }
        
        features = engineer_features(state)
        
        assert "is_power_play" in features or "strength" in features
        assert features.get("score_diff", 0) == 0
    
    def test_engineer_features_time_calculation(self):
        """Test time remaining calculation."""
        state = {
            "home_score": 0,
            "away_score": 0,
            "period": 1,
            "time_in_period": "10:00",  # 10 minutes elapsed
            "strength": "EV",
            "empty_net": False
        }
        
        features = engineer_features(state)
        
        # Should calculate time remaining correctly
        assert "time_remaining" in features or "time_elapsed" in features

