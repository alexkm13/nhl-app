"""Event processing helper functions."""

import math


EVENT_TYPE_MAPPING = {
    502: "FACEOFF",
    503: "HIT",
    504: "HIT",
    505: "GOAL",
    506: "SHOT",
    507: "SHOT",
    508: "BLOCK",
    509: "PENALTY",
    535: "GIVEAWAY",
    536: "TAKEAWAY",
    517: "PERIOD_END",  # Period end event
    520: "PERIOD_START",  # Period start event
}


def extract_player_id_from_event(mapped_type: str, details: dict) -> tuple:
    """Extract primary player ID and related IDs from event details.

    Returns:
        tuple: (primary_player_id, assist1_id, assist2_id, blocking_player_id, shooting_player_id)
    """
    primary_id = None
    assist1_id = None
    assist2_id = None
    blocking_id = None
    shooting_id = None

    if mapped_type == "GOAL":
        primary_id = details.get("scoringPlayerId")
        assist1_id = details.get("assist1PlayerId")
        assist2_id = details.get("assist2PlayerId")
    elif mapped_type == "PENALTY":
        primary_id = details.get("committedByPlayerId")
    elif mapped_type == "SHOT":
        primary_id = details.get("shootingPlayerId")
    elif mapped_type == "BLOCK":
        blocking_id = details.get("playerId") or details.get("blockingPlayerId")
        shooting_id = details.get("shootingPlayerId")
        primary_id = blocking_id
    elif mapped_type == "HIT":
        primary_id = details.get("hittingPlayerId")
    elif mapped_type == "FACEOFF":
        primary_id = details.get("winningPlayerId")
    elif mapped_type in ["GIVEAWAY", "TAKEAWAY"]:
        primary_id = details.get("playerId")

    return primary_id, assist1_id, assist2_id, blocking_id, shooting_id


async def get_player_info(
    player_id: int, player_names: dict, player_headshots: dict, redis=None
) -> tuple:
    """Get player name and headshot, with fallback to individual fetch if needed.

    Returns:
        tuple: (player_name, player_headshot)
    """
    from player_utils import get_player_name, get_player_headshot

    if not player_id:
        return None, None

    player_name = player_names.get(player_id)
    player_headshot = player_headshots.get(player_id)

    if not player_name:
        player_name = await get_player_name(player_id, redis)
    if not player_headshot:
        player_headshot = await get_player_headshot(player_id, redis)

    return player_name, player_headshot


def calculate_strength_from_situation(
    situation: str, team: str, home_skaters: int, away_skaters: int
) -> str:
    """Calculate strength situation from situationCode and team.

    Returns:
        str: Strength code (EV, PP, SH, EN, ENPP, PK)
    """
    empty_net = away_skaters == 6 or home_skaters == 6

    if team == "HOME":
        if empty_net:
            if home_skaters == 6:
                return "ENPP" if away_skaters < 5 else "EN"
            elif away_skaters == 6 or (home_skaters < 5 and away_skaters == 5):
                return "PK"
            else:
                return "EV"
        elif home_skaters == 5 and away_skaters == 5:
            return "EV"
        elif home_skaters > away_skaters:
            if home_skaters >= 3 and away_skaters >= 3:
                return "PP"
            else:
                return "EV"
        elif home_skaters < away_skaters:
            if home_skaters < 5 and away_skaters <= 5 and home_skaters >= 3:
                return "SH"
            else:
                return "EV"
        else:
            return "EV"
    else:  # AWAY team
        if empty_net:
            if away_skaters == 6:
                return "ENPP" if home_skaters < 5 else "EN"
            elif home_skaters == 6:
                return "PK"
            else:
                return "EV"
        elif away_skaters == 5 and home_skaters == 5:
            return "EV"
        elif away_skaters > home_skaters:
            if away_skaters >= 3 and home_skaters >= 3:
                return "PP"
            else:
                return "EV"
        elif away_skaters < home_skaters:
            if away_skaters < 5 and home_skaters <= 5 and away_skaters >= 3:
                return "SH"
            else:
                return "EV"
        else:
            return "EV"


def calculate_goal_distance(
    x_coord: float, y_coord: float, play: dict, team: str, period1_baseline: dict = None
) -> int:
    """Calculate distance from goal for a goal event.

    Returns:
        int: Distance in feet, or None if coordinates unavailable
    """
    if x_coord is None or y_coord is None:
        return None

    period = play.get("periodDescriptor", {}).get("number", 1)
    home_defending_side = play.get("homeTeamDefendingSide", "")

    # Establish period 1 baseline ONLY from period 1 data
    if period == 1 and period1_baseline is None:
        if home_defending_side == "right":
            period1_baseline = {"home_goal_x": 89, "away_goal_x": -89}
        elif home_defending_side == "left":
            period1_baseline = {"home_goal_x": -89, "away_goal_x": 89}
        else:
            # Default fallback
            period1_baseline = {"home_goal_x": 89, "away_goal_x": -89}

    # Fallback if still no baseline (shouldn't happen if period1_baseline is passed correctly)
    if period1_baseline is None:
        # Default assumption: home defends right in period 1
        period1_baseline = {"home_goal_x": 89, "away_goal_x": -89}

    # Determine goal positions based on period
    is_odd_period = period % 2 == 1
    if is_odd_period:
        home_goal_x = period1_baseline["home_goal_x"]
        away_goal_x = period1_baseline["away_goal_x"]
    else:
        # In even periods, teams switch sides
        home_goal_x = period1_baseline["away_goal_x"]
        away_goal_x = period1_baseline["home_goal_x"]

    # Determine which goal the scoring team is attacking
    # HOME team attacks the AWAY goal (the goal AWAY defends)
    # AWAY team attacks the HOME goal (the goal HOME defends)
    goal_x = away_goal_x if team == "HOME" else home_goal_x

    # Calculate Euclidean distance
    return int(round(math.sqrt((x_coord - goal_x) ** 2 + y_coord**2)))


def format_goal_description(
    shot_type: str,
    distance: int,
    game_situation: str,
    strength: str,
    assists: list = None,
) -> str:
    """Format goal description with all details.

    Returns:
        str: Formatted goal description
    """
    shot_type_map = {
        "snap": "snapshot",
        "wrist": "wrister",
        "slap": "slapshot",
        "backhand": "backhand",
        "tip-in": "tip-in",
        "deflected": "deflection",
        "wrap-around": "wrap-around",
        "penalty-shot": "penalty shot",
    }
    shot_desc = shot_type_map.get(shot_type, shot_type if shot_type else "shot")

    strength_label = ""
    if strength in ["PP", "ENPP"] and strength != "EN":
        strength_label = "power play "
    elif strength == "SH":
        strength_label = "shorthanded "
    else:
        strength_label = ""

    shot_desc_lower = shot_desc.lower()

    if distance is not None:
        desc = f"{distance}' {game_situation}{strength_label}{shot_desc_lower} goal"
    else:
        desc = f"{game_situation}{strength_label}{shot_desc_lower} goal"

    if assists:
        assist_text = ", ".join(assists)
        desc += f" (assists: {assist_text})"

    return desc


def format_shot_description(shot_type: str, was_saved: bool, was_blocked: bool) -> str:
    """Format shot description based on shot type and outcome.

    Returns:
        str: Formatted shot description
    """
    shot_type_converter = {
        "snap": "snapshot",
        "slap": "slapshot",
        "wrist": "wrister",
        "backhand": "backhand",
        "tip-in": "tip-in",
        "deflected": "deflection",
        "wrap-around": "wrap-around",
    }
    shot_type_name = shot_type_converter.get(
        shot_type, shot_type if shot_type else "shot"
    )

    if was_saved:
        return f"Saved {shot_type_name} shot on goal"
    elif was_blocked:
        return f"Blocked {shot_type_name}"
    else:
        return f"Missed {shot_type_name}"


def format_penalty_description(desc_key: str, duration: int) -> str:
    """Format penalty description.

    Returns:
        str: Formatted penalty description
    """
    penalty_type_map = {
        "fighting": "fighting",
        "slashing": "slashing",
        "tripping": "tripping",
        "hooking": "hooking",
        "holding": "holding",
        "interference": "interference",
        "roughing": "roughing",
        "cross-checking": "cross-checking",
        "boarding": "boarding",
        "high-sticking": "high-sticking",
        "unsportsmanlike": "unsportsmanlike conduct",
        "delay-of-game": "delay of game",
        "too-many-men": "too many men",
    }

    penalty_desc = penalty_type_map.get(desc_key, desc_key.replace("-", " "))

    if duration > 0:
        desc = f"{duration} min {penalty_desc} penalty"
    else:
        desc = f"{penalty_desc} penalty"

    return " ".join(word.capitalize() for word in desc.split())


def get_game_situation(home_score: int, away_score: int, team: str) -> str:
    """Determine game situation (game-tying, go-ahead, etc.) for a goal.

    Returns:
        str: Game situation prefix (empty string, "game-tying ", "go-ahead ", etc.)
    """
    future_home_score = home_score + 1 if team == "HOME" else home_score
    future_away_score = away_score + 1 if team == "AWAY" else away_score

    if future_home_score == future_away_score and home_score != away_score:
        return "game-tying "
    elif (
        team == "HOME" and future_home_score > away_score and home_score == away_score
    ) or (
        team == "AWAY" and future_away_score > home_score and away_score == home_score
    ):
        return "go-ahead "
    return ""


def extract_team_info(game_data: dict) -> dict:
    """Extract team information from game data.

    Returns:
        dict: Team information including IDs, names, logos
    """
    home_team = game_data.get("homeTeam", {})
    away_team = game_data.get("awayTeam", {})

    home_team_id = home_team.get("id")
    away_team_id = away_team.get("id")
    home_team_common = home_team.get("commonName", {}).get("default", "Home Team")
    away_team_common = away_team.get("commonName", {}).get("default", "Away Team")

    home_place_name = home_team.get("placeName", {}).get("default", "")
    away_place_name = away_team.get("placeName", {}).get("default", "")
    home_team_full = (
        f"{home_place_name} {home_team_common}".strip()
        if home_place_name
        else home_team_common
    )
    away_team_full = (
        f"{away_place_name} {away_team_common}".strip()
        if away_place_name
        else away_team_common
    )

    return {
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "home_team_common": home_team_common,
        "away_team_common": away_team_common,
        "home_team_full": home_team_full,
        "away_team_full": away_team_full,
        "home_team_logo": home_team.get("logo", ""),
        "away_team_logo": away_team.get("logo", ""),
    }


def parse_situation_code(situation: str) -> tuple:
    """Parse situationCode to extract skater counts.

    Returns:
        tuple: (home_skaters, away_skaters)
    """
    # Move bounds check before int conversion to improve error handling
    if not situation or len(situation) < 4:
        return 5, 5  # Default to even strength
    
    try:
        # Validate indices exist before accessing
        if len(situation) >= 2 and situation[1].isdigit():
            away_skaters = int(situation[1])
            # Validate away_skaters is in valid range (0-6)
            if away_skaters < 0 or away_skaters > 6:
                away_skaters = 5
        else:
            away_skaters = 5
        
        if len(situation) >= 4 and situation[3].isdigit():
            home_skaters = int(situation[3])
            # Validate home_skaters is in valid range (0-6)
            if home_skaters < 0 or home_skaters > 6:
                home_skaters = 5
        else:
            home_skaters = 5
        
        return home_skaters, away_skaters
    except (ValueError, IndexError, TypeError):
        return 5, 5  # Default to even strength on any error
