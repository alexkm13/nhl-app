"""Utility functions for game ingestion and processing."""

import json
import math
from datetime import datetime

from redis.asyncio import Redis

from nhl_api import fetch_nhl_play_by_play
from event_helpers import EVENT_TYPE_MAPPING


def calculate_win_probability(
    home_score: int,
    away_score: int,
    game_state: str,
    period: int = None,
    time_in_period: str = "",
    plays: list = None,
) -> float:
    """
    Calculate win probability based on current game state.
    Takes into account:
    - Time of goals scored (later goals have more weight)
    - Amount of goals (score differential)
    - Game state (final, live, regulation, OT, SO)
    - Time remaining in period
    """
    # If game is final, return 100% for winner, 0% for loser
    if game_state in ["OFF", "FINAL"]:
        if home_score > away_score:
            return 1.0
        elif away_score > home_score:
            return 0.0
        else:
            # Tie game - should not happen in final state, but return 50%
            return 0.5

    score_diff = home_score - away_score

    # If game hasn't started or we don't have period info, use simple model
    if period is None or period == 0:
        # Simple model based only on score differential
        if score_diff == 0:
            return 0.5
        # Use sigmoid for score differential
        return 1.0 / (1.0 + math.exp(-score_diff * 0.5))

    # Calculate time remaining
    time_remaining_seconds = 0
    if time_in_period:
        try:
            # Parse MM:SS format
            parts = time_in_period.split(":")
            if len(parts) == 2:
                minutes, seconds = int(parts[0]), int(parts[1])
                time_remaining_seconds = minutes * 60 + seconds
        except (ValueError, IndexError):
            pass

    # Determine total time remaining in game
    if period <= 3:
        # Regulation time: 20 minutes per period, 3 periods
        # Time remaining = (periods_remaining * 20 * 60) + time_remaining_seconds
        periods_remaining = (3 - period) * 20 * 60
        total_time_remaining = periods_remaining + time_remaining_seconds
    elif period == 4:
        # Overtime: sudden death, typically 5 minutes
        # Use time remaining in OT period
        total_time_remaining = time_remaining_seconds
    else:
        # Shootout or beyond - should not happen, but return based on score
        if score_diff > 0:
            return 0.95  # Very high probability if leading in SO
        elif score_diff < 0:
            return 0.05  # Very low probability if trailing in SO
        else:
            return 0.5

    # Base probability from score differential
    # Each goal difference is worth more later in the game
    regulation_time_total = 3 * 20 * 60  # 3600 seconds
    time_factor = (
        1.0 - (total_time_remaining / regulation_time_total)
        if regulation_time_total > 0
        else 0.5
    )
    time_factor = max(0.0, min(1.0, time_factor))  # Clamp between 0 and 1

    # Score differential weight increases as game progresses
    score_weight = 1.2 + (time_factor * 0.8)  # 1.2 to 2.0

    # Calculate base log-odds from score differential
    base_z = score_diff * score_weight

    # Factor in time remaining (more time = less certainty)
    # If lots of time remaining, probability is closer to 50%
    # If little time remaining, probability is more extreme
    time_penalty = (
        total_time_remaining / regulation_time_total
        if regulation_time_total > 0
        else 0.5
    )
    time_penalty = max(0.0, min(1.0, time_penalty))

    # Adjust z-score based on time remaining
    adjusted_z = base_z * (1.0 + (1.0 - time_penalty) * 1.5)

    # Special handling for overtime
    if period == 4:
        # In OT, any lead is significant
        if score_diff > 0:
            adjusted_z = 3.0  # Very high probability
        elif score_diff < 0:
            adjusted_z = -3.0  # Very low probability
        else:
            # Tied in OT - consider empty net situations would improve this
            adjusted_z = 0.0

    # Convert to probability using sigmoid
    p_home = 1.0 / (1.0 + math.exp(-adjusted_z))

    # Clamp to reasonable bounds (5% to 95%)
    p_home = max(0.05, min(0.95, p_home))

    # Consider goal timing if we have plays data
    # Analyze when goals were scored - later goals have more weight
    if plays and len(plays) > 0:
        # Get team IDs from game data if available
        # For now, we'll use a simpler approach based on score differential
        # and time remaining

        # Adjust probability based on lead size and time remaining
        # Later in the game, leads become more significant
        if home_score > away_score:
            # Home team is leading - adjust based on lead size and time remaining
            lead_size = home_score - away_score
            if total_time_remaining < 300:  # Less than 5 minutes
                # Late in game, larger leads are very secure
                p_home = min(0.95, 0.5 + (lead_size * 0.15))
            elif total_time_remaining < 600:  # Less than 10 minutes
                p_home = min(0.90, 0.5 + (lead_size * 0.12))
            else:
                p_home = min(0.85, 0.5 + (lead_size * 0.10))
        elif away_score > home_score:
            # Away team is leading
            lead_size = away_score - home_score
            if total_time_remaining < 300:
                p_home = max(0.05, 0.5 - (lead_size * 0.15))
            elif total_time_remaining < 600:
                p_home = max(0.10, 0.5 - (lead_size * 0.12))
            else:
                p_home = max(0.15, 0.5 - (lead_size * 0.10))

    return p_home


async def run_ingestion(game_id: str, redis: Redis):
    """Run NHL game ingestion in background - publishes events to 'events' stream for feature_state"""
    import random
    import time

    try:
        # Clear game state and predictions to prevent accumulation
        await redis.delete(f"state:{game_id}")
        await redis.delete(f"pred:{game_id}")
        # Set a flag to signal feature_state to reset this game's state
        await redis.setex(f"reset_game:{game_id}", 60, "1")  # Expires in 60 seconds

        # Fetch and process game data from official NHL API
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
            await redis.hset(
                f"ingestion_status:{game_id}", "error", "No game data found"
            )
            return

        plays = game_data.get("plays", [])
        if not plays:
            await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
            await redis.hset(f"ingestion_status:{game_id}", "error", "No plays found")
            return

        # Get team IDs and names
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        home_team_name = (
            game_data.get("homeTeam", {})
            .get("commonName", {})
            .get("default", "Home Team")
        )
        away_team_name = (
            game_data.get("awayTeam", {})
            .get("commonName", {})
            .get("default", "Away Team")
        )

        # Cache team names for 24 hours
        await redis.setex(f"game:{game_id}:home_team", 86400, home_team_name)
        await redis.setex(f"game:{game_id}:away_team", 86400, away_team_name)

        # Get game start time
        game_start_str = game_data.get("startTimeUTC", "")
        game_start_ts = None
        if game_start_str:
            game_start = datetime.fromisoformat(game_start_str.replace("Z", "+00:00"))
            game_start_ts = game_start.timestamp()

        # Stream name that feature_state reads from
        STREAM_EVENTS = "events"

        # Process events and publish to Redis stream (same format as ingestor/main.py)
        for play in plays:
            # Skip non-relevant events
            type_code = str(play.get("typeCode", ""))
            if type_code in [
                "520",
                "516",
                "517",
                "524",
            ]:  # period-start, stoppage, period-end, game-end
                continue

            # Map event types using EVENT_TYPE_MAPPING
            mapped_type = EVENT_TYPE_MAPPING.get(
                int(type_code) if type_code.isdigit() else 0, "SHOT"
            )

            # Determine team from event owner
            details = play.get("details", {})
            event_owner_id = details.get("eventOwnerTeamId")

            # Match event owner to home/away
            if event_owner_id == home_team_id:
                team = "HOME"
            elif event_owner_id == away_team_id:
                team = "AWAY"
            else:
                # Fallback logic for events without eventOwnerTeamId
                if mapped_type == "GOAL":
                    # For goals, use defending side logic
                    team = (
                        "AWAY"
                        if play.get("homeTeamDefendingSide") == "right"
                        else "HOME"
                    )
                else:
                    # For non-crucial events, fallback to defending side
                    team = (
                        "HOME"
                        if play.get("homeTeamDefendingSide") == "right"
                        else "AWAY"
                    )

            # Get situation/strength from NHL API situationCode
            # Format: ABCD where B=away_skaters, D=home_skaters
            situation = play.get("situationCode", "1551")
            away_skaters = int(situation[1]) if len(situation) >= 2 else 5
            home_skaters = int(situation[3]) if len(situation) >= 4 else 5

            # Detect empty net situations (6 skaters or 0 skaters = goalie pulled)
            empty_net = False
            if (
                away_skaters == 6
                or home_skaters == 6
                or away_skaters == 0
                or home_skaters == 0
            ):
                empty_net = True

            # Determine strength from the event-owning team's perspective
            if team == "HOME":
                # For home team: check home skaters vs away skaters
                if empty_net:
                    if home_skaters == 6:
                        strength = "ENPP" if away_skaters < 5 else "EN"
                    elif away_skaters == 6:
                        strength = "PK"
                    elif home_skaters == 0:
                        strength = "PK"
                    elif away_skaters == 0:
                        strength = "PP"
                    else:
                        strength = "EV"
                elif home_skaters == 5 and away_skaters == 5:
                    strength = "EV"
                elif home_skaters > away_skaters:
                    strength = "PP"
                elif home_skaters < away_skaters:
                    strength = "SH" if home_skaters < 5 else "PK"
                else:
                    strength = "EV"
            else:  # team == "AWAY"
                # For away team: check away skaters vs home skaters
                if empty_net:
                    if away_skaters == 6:
                        strength = "ENPP" if home_skaters < 5 else "EN"
                    elif home_skaters == 6:
                        strength = "PK"
                    elif away_skaters == 0:
                        strength = "PK"
                    elif home_skaters == 0:
                        strength = "PP"
                    else:
                        strength = "EV"
                elif away_skaters == 5 and home_skaters == 5:
                    strength = "EV"
                elif away_skaters > home_skaters:
                    strength = "PP"
                elif away_skaters < home_skaters:
                    strength = "SH" if away_skaters < 5 else "PK"
                else:
                    strength = "EV"

            # Get timestamp from game start and period time
            time_in_period = play.get("timeInPeriod", "00:00")
            period = play.get("periodDescriptor", {}).get("number", 1)

            if game_start_ts:
                try:
                    # Calculate elapsed time in period: timeInPeriod is MM:SS elapsed
                    minutes, seconds = map(int, time_in_period.split(":"))
                    elapsed_seconds = minutes * 60 + seconds
                    # Total seconds from game start
                    period_offset = (period - 1) * 1200  # 20 minutes per period
                    total_elapsed = period_offset + elapsed_seconds
                    timestamp = game_start_ts + total_elapsed
                except Exception:
                    timestamp = time.time()
            else:
                timestamp = time.time()

            # Get coordinates if available
            x = details.get("xCoord")
            if x is None:
                x = random.uniform(-100, 100)
            y = details.get("yCoord")
            if y is None:
                y = random.uniform(-42.5, 42.5)

            # Extract player ID based on event type
            player_id = None
            if mapped_type == "FACEOFF":
                player_id = details.get("winningPlayerId")
            elif mapped_type == "GOAL":
                player_id = details.get("scoringPlayerId")
            elif mapped_type in ["SHOT", "BLOCK"]:
                player_id = details.get("shootingPlayerId")
            elif mapped_type == "HIT":
                player_id = details.get("hittingPlayerId")
            elif mapped_type == "PENALTY":
                player_id = details.get("playerId")

            # Create event payload matching GameEvent model structure
            # This format is what feature_state expects
            payload = {
                "game_id": game_id,
                "ts": timestamp,
                "team": team,
                "event_type": mapped_type,
                "strength": strength,
                "empty_net": empty_net,
                "player_id": player_id,
                "x": x,
                "y": y,
                "shot_quality": random.random(),  # Optional field
            }

            # Publish to 'events' stream (not events:{game_id}) - this is what feature_state reads
            sid = await redis.xadd(STREAM_EVENTS, {"json": json.dumps(payload)})
            print(
                f"[gateway] XADD events id={sid} {mapped_type} team={team} game={game_id}"
            )

        # Mark ingestion as complete
        await redis.hset(f"ingestion_status:{game_id}", "status", "complete")
        await redis.hset(
            f"ingestion_status:{game_id}",
            "completed_at",
            str(datetime.now().isoformat()),
        )

        print(
            f"[gateway] Ingestion complete for game {game_id}, published {len(plays)} events to 'events' stream"
        )
    except Exception as e:
        await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
        await redis.hset(f"ingestion_status:{game_id}", "error", str(e))
        print(f"[gateway] Error in background ingestion: {e}")
        import traceback

        traceback.print_exc()


async def check_overtime_type(game_id: str) -> str:
    """Check if a completed game went to overtime or shootout"""
    try:
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            return None

        plays = game_data.get("plays", [])
        if not plays:
            return None

        # Check for shootout goals
        shootout_goals = 0
        for play in plays:
            period_descriptor = play.get("periodDescriptor", {})
            period_num = period_descriptor.get("number", 0)
            if period_num > 4:  # Shootout is period 5+
                type_code = play.get("typeCode")
                if type_code == 505:  # GOAL
                    shootout_goals += 1

        if shootout_goals > 0:
            return "SO"

        # Check for overtime period
        max_period = 0
        for play in plays:
            period_descriptor = play.get("periodDescriptor", {})
            period_num = period_descriptor.get("number", 1)
            if period_num > max_period:
                max_period = period_num

        if max_period > 3:
            return "OT"

        return None
    except Exception as e:
        print(f"[gateway] Error checking overtime type for game {game_id}: {e}")
        return None
