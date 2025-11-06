"""Tests for Pydantic models."""
import pytest

from models import WinProb


def test_winprob_model_valid():
    """Test WinProb model with valid data."""
    winprob = WinProb(
        game_id="2024020589",
        p_home_win=0.75,
        model_id="lightgbm_20251104_121934_d9b5b03f",
        ts=1705358400.0
    )
    assert winprob.game_id == "2024020589"
    assert winprob.p_home_win == 0.75
    assert winprob.model_id == "lightgbm_20251104_121934_d9b5b03f"
    assert winprob.ts == 1705358400.0


def test_winprob_model_invalid():
    """Test WinProb model with invalid data."""
    with pytest.raises(Exception):  # Pydantic validation error
        WinProb(
            game_id="2024020589",
            p_home_win="invalid",  # Should be float
            model_id="lightgbm_20251104_121934_d9b5b03f",
            ts=1705358400.0
        )


def test_winprob_model_missing_fields():
    """Test WinProb model with missing required fields."""
    with pytest.raises(Exception):  # Pydantic validation error
        WinProb(
            game_id="2024020589",
            p_home_win=0.75
            # Missing model_id and ts
        )


def test_winprob_model_p_home_win_range():
    """Test WinProb model with p_home_win outside 0-1 range."""
    # Pydantic doesn't enforce 0-1 range by default, but we can test it accepts any float
    winprob = WinProb(
        game_id="2024020589",
        p_home_win=1.5,  # Outside 0-1 range
        model_id="lightgbm_20251104_121934_d9b5b03f",
        ts=1705358400.0
    )
    assert winprob.p_home_win == 1.5


def test_winprob_model_negative_ts():
    """Test WinProb model with negative timestamp."""
    winprob = WinProb(
        game_id="2024020589",
        p_home_win=0.75,
        model_id="lightgbm_20251104_121934_d9b5b03f",
        ts=-1000.0
    )
    assert winprob.ts == -1000.0


def test_winprob_model_json_serialization():
    """Test WinProb model can be serialized to JSON."""
    winprob = WinProb(
        game_id="2024020589",
        p_home_win=0.75,
        model_id="lightgbm_20251104_121934_d9b5b03f",
        ts=1705358400.0
    )
    json_data = winprob.model_dump()
    assert json_data["game_id"] == "2024020589"
    assert json_data["p_home_win"] == 0.75
    assert json_data["model_id"] == "lightgbm_20251104_121934_d9b5b03f"
    assert json_data["ts"] == 1705358400.0

