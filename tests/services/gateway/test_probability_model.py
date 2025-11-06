"""Tests for the win probability calculation model."""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

try:
    from services.gateway.main import calculate_win_probability
except ImportError:
    calculate_win_probability = None


@pytest.mark.unit
@pytest.mark.skipif(calculate_win_probability is None, reason="calculate_win_probability not available")
class TestProbabilityModel:
    """Test the win probability calculation model."""
    
    def test_final_game_home_winner(self):
        """Test probability for final game where home team won."""
        prob = calculate_win_probability(
            home_score=3,
            away_score=1,
            game_state="FINAL"
        )
        assert prob == 1.0
    
    def test_final_game_away_winner(self):
        """Test probability for final game where away team won."""
        prob = calculate_win_probability(
            home_score=1,
            away_score=3,
            game_state="FINAL"
        )
        assert prob == 0.0
    
    def test_final_game_tie(self):
        """Test probability for final game that ended in tie."""
        prob = calculate_win_probability(
            home_score=2,
            away_score=2,
            game_state="FINAL"
        )
        assert prob == 0.5
    
    def test_tied_game_live(self):
        """Test probability for tied live game."""
        prob = calculate_win_probability(
            home_score=0,
            away_score=0,
            game_state="LIVE",
            period=1,
            time_in_period="10:00"
        )
        # Should be close to 50/50
        assert 0.45 <= prob <= 0.55
    
    def test_home_leading_early(self):
        """Test probability when home team is leading early in game."""
        prob = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=1,
            time_in_period="10:00"
        )
        assert prob > 0.5  # Home should have higher probability
        assert prob < 0.9  # But not too high early in game (model returns ~0.84 for 2-1 lead)
    
    def test_home_leading_late(self):
        """Test probability when home team is leading late in game."""
        prob = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=3,
            time_in_period="2:00"
        )
        assert prob > 0.5  # Home should have higher probability
        assert prob > 0.7  # Should be higher than early game
    
    def test_away_leading_early(self):
        """Test probability when away team is leading early."""
        prob = calculate_win_probability(
            home_score=1,
            away_score=2,
            game_state="LIVE",
            period=1,
            time_in_period="10:00"
        )
        assert prob < 0.5  # Home should have lower probability
    
    def test_away_leading_late(self):
        """Test probability when away team is leading late."""
        prob = calculate_win_probability(
            home_score=1,
            away_score=2,
            game_state="LIVE",
            period=3,
            time_in_period="2:00"
        )
        assert prob < 0.5  # Home should have lower probability
        assert prob < 0.3  # Should be lower than early game
    
    def test_large_lead_early(self):
        """Test probability with large lead early in game."""
        prob = calculate_win_probability(
            home_score=5,
            away_score=0,
            game_state="LIVE",
            period=1,
            time_in_period="10:00"
        )
        assert prob > 0.5  # Home should lead
        # Large lead (5-0) early in game gives high probability (~0.95, which is clamped max)
        assert prob >= 0.9  # Should be very high for such a large lead
    
    def test_large_lead_late(self):
        """Test probability with large lead late in game."""
        prob = calculate_win_probability(
            home_score=5,
            away_score=0,
            game_state="LIVE",
            period=3,
            time_in_period="2:00"
        )
        assert prob > 0.9  # Should be very high late in game
    
    def test_overtime_tied(self):
        """Test probability for tied game in overtime."""
        prob = calculate_win_probability(
            home_score=3,
            away_score=3,
            game_state="LIVE",
            period=4,
            time_in_period="2:00"
        )
        # Should be close to 50/50 in OT
        assert 0.4 <= prob <= 0.6
    
    def test_overtime_home_leading(self):
        """Test probability when home team leads in overtime."""
        prob = calculate_win_probability(
            home_score=4,
            away_score=3,
            game_state="LIVE",
            period=4,
            time_in_period="2:00"
        )
        assert prob > 0.7  # Should be high in OT
    
    def test_no_period_info(self):
        """Test probability calculation without period info."""
        prob = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE"
        )
        # Should use simple model based on score differential
        assert prob > 0.5
    
    def test_time_remaining_calculation(self):
        """Test that time remaining affects probability correctly."""
        prob_early = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=1,
            time_in_period="1:00"
        )
        prob_late = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=3,
            time_in_period="1:00"
        )
        # Same score differential, but later in game should have higher probability
        assert prob_late > prob_early
    
    def test_shootout_home_leading(self):
        """Test probability in shootout when home leads."""
        prob = calculate_win_probability(
            home_score=1,
            away_score=0,
            game_state="LIVE",
            period=5  # Shootout
        )
        assert prob == 0.95  # Very high probability
    
    def test_shootout_away_leading(self):
        """Test probability in shootout when away leads."""
        prob = calculate_win_probability(
            home_score=0,
            away_score=1,
            game_state="LIVE",
            period=5  # Shootout
        )
        assert prob == 0.05  # Very low probability
    
    def test_time_parsing(self):
        """Test that time parsing works correctly."""
        prob1 = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=2,
            time_in_period="10:00"
        )
        prob2 = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=2,
            time_in_period="5:00"
        )
        # Less time remaining should give higher probability to leader
        assert prob2 > prob1
    
    def test_probability_bounds(self):
        """Test that probabilities stay within reasonable bounds."""
        # Test various scenarios
        scenarios = [
            (0, 0, "LIVE", 1, "10:00"),
            (5, 0, "LIVE", 1, "10:00"),
            (0, 5, "LIVE", 1, "10:00"),
            (2, 1, "LIVE", 3, "1:00"),
            (1, 2, "LIVE", 3, "1:00"),
        ]
        
        for home, away, state, period, time_str in scenarios:
            prob = calculate_win_probability(
                home_score=home,
                away_score=away,
                game_state=state,
                period=period,
                time_in_period=time_str
            )
            # Probabilities should be between 5% and 95% (clamped)
            assert 0.05 <= prob <= 0.95, f"Probability {prob} out of bounds for scenario {scenarios}"


@pytest.mark.unit
class TestProbabilityModelEdgeCases:
    """Test edge cases for probability model."""
    
    @pytest.mark.skipif(calculate_win_probability is None, reason="calculate_win_probability not available")
    def test_invalid_time_format(self):
        """Test handling of invalid time format."""
        prob = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=2,
            time_in_period="invalid"
        )
        # Should still calculate based on score differential
        assert prob > 0.5
    
    @pytest.mark.skipif(calculate_win_probability is None, reason="calculate_win_probability not available")
    def test_empty_time_string(self):
        """Test handling of empty time string."""
        prob = calculate_win_probability(
            home_score=2,
            away_score=1,
            game_state="LIVE",
            period=2,
            time_in_period=""
        )
        assert prob > 0.5
    
    @pytest.mark.skipif(calculate_win_probability is None, reason="calculate_win_probability not available")
    def test_negative_scores(self):
        """Test handling of negative scores (shouldn't happen but test robustness)."""
        prob = calculate_win_probability(
            home_score=-1,
            away_score=0,
            game_state="LIVE",
            period=1,
            time_in_period="10:00"
        )
        # Should still calculate something reasonable
        assert isinstance(prob, float)
        assert 0.0 <= prob <= 1.0

