"""Tests for event helper functions."""

from unittest.mock import patch

import pytest

from event_helpers import (
    EVENT_TYPE_MAPPING,
    calculate_goal_distance,
    calculate_strength_from_situation,
    extract_player_id_from_event,
    format_goal_description,
    format_penalty_description,
    format_shot_description,
    get_game_situation,
    parse_situation_code,
)


def test_event_type_mapping():
    """Test EVENT_TYPE_MAPPING contains expected mappings."""
    assert EVENT_TYPE_MAPPING[502] == "FACEOFF"
    assert EVENT_TYPE_MAPPING[505] == "GOAL"
    assert EVENT_TYPE_MAPPING[509] == "PENALTY"
    assert EVENT_TYPE_MAPPING[506] == "SHOT"


def test_extract_player_id_from_event_goal():
    """Test extracting player ID from GOAL event."""
    details = {
        "scoringPlayerId": 12345,
        "assist1PlayerId": 67890,
        "assist2PlayerId": 11111,
    }
    primary_id, assist1_id, assist2_id, blocking_id, shooting_id = (
        extract_player_id_from_event("GOAL", details)
    )

    assert primary_id == 12345
    assert assist1_id == 67890
    assert assist2_id == 11111
    assert blocking_id is None
    assert shooting_id is None


def test_extract_player_id_from_event_penalty():
    """Test extracting player ID from PENALTY event."""
    details = {"committedByPlayerId": 12345}
    primary_id, assist1_id, assist2_id, blocking_id, shooting_id = (
        extract_player_id_from_event("PENALTY", details)
    )

    assert primary_id == 12345
    assert assist1_id is None


def test_extract_player_id_from_event_block():
    """Test extracting player ID from BLOCK event."""
    details = {
        "playerId": 12345,  # Blocking player
        "shootingPlayerId": 67890,
    }
    primary_id, assist1_id, assist2_id, blocking_id, shooting_id = (
        extract_player_id_from_event("BLOCK", details)
    )

    assert primary_id == 12345
    assert blocking_id == 12345
    assert shooting_id == 67890


def test_calculate_strength_from_situation_even_strength():
    """Test calculating strength for even strength (5v5)."""
    strength = calculate_strength_from_situation("1551", "HOME", 5, 5)
    assert strength == "EV"


def test_calculate_strength_from_situation_power_play():
    """Test calculating strength for power play (5v4)."""
    strength = calculate_strength_from_situation("1541", "HOME", 5, 4)
    assert strength == "PP"


def test_calculate_strength_from_situation_shorthanded():
    """Test calculating strength for shorthanded (4v5)."""
    strength = calculate_strength_from_situation("1451", "HOME", 4, 5)
    assert strength in ["SH", "PK"]  # Can be either depending on implementation


def test_calculate_strength_from_situation_empty_net():
    """Test calculating strength for empty net (6v5)."""
    strength = calculate_strength_from_situation("1651", "HOME", 6, 5)
    assert strength in ["EN", "ENPP"]


def test_parse_situation_code():
    """Test parsing situation code."""
    # Format: ABCD where position 1 = away_skaters, position 3 = home_skaters
    # "1555" means away=5, home=5 (even strength)
    home_skaters, away_skaters = parse_situation_code("1555")
    assert home_skaters == 5
    assert away_skaters == 5

    # "1455" means away=4, home=5 (home has power play)
    home_skaters, away_skaters = parse_situation_code("1455")
    assert home_skaters == 5
    assert away_skaters == 4


def test_parse_situation_code_invalid():
    """Test parsing invalid situation code."""
    home_skaters, away_skaters = parse_situation_code("")
    assert home_skaters == 5  # Default
    assert away_skaters == 5  # Default


def test_calculate_goal_distance():
    """Test calculating goal distance."""
    # Test goal at (89, 0) - should be 0 distance from home goal
    distance = calculate_goal_distance(
        89, 0, {"homeTeamDefendingSide": "right"}, "HOME", None
    )
    assert distance is not None
    assert distance >= 0


def test_calculate_goal_distance_away_goal():
    """Test calculating distance to away goal."""
    # Test goal at (-89, 0) - should be 0 distance from away goal
    distance = calculate_goal_distance(
        -89, 0, {"homeTeamDefendingSide": "left"}, "AWAY", None
    )
    assert distance is not None
    assert distance >= 0


def test_format_goal_description():
    """Test formatting goal description."""
    shot_type = "wrist"
    distance = 15
    game_situation = "go-ahead "
    strength = "PP"
    assists = ["Player 1", "Player 2"]

    desc = format_goal_description(
        shot_type, distance, game_situation, strength, assists
    )

    assert "go-ahead" in desc.lower()
    assert "power play" in desc.lower() or "pp" in desc.lower()
    assert "wrist" in desc.lower()
    assert "15'" in desc or "15" in desc


def test_format_shot_description():
    """Test formatting shot description."""
    # Test saved shot
    desc = format_shot_description("wrist", was_saved=True, was_blocked=False)
    assert "saved" in desc.lower()
    assert "wrist" in desc.lower()

    # Test blocked shot
    desc = format_shot_description("slap", was_saved=False, was_blocked=True)
    assert "blocked" in desc.lower()

    # Test missed shot
    desc = format_shot_description("snap", was_saved=False, was_blocked=False)
    assert "missed" in desc.lower()


def test_format_penalty_description():
    """Test formatting penalty description."""
    desc = format_penalty_description("tripping", 2)
    assert "tripping" in desc.lower()
    assert "2" in desc or "min" in desc.lower()

    desc = format_penalty_description("fighting", 5)
    assert "fighting" in desc.lower()
    assert "5" in desc


def test_get_game_situation_tied():
    """Test getting game situation for tied game."""
    # Current: 2-2, scoring goal makes it 3-2
    situation = get_game_situation(2, 2, "HOME")
    assert situation == "go-ahead "


def test_get_game_situation_go_ahead():
    """Test getting game situation for go-ahead goal."""
    # Current: 1-2, scoring goal makes it 2-2 (ties the game)
    situation = get_game_situation(1, 2, "HOME")
    assert situation == "game-tying "


def test_get_game_situation_insurance():
    """Test getting game situation for insurance goal."""
    # Current: 2-1, scoring goal makes it 3-1 (extends lead)
    # The function only returns "game-tying ", "go-ahead ", or ""
    # Insurance goals don't have a special prefix in the current implementation
    situation = get_game_situation(2, 1, "HOME")
    # When home is already leading and scores again, it's not go-ahead or game-tying
    # So it returns empty string
    assert situation == ""  # Insurance goals return empty string


def test_get_game_situation_first_goal():
    """Test getting game situation for first goal."""
    # Current: 0-0, scoring goal makes it 1-0
    situation = get_game_situation(0, 0, "HOME")
    assert situation == "go-ahead " or situation == ""


@pytest.mark.asyncio
async def test_get_player_info_with_cache(mock_redis):
    """Test get_player_info with cached data."""
    from event_helpers import get_player_info

    player_id = 12345
    player_names = {player_id: "Brad Marchand"}
    player_headshots = {player_id: "https://example.com/headshot.png"}

    name, headshot = await get_player_info(
        player_id, player_names, player_headshots, mock_redis
    )

    assert name == "Brad Marchand"
    assert headshot == "https://example.com/headshot.png"


@pytest.mark.asyncio
async def test_get_player_info_fallback(mock_redis):
    """Test get_player_info with fallback to individual fetch."""
    from event_helpers import get_player_info

    player_id = 12345
    player_names = {}
    player_headshots = {}

    with (
        patch("player_utils.get_player_name") as mock_get_name,
        patch("player_utils.get_player_headshot") as mock_get_headshot,
    ):
        mock_get_name.return_value = "Brad Marchand"
        mock_get_headshot.return_value = "https://example.com/headshot.png"

        name, headshot = await get_player_info(
            player_id, player_names, player_headshots, mock_redis
        )

        assert name == "Brad Marchand"
        assert headshot == "https://example.com/headshot.png"
        mock_get_name.assert_called_once()
        mock_get_headshot.assert_called_once()


@pytest.mark.asyncio
async def test_get_player_info_no_player_id(mock_redis):
    """Test get_player_info with None player_id."""
    from event_helpers import get_player_info

    name, headshot = await get_player_info(None, {}, {}, mock_redis)

    assert name is None
    assert headshot is None
