"""Tests for utility functions."""

from unittest.mock import patch

import pytest

from utils import calculate_win_probability, check_overtime_type, run_ingestion


def test_calculate_win_probability_final_home_win():
    """Test win probability for final game with home win."""
    prob = calculate_win_probability(home_score=3, away_score=1, game_state="FINAL")
    assert prob == 1.0


def test_calculate_win_probability_final_away_win():
    """Test win probability for final game with away win."""
    prob = calculate_win_probability(home_score=1, away_score=3, game_state="FINAL")
    assert prob == 0.0


def test_calculate_win_probability_final_tie():
    """Test win probability for final tie game."""
    prob = calculate_win_probability(home_score=2, away_score=2, game_state="FINAL")
    assert prob == 0.5


def test_calculate_win_probability_tied_score():
    """Test win probability with tied score."""
    prob = calculate_win_probability(
        home_score=2, away_score=2, game_state="LIVE", period=2, time_in_period="10:00"
    )
    assert 0.45 <= prob <= 0.55  # Should be close to 50%


def test_calculate_win_probability_home_lead():
    """Test win probability with home team leading."""
    prob = calculate_win_probability(
        home_score=3,
        away_score=1,
        game_state="LIVE",
        period=3,
        time_in_period="05:00",  # Late in game
    )
    assert prob > 0.5  # Home should have higher probability


def test_calculate_win_probability_away_lead():
    """Test win probability with away team leading."""
    prob = calculate_win_probability(
        home_score=1,
        away_score=3,
        game_state="LIVE",
        period=3,
        time_in_period="05:00",  # Late in game
    )
    assert prob < 0.5  # Home should have lower probability


def test_calculate_win_probability_no_period():
    """Test win probability without period info."""
    prob = calculate_win_probability(
        home_score=2, away_score=1, game_state="LIVE", period=None
    )
    assert prob > 0.5  # Home should have higher probability


def test_calculate_win_probability_overtime():
    """Test win probability in overtime."""
    prob = calculate_win_probability(
        home_score=2,
        away_score=2,
        game_state="LIVE",
        period=4,  # Overtime
        time_in_period="02:00",
    )
    assert 0.4 <= prob <= 0.6  # Should be close to 50% in tied OT


def test_calculate_win_probability_overtime_lead():
    """Test win probability in overtime with lead."""
    prob = calculate_win_probability(
        home_score=3,
        away_score=2,
        game_state="LIVE",
        period=4,  # Overtime
        time_in_period="02:00",
    )
    assert prob > 0.7  # Lead in OT should be significant


def test_calculate_win_probability_with_plays():
    """Test win probability calculation with plays data."""
    plays = [
        {
            "typeCode": 505,  # GOAL
            "timeInPeriod": "15:00",
            "periodDescriptor": {"number": 1},
            "details": {"eventOwnerTeamId": 1},
        }
    ]

    prob = calculate_win_probability(
        home_score=3,
        away_score=1,
        game_state="LIVE",
        period=3,
        time_in_period="10:00",
        plays=plays,
    )
    assert prob > 0.5  # Home should have higher probability


@pytest.mark.asyncio
async def test_check_overtime_type_regulation():
    """Test check_overtime_type for regulation game."""
    game_id = "2024020589"

    game_data = {
        "plays": [
            {"periodDescriptor": {"number": 1}, "typeCode": 505},
            {"periodDescriptor": {"number": 2}, "typeCode": 505},
            {"periodDescriptor": {"number": 3}, "typeCode": 505},
        ]
    }

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.return_value = game_data

        result = await check_overtime_type(game_id)

        assert result is None  # No overtime


@pytest.mark.asyncio
async def test_check_overtime_type_overtime():
    """Test check_overtime_type for overtime game."""
    game_id = "2024020589"

    game_data = {
        "plays": [
            {
                "periodDescriptor": {"number": 4},  # Overtime
                "typeCode": 505,
            }
        ]
    }

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.return_value = game_data

        result = await check_overtime_type(game_id)

        assert result == "OT"


@pytest.mark.asyncio
async def test_check_overtime_type_shootout():
    """Test check_overtime_type for shootout game."""
    game_id = "2024020589"

    game_data = {
        "plays": [
            {
                "periodDescriptor": {"number": 5},  # Shootout
                "typeCode": 505,  # GOAL
            }
        ]
    }

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.return_value = game_data

        result = await check_overtime_type(game_id)

        assert result == "SO"


@pytest.mark.asyncio
async def test_check_overtime_type_no_game_data():
    """Test check_overtime_type with no game data."""
    game_id = "2024020589"

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.return_value = None

        result = await check_overtime_type(game_id)

        assert result is None


@pytest.mark.asyncio
async def test_run_ingestion_success(mock_redis):
    """Test successful game ingestion."""
    game_id = "2024020589"

    game_data = {
        "startTimeUTC": "2024-01-15T19:00:00Z",
        "homeTeam": {"id": 1, "commonName": {"default": "Bruins"}},
        "awayTeam": {"id": 2, "commonName": {"default": "Leafs"}},
        "plays": [
            {
                "typeCode": 505,  # GOAL
                "timeInPeriod": "15:00",
                "periodDescriptor": {"number": 1},
                "details": {"eventOwnerTeamId": 1, "scoringPlayerId": 12345},
            }
        ],
    }

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.return_value = game_data

        await run_ingestion(game_id, mock_redis)

        # Verify Redis operations were called
        mock_redis.delete.assert_called()
        mock_redis.setex.assert_called()
        mock_redis.hset.assert_called()
        mock_redis.xadd.assert_called()  # Should publish events


@pytest.mark.asyncio
async def test_run_ingestion_no_game_data(mock_redis):
    """Test ingestion with no game data."""
    game_id = "2024020589"

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.return_value = None

        await run_ingestion(game_id, mock_redis)

        # Should mark as failed
        mock_redis.hset.assert_called()
        calls = [str(call) for call in mock_redis.hset.call_args_list]
        assert any("failed" in str(call) for call in calls)


@pytest.mark.asyncio
async def test_run_ingestion_no_plays(mock_redis):
    """Test ingestion with no plays."""
    game_id = "2024020589"

    game_data = {
        "homeTeam": {"id": 1, "commonName": {"default": "Bruins"}},
        "awayTeam": {"id": 2, "commonName": {"default": "Leafs"}},
        "plays": [],
    }

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.return_value = game_data

        await run_ingestion(game_id, mock_redis)

        # Should mark as failed
        mock_redis.hset.assert_called()
        calls = [str(call) for call in mock_redis.hset.call_args_list]
        assert any("failed" in str(call) for call in calls)


@pytest.mark.asyncio
async def test_run_ingestion_exception(mock_redis):
    """Test ingestion with exception."""
    game_id = "2024020589"

    with patch("utils.fetch_nhl_play_by_play") as mock_fetch:
        mock_fetch.side_effect = Exception("Network error")

        await run_ingestion(game_id, mock_redis)

        # Should mark as failed
        mock_redis.hset.assert_called()
        calls = [str(call) for call in mock_redis.hset.call_args_list]
        assert any("failed" in str(call) for call in calls)
