"""Game-related API routes."""

import asyncio
import logging
import os
import sys
import time
from datetime import datetime

import psycopg
from fastapi import APIRouter, HTTPException
from redis.asyncio import Redis

# Add parent directory to path for common imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from common.logging_config import setup_logger

logger = setup_logger("gateway.routes.games", level=logging.INFO)

from nhl_api import (  # noqa: E402
    fetch_nhl_boxscore,
    fetch_nhl_daily_schedule,
    fetch_nhl_play_by_play,
    fetch_team_standings,
)
from player_utils import get_player_name, get_player_headshot  # noqa: E402
from models import WinProb  # noqa: E402
from utils import check_overtime_type, run_ingestion, calculate_win_probability  # noqa: E402

router = APIRouter(prefix="/v1/games", tags=["games"])

DATABASE_URL = os.environ.get("DATABASE_URL", "")


# Helper function to get app state (will be injected)
def get_redis() -> Redis:
    """Get Redis instance from app state."""
    from main import app

    return app.state.redis


@router.get("")
async def list_games(date: str = None):
    """List NHL games for a specific date (YYYY-MM-DD) or today if not specified"""
    try:
        r = get_redis()
        schedule = await fetch_nhl_daily_schedule(date)

        # Fetch team standings for records
        standings = await fetch_team_standings(r)

        games = []
        games_list = schedule.get("games", []) if isinstance(schedule, dict) else []
        completed_game_ids = []

        for game in games_list:
            if isinstance(game, dict):
                # Get team names
                away_team = game.get("awayTeam", {})
                home_team = game.get("homeTeam", {})

                # Get team abbreviations for matching with standings
                away_team_abbrev = away_team.get("abbrev", "")
                home_team_abbrev = home_team.get("abbrev", "")

                # Get team records from standings (standings are keyed by abbreviation)
                away_record = None
                home_record = None
                if standings:
                    away_team_stats = standings.get(away_team_abbrev, {})
                    home_team_stats = standings.get(home_team_abbrev, {})

                    if away_team_stats:
                        away_record = f"{away_team_stats.get('wins', 0)}-{away_team_stats.get('losses', 0)}-{away_team_stats.get('ot_losses', 0)}"
                    if home_team_stats:
                        home_record = f"{home_team_stats.get('wins', 0)}-{home_team_stats.get('losses', 0)}-{home_team_stats.get('ot_losses', 0)}"

                # Get start time in UTC - let client convert to local time
                start_time = game.get("startTimeUTC", "")

                # Get spread (mock for now - can be replaced with real betting API)
                spread_value = None
                spread_favorite = None
                over_under = None

                # Check if game went to overtime or shootout (for completed games)
                game_state = game.get("gameState", "")
                game_id = str(game.get("id", ""))
                overtime_type = None

                # For live games, get period and time remaining
                period = None
                time_in_period = None
                if game_state in ["LIVE", "CRIT"]:
                    period_descriptor = game.get("periodDescriptor", {})
                    period = period_descriptor.get("number", None)

                    # Try to get time from periodDescriptor first (most current for live games)
                    is_time_remaining = False
                    if period_descriptor:
                        # timeRemaining is the official remaining time field
                        if period_descriptor.get("timeRemaining"):
                            time_in_period = period_descriptor.get("timeRemaining")
                            is_time_remaining = True
                            print(f"[DEBUG] Game {game_id}: Using timeRemaining = {time_in_period}")
                        # clock is typically remaining time in MM:SS format
                        elif period_descriptor.get("clock"):
                            time_in_period = period_descriptor.get("clock")
                            is_time_remaining = True
                            print(f"[DEBUG] Game {game_id}: Using clock = {time_in_period}")
                        # timeInPeriod might be elapsed or remaining - NHL API is inconsistent
                        # Based on testing, this appears to be remaining time in live games
                        elif period_descriptor.get("timeInPeriod"):
                            time_in_period = period_descriptor.get("timeInPeriod")
                            is_time_remaining = True
                            print(f"[DEBUG] Game {game_id}: Using timeInPeriod = {time_in_period}")
                        elif period_descriptor.get("time"):
                            time_in_period = period_descriptor.get("time")
                            is_time_remaining = True
                            print(f"[DEBUG] Game {game_id}: Using time = {time_in_period}")

                    # If not found in periodDescriptor, try to get from boxscore for more current time
                    if not time_in_period:
                        try:
                            boxscore_data = await fetch_nhl_boxscore(game_id)
                            if boxscore_data:
                                boxscore_period = boxscore_data.get(
                                    "periodDescriptor", {}
                                )
                                if boxscore_period:
                                    boxscore_period_num = boxscore_period.get(
                                        "number", None
                                    )
                                    if boxscore_period_num:
                                        period = boxscore_period_num

                                    if boxscore_period.get("timeRemaining"):
                                        time_in_period = boxscore_period.get(
                                            "timeRemaining"
                                        )
                                        is_time_remaining = True
                                        print(f"[DEBUG] Game {game_id}: Using boxscore timeRemaining = {time_in_period}")
                                    elif boxscore_period.get("clock"):
                                        time_in_period = boxscore_period.get("clock")
                                        is_time_remaining = True
                                        print(f"[DEBUG] Game {game_id}: Using boxscore clock = {time_in_period}")
                                    elif boxscore_period.get("timeInPeriod"):
                                        time_in_period = boxscore_period.get(
                                            "timeInPeriod"
                                        )
                                        is_time_remaining = True
                                        print(f"[DEBUG] Game {game_id}: Using boxscore timeInPeriod = {time_in_period}")
                                    elif boxscore_period.get("time"):
                                        time_in_period = boxscore_period.get("time")
                                        is_time_remaining = True
                                        print(f"[DEBUG] Game {game_id}: Using boxscore time = {time_in_period}")
                        except Exception:
                            pass

                    # If still not found, get from most recent play
                    # Note: timeInPeriod from plays is typically ELAPSED time
                    if not time_in_period:
                        plays = game.get("plays", [])
                        if plays:
                            for play in reversed(plays):
                                play_time = play.get("timeInPeriod", None)
                                if play_time:
                                    time_in_period = play_time
                                    # Mark as elapsed time (will be converted by frontend)
                                    is_time_remaining = False
                                    play_period = play.get("periodDescriptor", {}).get(
                                        "number", None
                                    )
                                    if play_period:
                                        period = play_period
                                    print(f"[DEBUG] Game {game_id}: Using play timeInPeriod (elapsed) = {time_in_period}")
                                    break

                    # Final debug log
                    if not time_in_period:
                        print(f"[DEBUG] Game {game_id}: No time found, will default to 20:00")

                # Track completed games to check OT/SO status
                if game_state in ["OFF", "FINAL"]:
                    completed_game_ids.append(game_id)

                games.append(
                    {
                        "game_id": game_id,
                        "away_team": away_team.get("abbrev", ""),
                        "away_team_name": away_team.get("commonName", {}).get(
                            "default", ""
                        ),
                        "away_team_logo": away_team.get("logo", ""),
                        "away_team_record": away_record,
                        "home_team": home_team.get("abbrev", ""),
                        "home_team_name": home_team.get("commonName", {}).get(
                            "default", ""
                        ),
                        "home_team_logo": home_team.get("logo", ""),
                        "home_team_record": home_record,
                        "venue": game.get("venue", {}).get("default", ""),
                        "start_time_utc": start_time,
                        "game_state": game_state,
                        "away_score": game.get("awayScore", 0)
                        if "awayScore" in game
                        else away_team.get("score", 0),
                        "home_score": game.get("homeScore", 0)
                        if "homeScore" in game
                        else home_team.get("score", 0),
                        "period": period,
                        "time_in_period": time_in_period,
                        "is_time_remaining": is_time_remaining
                        if time_in_period
                        else None,
                        "spread": spread_value,
                        "spread_favorite": spread_favorite,
                        "over_under": over_under,
                        "overtime_type": overtime_type,
                    }
                )

        # Check OT/SO status for completed games in parallel
        if completed_game_ids:
            ot_checks = await asyncio.gather(
                *[check_overtime_type(game_id) for game_id in completed_game_ids]
            )
            ot_map = dict(zip(completed_game_ids, ot_checks))
            for game in games:
                if game["game_id"] in ot_map:
                    game["overtime_type"] = ot_map[game["game_id"]]

        # Sort games by start time
        games.sort(key=lambda x: x.get("start_time_utc", ""))

        return {
            "date": schedule.get("date", "") if isinstance(schedule, dict) else "",
            "games": games,
            "total_games": len(games),
        }
    except Exception as e:
        return {"error": str(e), "games": [], "total_games": 0}


@router.post("/{game_id}/start")
async def start_game_ingestion(game_id: str):
    """Trigger ingestion for a specific game"""
    try:
        # Verify game exists
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        home_team = (
            game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home")
        )
        away_team = (
            game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away")
        )

        r = get_redis()

        # Check if ingestion is already in progress
        existing = await r.hget(f"ingestion_status:{game_id}", "status")
        if existing and existing == "in_progress":
            return {
                "message": f"Ingestion already in progress for {away_team} @ {home_team}",
                "game_id": game_id,
                "matchup": f"{away_team} @ {home_team}",
                "status": "in_progress",
            }

        # Mark as in progress
        await r.hset(
            f"ingestion_status:{game_id}",
            mapping={
                "status": "in_progress",
                "game_id": game_id,
                "matchup": f"{away_team} @ {home_team}",
            },
        )

        # Run ingestion in background with error handling
        task = asyncio.create_task(run_ingestion(game_id, r))

        # Add callback to log any uncaught exceptions
        def handle_task_exception(task):
            try:
                task.result()
            except Exception as e:
                logger.error(f"Uncaught exception in background ingestion task: {e}", exc_info=True)

        task.add_done_callback(handle_task_exception)

        return {
            "message": f"Started ingestion for {away_team} @ {home_team}",
            "game_id": game_id,
            "matchup": f"{away_team} @ {home_team}",
            "status": "started",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/{game_id}/refresh")
async def refresh_game_predictions(game_id: str):
    """Incrementally refresh predictions for a game without clearing existing state"""
    try:
        # Verify game exists
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        r = get_redis()

        # Check if initial ingestion has been done
        existing_state = await r.hgetall(f"state:{game_id}")
        if not existing_state:
            # No state exists, need to run full ingestion first
            return {
                "message": "No existing state found. Please start ingestion first with POST /start",
                "game_id": game_id,
                "status": "skipped",
            }

        # Get last processed event timestamp (stored for reference)
        await r.get(f"last_event_ts:{game_id}")

        # Process only new events
        plays = game_data.get("plays", [])
        new_events = [p for p in plays if p.get("timeInPeriod", "") and
                      p.get("periodDescriptor", {}).get("number", 0) > 0]

        # Filter for events newer than last processed
        # Note: NHL API doesn't provide timestamps, so we'll use a sequential approach
        # Get current event count from state
        current_event_count = len(new_events)
        last_event_count = await r.get(f"last_event_count:{game_id}")
        prev_count = int(last_event_count) if last_event_count else 0

        if current_event_count <= prev_count:
            return {
                "message": "No new events to process",
                "game_id": game_id,
                "status": "up_to_date",
            }

        # Get team IDs for event processing
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")

        # Process only new events (events beyond prev_count)
        new_plays = plays[prev_count:]

        # Stream name that feature_state reads from
        STREAM_EVENTS = "events"

        # Publish only new events to stream (same format as run_ingestion)
        for play in new_plays:
            type_code = str(play.get("typeCode", ""))
            if type_code in ["520", "516", "517", "524"]:
                continue

            from ..utils import EVENT_TYPE_MAPPING
            mapped_type = EVENT_TYPE_MAPPING.get(
                int(type_code) if type_code.isdigit() else 0, "SHOT"
            )

            details = play.get("details", {})
            event_owner_id = details.get("eventOwnerTeamId")

            if event_owner_id == home_team_id:
                team = "HOME"
            elif event_owner_id == away_team_id:
                team = "AWAY"
            else:
                continue

            period_descriptor = play.get("periodDescriptor", {})
            period = period_descriptor.get("number", 1)
            time_in_period = play.get("timeInPeriod", "00:00")

            event_data = {
                "game_id": game_id,
                "event_idx": play.get("eventId", 0),
                "period": str(period),
                "period_time": time_in_period,
                "event_type": mapped_type,
                "team": team,
            }

            await r.xadd(STREAM_EVENTS, event_data)

        # Update last processed event count
        await r.set(f"last_event_count:{game_id}", str(current_event_count))

        return {
            "message": f"Processed {len(new_plays)} new events",
            "game_id": game_id,
            "new_events": len(new_plays),
            "status": "refreshed",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/{game_id}/status")
async def get_game_status(game_id: str):
    """Check ingestion and prediction status for a game"""
    r = get_redis()

    # Check ingestion status
    ingestion_status = await r.hgetall(f"ingestion_status:{game_id}")

    # Check if prediction exists
    prediction = await r.hgetall(f"pred:{game_id}")

    # Check if state exists
    state = await r.hgetall(f"state:{game_id}")

    status = ingestion_status.get("status", "not_started")
    has_prediction = bool(prediction)
    has_state = bool(state)

    return {
        "game_id": game_id,
        "matchup": ingestion_status.get("matchup", "Unknown"),
        "ingestion_status": status,
        "has_prediction": has_prediction,
        "has_state": has_state,
        "error": ingestion_status.get("error"),
        "message": (
            "Prediction available"
            if has_prediction
            else "Ingestion in progress, please wait..."
            if status == "in_progress"
            else "Ingestion completed, waiting for prediction..."
            if status == "completed"
            else "Ingestion failed"
            if status == "failed"
            else "No ingestion started yet. Call POST /v1/games/{game_id}/start to begin."
        ),
    }


@router.get("/{game_id}/winprob", response_model=WinProb)
async def get_winprob(game_id: str):
    r = get_redis()
    key = f"pred:{game_id}"
    data = await r.hgetall(key)
    if not data:
        # Check if ingestion is in progress
        ingestion_status = await r.hget(f"ingestion_status:{game_id}", "status")
        if ingestion_status == "in_progress":
            raise HTTPException(
                status_code=202,
                detail="Ingestion in progress. Please wait 60-90 seconds and try again. Check status at GET /v1/games/{game_id}/status",
            )
        elif ingestion_status == "failed":
            error = await r.hget(f"ingestion_status:{game_id}", "error")
            raise HTTPException(
                status_code=500,
                detail=f"Ingestion failed: {error}. Check status at GET /v1/games/{game_id}/status",
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No prediction yet for game {game_id}. Start ingestion with POST /v1/games/{game_id}/start",
            )
    try:
        # Validate all required fields exist and are valid
        # Redis hgetall returns all values as strings, so we need to validate and convert
        game_id_val = data.get("game_id")
        p_home_win_val = data.get("p_home_win")
        model_id_val = data.get("model_id")
        ts_val = data.get("ts")

        # Check if required fields are missing, empty, or invalid strings
        # Handle cases where Redis returns "None" as a string or empty strings
        if (not game_id_val or
                not p_home_win_val or
                not model_id_val or
                ts_val is None or
                ts_val == "" or
                ts_val.lower() == "none"):
            raise HTTPException(status_code=404, detail="No prediction yet for this game")

        # Convert to appropriate types with error handling
        try:
            p_home_win_float = float(p_home_win_val)
            # Validate probability is in valid range
            if not (0.0 <= p_home_win_float <= 1.0):
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid probability value: {p_home_win_float}. Must be between 0.0 and 1.0."
                )
            ts_float = float(ts_val)
        except (ValueError, TypeError) as e:
            # Handle cases where ts might be "None", empty string, or invalid
            raise HTTPException(
                status_code=500,
                detail=f"Invalid prediction data format: {str(e)}. Prediction may be incomplete."
            )

        return WinProb(
            game_id=game_id_val,
            p_home_win=p_home_win_float,
            model_id=model_id_val,
            ts=ts_float,
        )
    except HTTPException:
        raise
    except Exception as e:
        # Catch any other unexpected errors
        raise HTTPException(status_code=500, detail=f"Error retrieving prediction: {str(e)}")


@router.get("/{game_id}/winprob/history")
async def get_winprob_history(game_id: str):
    """Get historical win probability data for graphing"""
    try:
        if not DATABASE_URL:
            return {"game_id": game_id, "data": []}

        # Get game start time from NHL API to calculate relative time
        game_data = await fetch_nhl_play_by_play(game_id)
        game_start_ts = None
        if game_data:
            game_start_str = game_data.get("startTimeUTC", "")
            if game_start_str:
                try:
                    game_start = datetime.fromisoformat(
                        game_start_str.replace("Z", "+00:00")
                    )
                    game_start_ts = game_start.timestamp()
                except Exception:
                    pass

        # Use connection pool if available, otherwise fall back to direct connection
        from db_pool import get_db_connection, get_db_pool

        db_pool = get_db_pool()
        if db_pool:
            async with get_db_connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT ts, p_home_win
                        FROM predictions
                        WHERE game_id = %s
                        ORDER BY ts ASC
                        """,
                        (game_id,),
                    )
                    rows = await cur.fetchall()

                    # Calculate relative time (seconds elapsed from game start)
                    # Filter out invalid timestamps (e.g., 1970-01-01 from old bug)
                    data = []
                    for ts, p_home_win in rows:
                        # Skip NULL or invalid values
                        if ts is None or p_home_win is None:
                            continue

                        try:
                            ts_timestamp = float(ts.timestamp())
                            p_home_win_float = float(p_home_win)
                        except (AttributeError, TypeError, ValueError):
                            # Skip invalid data types
                            continue

                        # Skip timestamps that are clearly wrong (before 2020 or way in future)
                        # Valid predictions should be recent (after 2020)
                        if ts_timestamp < 1577836800:  # Before 2020-01-01
                            continue
                        # Tighten future timestamp check - not allow future times (only allow small buffer for clock skew)
                        current_time = time.time()
                        if ts_timestamp > current_time + 60:  # More than 60 seconds in future (allow small clock skew)
                            continue

                        if game_start_ts:
                            relative_time = ts_timestamp - game_start_ts
                            # Only include predictions that occurred during or after game start
                            # Allow some leeway for predictions slightly before game start
                            if relative_time >= -300:  # Allow 5 minutes before game start
                                data.append(
                                    {
                                        "ts": max(0, relative_time),
                                        "p_home_win": p_home_win_float,
                                    }
                                )
                        else:
                            # No game start time available - use timestamp as-is if reasonable
                            # This shouldn't happen in normal operation
                            data.append(
                                {"ts": ts_timestamp, "p_home_win": p_home_win_float}
                            )

                    return {"game_id": game_id, "data": data}
        else:
            # Fallback to direct connection if pool not available
            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT ts, p_home_win
                        FROM predictions
                        WHERE game_id = %s
                        ORDER BY ts ASC
                        """,
                        (game_id,),
                    )
                    rows = await cur.fetchall()
                    # Process rows same as above (simplified for fallback)
                    data = []
                    for ts, p_home_win in rows:
                        if ts is None or p_home_win is None:
                            continue
                        try:
                            ts_timestamp = float(ts.timestamp())
                            p_home_win_float = float(p_home_win)
                            if ts_timestamp < 1577836800 or ts_timestamp > time.time() + 60:
                                continue
                            if game_start_ts:
                                relative_time = ts_timestamp - game_start_ts
                                if relative_time >= -300:
                                    data.append({"ts": max(0, relative_time), "p_home_win": p_home_win_float})
                            else:
                                data.append({"ts": ts_timestamp, "p_home_win": p_home_win_float})
                        except (AttributeError, TypeError, ValueError):
                            continue
                    return {"game_id": game_id, "data": data}
    except Exception as e:
        logger.error(f"Error fetching win probability history for game {game_id}: {e}", exc_info=True)
        return {"game_id": game_id, "data": []}


@router.get("/{game_id}/rosters")
async def get_game_rosters(game_id: str):
    """Get rosters for both teams in a game"""
    try:
        boxscore = await fetch_nhl_boxscore(game_id)
        if not boxscore:
            raise HTTPException(
                status_code=404,
                detail=f"Game {game_id} not found or boxscore unavailable",
            )

        # Extract roster data
        home_team = boxscore.get("homeTeam", {})
        away_team = boxscore.get("awayTeam", {})

        # Get roster from boxscore
        home_roster_data = home_team.get("roster", {})
        away_roster_data = away_team.get("roster", {})

        home_roster = (
            home_roster_data.get("roster", [])
            if isinstance(home_roster_data, dict)
            else []
        )
        away_roster = (
            away_roster_data.get("roster", [])
            if isinstance(away_roster_data, dict)
            else []
        )

        # Format roster players
        def format_player(player):
            """Format player data from roster"""
            return {
                "id": player.get("playerId"),
                "name": player.get("firstName", {}).get("default", "")
                + " "
                + player.get("lastName", {}).get("default", ""),
                "position": player.get("position"),
                "number": player.get("sweaterNumber"),
            }

        home_roster_formatted = [
            format_player(p) for p in home_roster if p.get("playerId")
        ]
        away_roster_formatted = [
            format_player(p) for p in away_roster if p.get("playerId")
        ]

        return {
            "game_id": game_id,
            "home_team": {
                "id": home_team.get("id"),
                "name": home_team.get("commonName", {}).get("default", ""),
                "abbrev": home_team.get("abbrev", ""),
                "logo": home_team.get("logo", ""),
                "roster": home_roster_formatted,
            },
            "away_team": {
                "id": away_team.get("id"),
                "name": away_team.get("commonName", {}).get("default", ""),
                "abbrev": away_team.get("abbrev", ""),
                "logo": away_team.get("logo", ""),
                "roster": away_roster_formatted,
            },
        }
    except Exception as e:
        logger.error(f"Error fetching rosters for game {game_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching rosters: {str(e)}")


@router.get("/{game_id}/final")
async def get_final_score(game_id: str):
    """Get final score and game state for a completed game"""
    try:
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        game_state = game_data.get("gameState", "")
        home_team_data = game_data.get("homeTeam", {})
        away_team_data = game_data.get("awayTeam", {})
        home_team = home_team_data.get("commonName", {}).get("default", "Home Team")
        away_team = away_team_data.get("commonName", {}).get("default", "Away Team")
        home_logo = home_team_data.get("logo", "")
        away_logo = away_team_data.get("logo", "")
        home_abbrev = home_team_data.get("abbrev", "")
        away_abbrev = away_team_data.get("abbrev", "")
        home_score = home_team_data.get("score", 0)
        away_score = away_team_data.get("score", 0)

        # Determine winner
        winner = None
        if home_score > away_score:
            winner = "HOME"
        elif away_score > home_score:
            winner = "AWAY"
        else:
            winner = "TIE"

        # Check if game went to overtime or shootout
        max_period = 3
        overtime_type = None

        plays = game_data.get("plays", [])
        if plays:
            for play in plays:
                period_descriptor = play.get("periodDescriptor", {})
                period_number = period_descriptor.get("number", 1)
                if period_number > max_period:
                    max_period = period_number
                    if period_number == 4:
                        overtime_type = "OT"
                    elif period_number >= 5:
                        overtime_type = "SO"

        return {
            "game_id": game_id,
            "game_state": game_state,
            "is_final": game_state in ["OFF", "FINAL"],
            "home_team": home_team,
            "away_team": away_team,
            "home_abbrev": home_abbrev,
            "away_abbrev": away_abbrev,
            "home_logo": home_logo,
            "away_logo": away_logo,
            "home_score": home_score,
            "away_score": away_score,
            "winner": winner,
            "overtime_type": overtime_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching final score: {str(e)}"
        )


@router.get("/{game_id}/powerplay")
async def get_powerplay_status(game_id: str):
    """Get current power play status and time remaining"""
    r = get_redis()

    try:
        # Fetch game data from NHL API
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        # Get current game state
        game_state = game_data.get("gameState", "")
        if game_state not in ["LIVE", "CRIT"]:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None,
            }

        # Get plays from game data
        plays = game_data.get("plays", [])
        if not plays:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None,
            }

        # Get the most recent non-stoppage play
        current_play = None
        for p in reversed(plays):
            tc = p.get("typeCode")
            if tc not in [520, 516, 517, 524]:  # Skip stoppages
                current_play = p
                break

        if not current_play:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None,
            }

        # Check situation code to determine if there's a power play
        situation_code = current_play.get("situationCode", "1551")
        if len(situation_code) < 4:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None,
            }

        away_skaters = int(situation_code[1]) if len(situation_code) >= 2 else 5
        home_skaters = int(situation_code[3]) if len(situation_code) >= 4 else 5

        # Determine which team is on the power play based on skater count
        pp_team = None
        if away_skaters != home_skaters and away_skaters != 6 and home_skaters != 6:
            if home_skaters > away_skaters:
                pp_team = "HOME"
            elif away_skaters > home_skaters:
                pp_team = "AWAY"

        if not pp_team:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None,
            }

        # Get team IDs
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")

        # Find the most recent penalty event that matches the current power play
        most_recent_penalty = None
        current_time = current_play.get("timeInPeriod", "00:00")
        current_period = current_play.get("periodDescriptor", {}).get("number", 1)

        for play in reversed(plays):
            type_code = play.get("typeCode")
            if type_code == 509:  # PENALTY
                details = play.get("details", {})
                event_owner_id = details.get("eventOwnerTeamId")

                # Determine which team took the penalty
                penalty_team = None
                if event_owner_id == home_team_id:
                    penalty_team = "AWAY"
                elif event_owner_id == away_team_id:
                    penalty_team = "HOME"

                if penalty_team != pp_team:
                    continue

                penalty_duration = details.get("duration", 0)
                penalty_time = play.get("timeInPeriod", "00:00")
                period = play.get("periodDescriptor", {}).get("number", 1)

                # Calculate time elapsed since penalty
                def time_to_seconds(time_str):
                    """Convert MM:SS time string to total seconds elapsed in period"""
                    try:
                        minutes, seconds = map(int, time_str.split(":"))
                        return (20 * 60) - (minutes * 60 + seconds)
                    except (ValueError, TypeError):
                        return 0

                penalty_elapsed = time_to_seconds(penalty_time)
                current_elapsed = time_to_seconds(current_time)

                # Calculate total time elapsed since penalty
                if current_period == period:
                    time_elapsed = current_elapsed - penalty_elapsed
                elif current_period > period:
                    time_remaining_in_penalty_period = (20 * 60) - penalty_elapsed
                    time_elapsed = time_remaining_in_penalty_period + current_elapsed
                    if current_period > period + 1:
                        time_elapsed += (current_period - period - 1) * 20 * 60
                else:
                    time_elapsed = penalty_duration * 60 + 1

                penalty_duration_seconds = penalty_duration * 60
                time_remaining_seconds = max(0, penalty_duration_seconds - time_elapsed)

                if time_remaining_seconds > 0 and time_elapsed >= 0:
                    most_recent_penalty = {
                        "team": pp_team,
                        "duration": penalty_duration,
                        "time_remaining": time_remaining_seconds,
                    }
                    break

        if most_recent_penalty and most_recent_penalty["time_remaining"] > 0:
            # Get team logo for the team on PP
            team_logo_key = (
                f"game:{game_id}:{'home' if pp_team == 'HOME' else 'away'}_logo"
            )
            team_logo = await r.get(team_logo_key)

            if not team_logo:
                if pp_team == "HOME":
                    team_logo = game_data.get("homeTeam", {}).get("logo", "")
                else:
                    team_logo = game_data.get("awayTeam", {}).get("logo", "")

            # Get player strengths from situation code
            situation_code = (
                current_play.get("situationCode", "1551") if current_play else "1551"
            )
            away_skaters = int(situation_code[1]) if len(situation_code) >= 2 else 5
            home_skaters = int(situation_code[3]) if len(situation_code) >= 4 else 5

            if pp_team == "HOME":
                strength = f"{home_skaters} on {away_skaters}"
            else:
                strength = f"{away_skaters} on {home_skaters}"

            time_remaining_seconds = most_recent_penalty["time_remaining"]
            penalty_duration_seconds = most_recent_penalty["duration"] * 60
            time_elapsed = penalty_duration_seconds - time_remaining_seconds

            return {
                "is_powerplay": True,
                "team": pp_team,
                "time_remaining": time_remaining_seconds,
                "time_elapsed": time_elapsed,
                "team_logo": team_logo or None,
                "strength": strength,
            }
        else:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None,
            }

    except Exception as e:
        logger.error(f"Error getting power play status for game {game_id}: {e}", exc_info=True)
        return {
            "is_powerplay": False,
            "team": None,
            "time_remaining": None,
            "team_logo": None,
        }


@router.get("/{game_id}/stats")
async def get_game_stats(game_id: str):
    """Get game statistics (shots, hits, faceoffs, etc.) for head-to-head display"""
    try:
        boxscore = await fetch_nhl_boxscore(game_id)
        if not boxscore:
            raise HTTPException(
                status_code=404,
                detail=f"Game {game_id} not found or boxscore unavailable",
            )

        home_team = boxscore.get("homeTeam", {})
        away_team = boxscore.get("awayTeam", {})

        # Extract team info
        home_team_name = home_team.get("commonName", {}).get("default", "")
        away_team_name = away_team.get("commonName", {}).get("default", "")
        home_team_logo = home_team.get("logo", "")
        away_team_logo = away_team.get("logo", "")
        home_team_abbrev = home_team.get("abbrev", "")
        away_team_abbrev = away_team.get("abbrev", "")

        # Get player stats to sum up team totals
        player_stats = boxscore.get("playerByGameStats", {})
        home_players = player_stats.get("homeTeam", {})
        away_players = player_stats.get("awayTeam", {})

        # Helper to sum stats from all players
        def sum_player_stat(players_dict, stat_key):
            total = 0
            for position_group in ["forwards", "defense", "goalies"]:
                players = players_dict.get(position_group, [])
                for player in players:
                    if isinstance(player, dict):
                        val = player.get(stat_key, 0)
                        if isinstance(val, (int, float)):
                            total += val
            return int(total)

        # Get shots directly from team objects
        home_shots = home_team.get("sog", 0)
        away_shots = away_team.get("sog", 0)

        # Sum other stats from player data
        home_hits = sum_player_stat(home_players, "hits")
        away_hits = sum_player_stat(away_players, "hits")

        home_blocked = sum_player_stat(home_players, "blockedShots")
        away_blocked = sum_player_stat(away_players, "blockedShots")

        # Try to get takeaways/giveaways from team level first, then fall back to player sum
        home_takeaways = (
            home_team.get("takeaways")
            if "takeaways" in home_team
            else home_team.get("takeAways")
            if "takeAways" in home_team
            else None
        )
        if home_takeaways is None:
            home_takeaways = sum_player_stat(
                home_players, "takeaways"
            ) or sum_player_stat(home_players, "takeAways")

        away_takeaways = (
            away_team.get("takeaways")
            if "takeaways" in away_team
            else away_team.get("takeAways")
            if "takeAways" in away_team
            else None
        )
        if away_takeaways is None:
            away_takeaways = sum_player_stat(
                away_players, "takeaways"
            ) or sum_player_stat(away_players, "takeAways")

        home_giveaways = (
            home_team.get("giveaways")
            if "giveaways" in home_team
            else home_team.get("giveAways")
            if "giveAways" in home_team
            else None
        )
        if home_giveaways is None:
            home_giveaways = sum_player_stat(
                home_players, "giveaways"
            ) or sum_player_stat(home_players, "giveAways")

        away_giveaways = (
            away_team.get("giveaways")
            if "giveaways" in away_team
            else away_team.get("giveAways")
            if "giveAways" in away_team
            else None
        )
        if away_giveaways is None:
            away_giveaways = sum_player_stat(
                away_players, "giveaways"
            ) or sum_player_stat(away_players, "giveAways")

        home_pim = sum_player_stat(home_players, "pim")
        away_pim = sum_player_stat(away_players, "pim")

        # Calculate faceoff percentage from actual play-by-play data
        async def calculate_faceoff_pct_from_plays(game_id, home_team_id, away_team_id):
            """Count actual faceoffs from play-by-play data"""
            try:
                game_data = await fetch_nhl_play_by_play(game_id)
                if not game_data:
                    return 0, 0

                plays = game_data.get("plays", [])
                if not plays:
                    return 0, 0

                home_won = 0
                away_won = 0
                total_faceoffs = 0

                # Count faceoffs (type_code 502)
                for play in plays:
                    type_code = play.get("typeCode")
                    if type_code == 502:  # FACEOFF
                        details = play.get("details", {})
                        event_owner_team_id = details.get("eventOwnerTeamId")

                        if event_owner_team_id == home_team_id:
                            home_won += 1
                        elif event_owner_team_id == away_team_id:
                            away_won += 1
                        else:
                            continue

                        total_faceoffs += 1

                if total_faceoffs > 0:
                    home_pct = round((home_won / total_faceoffs) * 100, 1)
                    away_pct = round((away_won / total_faceoffs) * 100, 1)
                    return home_pct, away_pct
                else:
                    return 0.0, 0.0
            except Exception as e:
                logger.error(f"Error calculating faceoff percentage for game {game_id}: {e}", exc_info=True)
                return 0, 0

        # Get team IDs for faceoff calculation
        home_team_id = home_team.get("id")
        away_team_id = away_team.get("id")

        # Calculate faceoff percentages from actual play-by-play data
        home_fo_pct, away_fo_pct = await calculate_faceoff_pct_from_plays(
            game_id, home_team_id, away_team_id
        )

        # Calculate power play stats - get from team stats first, fallback to player stats
        home_pp_goals = None
        away_pp_goals = None

        # Check team-level stats first
        for field_name in ["powerPlayGoals", "ppGoals", "powerPlayG", "ppG"]:
            if field_name in home_team:
                val = home_team.get(field_name)
                if val is not None and val != "":
                    home_pp_goals = val
            if field_name in away_team:
                val = away_team.get(field_name)
                if val is not None and val != "":
                    away_pp_goals = val
            if home_pp_goals is not None and away_pp_goals is not None:
                break

        # Check teamStats.teamSkaterStats (NHL API structure)
        if home_pp_goals is None or away_pp_goals is None:
            home_stats = home_team.get("teamStats", {})
            away_stats = away_team.get("teamStats", {})
            home_skater_stats = (
                home_stats.get("teamSkaterStats", {}) if home_stats else {}
            )
            away_skater_stats = (
                away_stats.get("teamSkaterStats", {}) if away_stats else {}
            )

            if home_skater_stats:
                for field_name in ["powerPlayGoals", "ppGoals", "powerPlayG", "ppG"]:
                    if field_name in home_skater_stats:
                        val = home_skater_stats.get(field_name)
                        if val is not None and val != "":
                            home_pp_goals = val
                            break
            if away_skater_stats:
                for field_name in ["powerPlayGoals", "ppGoals", "powerPlayG", "ppG"]:
                    if field_name in away_skater_stats:
                        val = away_skater_stats.get(field_name)
                        if val is not None and val != "":
                            away_pp_goals = val
                            break

        # Fallback to summing player stats if not found in team stats
        if home_pp_goals is None:
            home_pp_goals = sum_player_stat(home_players, "powerPlayGoals")
        if away_pp_goals is None:
            away_pp_goals = sum_player_stat(away_players, "powerPlayGoals")

        # Ensure we have valid integers
        home_pp_goals = int(home_pp_goals) if home_pp_goals is not None else 0
        away_pp_goals = int(away_pp_goals) if away_pp_goals is not None else 0

        # Calculate power play opportunities by counting actual penalties from play-by-play
        async def calculate_pp_opportunities_from_plays(
            game_id, home_team_id, away_team_id
        ):
            """Count actual power play opportunities by counting penalties"""
            try:
                game_data = await fetch_nhl_play_by_play(game_id)
                if not game_data:
                    return 0, 0

                plays = game_data.get("plays", [])
                if not plays:
                    return 0, 0

                home_pp_opp = 0
                away_pp_opp = 0
                penalty_times = {}

                for play in plays:
                    type_code = play.get("typeCode")
                    if type_code == 509:  # PENALTY
                        details = play.get("details", {})
                        penalty_duration = details.get("duration", 0)

                        if penalty_duration >= 2:
                            event_owner_team_id = details.get("eventOwnerTeamId")

                            period = play.get("periodDescriptor", {}).get("number", 1)
                            time_in_period = play.get("timeInPeriod", "00:00")
                            try:
                                minutes, seconds = map(int, time_in_period.split(":"))
                                timestamp_key = f"{period}:{minutes}:{seconds}"
                            except (ValueError, TypeError):
                                timestamp_key = None

                            if event_owner_team_id == home_team_id:
                                if timestamp_key and timestamp_key in penalty_times:
                                    other_penalty = penalty_times[timestamp_key]
                                    if other_penalty["team"] == "away":
                                        penalty_times.pop(timestamp_key)
                                        continue

                                away_pp_opp += 1
                                if timestamp_key:
                                    penalty_times[timestamp_key] = {"team": "home"}
                            elif event_owner_team_id == away_team_id:
                                if timestamp_key and timestamp_key in penalty_times:
                                    other_penalty = penalty_times[timestamp_key]
                                    if other_penalty["team"] == "home":
                                        penalty_times.pop(timestamp_key)
                                        continue

                                home_pp_opp += 1
                                if timestamp_key:
                                    penalty_times[timestamp_key] = {"team": "away"}

                logger.debug(f"Calculated PP opportunities from play-by-play: home={home_pp_opp}, away={away_pp_opp}")
                return home_pp_opp, away_pp_opp
            except Exception as e:
                logger.error(f"Error calculating power play opportunities for game {game_id}: {e}", exc_info=True)
                return 0, 0

        # First, try to get power play opportunities directly from boxscore team stats
        home_pp_opp = None
        away_pp_opp = None

        # Check team-level stats first
        for field_name in [
            "powerPlayOpportunities",
            "powerPlayOpps",
            "ppOpportunities",
            "ppOpps",
            "powerPlayOps",
            "ppOpportunities",
        ]:
            if field_name in home_team:
                val = home_team.get(field_name)
                if val is not None and val != "":
                    home_pp_opp = val
            if field_name in away_team:
                val = away_team.get(field_name)
                if val is not None and val != "":
                    away_pp_opp = val
            if home_pp_opp is not None and away_pp_opp is not None:
                break

        # Check teamStats.teamSkaterStats (NHL API structure)
        if home_pp_opp is None or away_pp_opp is None:
            home_stats = home_team.get("teamStats", {})
            away_stats = away_team.get("teamStats", {})
            home_skater_stats = (
                home_stats.get("teamSkaterStats", {}) if home_stats else {}
            )
            away_skater_stats = (
                away_stats.get("teamSkaterStats", {}) if away_stats else {}
            )

            if home_skater_stats:
                for field_name in [
                    "powerPlayOpportunities",
                    "powerPlayOpps",
                    "ppOpportunities",
                ]:
                    if field_name in home_skater_stats:
                        val = home_skater_stats.get(field_name)
                        if val is not None and val != "":
                            home_pp_opp = val
                            break
            if away_skater_stats:
                for field_name in [
                    "powerPlayOpportunities",
                    "powerPlayOpps",
                    "ppOpportunities",
                ]:
                    if field_name in away_skater_stats:
                        val = away_skater_stats.get(field_name)
                        if val is not None and val != "":
                            away_pp_opp = val
                            break

            # Also check teamStats directly (fallback)
            if home_pp_opp is None and home_stats:
                for field_name in [
                    "powerPlayOpportunities",
                    "powerPlayOpps",
                    "ppOpportunities",
                ]:
                    if field_name in home_stats:
                        val = home_stats.get(field_name)
                        if val is not None and val != "":
                            home_pp_opp = val
                            break
            if away_pp_opp is None and away_stats:
                for field_name in [
                    "powerPlayOpportunities",
                    "powerPlayOpps",
                    "ppOpportunities",
                ]:
                    if field_name in away_stats:
                        val = away_stats.get(field_name)
                        if val is not None and val != "":
                            away_pp_opp = val
                            break

        # If not found in team stats, try to calculate from play-by-play
        if home_pp_opp is None or away_pp_opp is None:
            logger.debug(f"PP opportunities not in boxscore for game {game_id}, calculating from play-by-play")
            (
                calculated_home_pp_opp,
                calculated_away_pp_opp,
            ) = await calculate_pp_opportunities_from_plays(
                game_id, home_team_id, away_team_id
            )

            if home_pp_opp is None:
                home_pp_opp = calculated_home_pp_opp
            if away_pp_opp is None:
                away_pp_opp = calculated_away_pp_opp
        else:
            logger.debug(f"Using PP opportunities from boxscore for game {game_id}: home={home_pp_opp}, away={away_pp_opp}")

        # Ensure we have valid integers
        home_pp_opp = int(home_pp_opp) if home_pp_opp is not None else 0
        away_pp_opp = int(away_pp_opp) if away_pp_opp is not None else 0

        # Calculate PP percentage (only if we have opportunities)
        home_pp_pct = (
            round((home_pp_goals / home_pp_opp * 100), 1) if home_pp_opp > 0 else 0.0
        )
        away_pp_pct = (
            round((away_pp_goals / away_pp_opp * 100), 1) if away_pp_opp > 0 else 0.0
        )

        stats = {
            "shots": {
                "home": int(home_shots) if home_shots else 0,
                "away": int(away_shots) if away_shots else 0,
            },
            "hits": {"home": home_hits, "away": away_hits},
            "faceoff_win_pct": {"home": home_fo_pct, "away": away_fo_pct},
            "penalty_minutes": {"home": home_pim, "away": away_pim},
            "power_play_pct": {"home": home_pp_pct, "away": away_pp_pct},
            "power_play_opportunities": {"home": home_pp_opp, "away": away_pp_opp},
            "blocked_shots": {"home": home_blocked, "away": away_blocked},
            "takeaways": {"home": home_takeaways, "away": away_takeaways},
            "giveaways": {"home": home_giveaways, "away": away_giveaways},
        }

        return {
            "game_id": game_id,
            "home_team": {
                "name": home_team_name,
                "logo": home_team_logo,
                "abbrev": home_team_abbrev,
            },
            "away_team": {
                "name": away_team_name,
                "logo": away_team_logo,
                "abbrev": away_team_abbrev,
            },
            "stats": stats,
        }
    except Exception as e:
        logger.error(f"Error fetching game stats for game {game_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching game stats: {str(e)}"
        )


@router.get("/{game_id}/player-stats")
async def get_player_stats(game_id: str):
    """Get individual player statistics for both teams"""
    try:
        boxscore = await fetch_nhl_boxscore(game_id)
        if not boxscore:
            raise HTTPException(
                status_code=404,
                detail=f"Game {game_id} not found or boxscore unavailable",
            )

        home_team = boxscore.get("homeTeam", {})
        away_team = boxscore.get("awayTeam", {})

        # Extract team info
        home_team_name = home_team.get("commonName", {}).get("default", "")
        away_team_name = away_team.get("commonName", {}).get("default", "")
        home_team_logo = home_team.get("logo", "")
        away_team_logo = away_team.get("logo", "")

        # Get player stats
        player_stats = boxscore.get("playerByGameStats", {})
        home_players_raw = player_stats.get("homeTeam", {})
        away_players_raw = player_stats.get("awayTeam", {})

        r = get_redis()

        # Helper function to format player name
        def format_player_name(first_name: str, last_name: str) -> str:
            if not first_name or not last_name:
                return last_name or first_name or "Unknown"
            return f"{first_name} {last_name}"

        # Helper function to process skater stats
        async def process_skater(player_data: dict, team: str) -> dict:
            player_id = player_data.get("playerId")
            if not player_id:
                return None

            # Get player name
            player_name_obj = player_data.get("name", {})
            first_name = (
                player_name_obj.get("default", "").split()[0]
                if player_name_obj.get("default")
                else ""
            )
            last_name = (
                " ".join(player_name_obj.get("default", "").split()[1:])
                if player_name_obj.get("default")
                else ""
            )

            # Try to get from player lookup if not available
            if not first_name or not last_name:
                player_name = await get_player_name(player_id, r)
                if player_name:
                    name_parts = player_name.split(" ", 1)
                    first_name = name_parts[0] if len(name_parts) > 0 else ""
                    last_name = name_parts[1] if len(name_parts) > 1 else ""

            formatted_name = format_player_name(first_name, last_name)

            # Get player headshot
            headshot_url = await get_player_headshot(player_id, r)

            # Get position
            position = player_data.get("position", "")

            # Get stats
            pts = player_data.get("points", 0) or 0
            goals = player_data.get("goals", 0) or 0
            assists = player_data.get("assists", 0) or 0
            plus_minus = player_data.get("plusMinus", 0) or 0
            pim = player_data.get("pim", 0) or 0
            sog = player_data.get("shots", 0) or 0
            hits = player_data.get("hits", 0) or 0

            # Get TOI (Time On Ice) - typically in seconds, format as MM:SS
            toi_seconds = (
                player_data.get("toi", 0) or player_data.get("timeOnIce", 0) or 0
            )
            if isinstance(toi_seconds, str):
                if ":" in toi_seconds:
                    try:
                        parts = toi_seconds.split(":")
                        toi_seconds = int(parts[0]) * 60 + int(parts[1])
                    except (ValueError, IndexError):
                        toi_seconds = 0
                else:
                    try:
                        toi_seconds = int(toi_seconds)
                    except (ValueError, TypeError):
                        toi_seconds = 0
            toi_seconds = int(toi_seconds)
            toi_minutes = toi_seconds // 60
            toi_secs = toi_seconds % 60
            toi_formatted = f"{toi_minutes}:{toi_secs:02d}"

            return {
                "player_id": player_id,
                "name": formatted_name,
                "position": position,
                "headshot": headshot_url or "",
                "stats": {
                    "pts": int(pts),
                    "goals": int(goals),
                    "assists": int(assists),
                    "plus_minus": int(plus_minus),
                    "pim": int(pim),
                    "sog": int(sog),
                    "hits": int(hits),
                    "toi": toi_formatted,
                },
            }

        # Helper function to process goalie stats
        async def process_goalie(player_data: dict, team: str) -> dict:
            player_id = player_data.get("playerId")
            if not player_id:
                return None

            # Get player name
            player_name_obj = player_data.get("name", {})
            first_name = (
                player_name_obj.get("default", "").split()[0]
                if player_name_obj.get("default")
                else ""
            )
            last_name = (
                " ".join(player_name_obj.get("default", "").split()[1:])
                if player_name_obj.get("default")
                else ""
            )

            # Try to get from player lookup if not available
            if not first_name or not last_name:
                player_name = await get_player_name(player_id, r)
                if player_name:
                    name_parts = player_name.split(" ", 1)
                    first_name = name_parts[0] if len(name_parts) > 0 else ""
                    last_name = name_parts[1] if len(name_parts) > 1 else ""

            formatted_name = format_player_name(first_name, last_name)

            # Get player headshot
            headshot_url = await get_player_headshot(player_id, r)

            # Get position
            position = player_data.get("position", "G")

            # Get goalie stats - ensure they're integers, not strings
            def safe_int(value, default=0):
                """Safely convert value to int, handling strings and None"""
                if value is None:
                    return default
                if isinstance(value, str):
                    if "/" in value:
                        try:
                            return int(value.split("/")[0])
                        except (ValueError, IndexError):
                            return default
                    else:
                        try:
                            return int(value)
                        except (ValueError, TypeError):
                            return default
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return default

            saves = safe_int(player_data.get("saves"), 0)
            shots = safe_int(player_data.get("shotsAgainst"), 0)
            pp_saves = safe_int(player_data.get("powerPlaySaves"), 0)
            pp_shots = safe_int(player_data.get("powerPlayShotsAgainst"), 0)
            sh_saves = safe_int(player_data.get("shorthandedSaves"), 0)
            sh_shots = safe_int(player_data.get("shorthandedShotsAgainst"), 0)
            pim = safe_int(player_data.get("pim"), 0)

            # Get TOI (Time On Ice) - typically in seconds, format as MM:SS
            toi_seconds = (
                player_data.get("toi", 0) or player_data.get("timeOnIce", 0) or 0
            )
            if isinstance(toi_seconds, str):
                if ":" in toi_seconds:
                    try:
                        parts = toi_seconds.split(":")
                        toi_seconds = int(parts[0]) * 60 + int(parts[1])
                    except (ValueError, IndexError):
                        toi_seconds = 0
                else:
                    try:
                        toi_seconds = int(toi_seconds)
                    except (ValueError, TypeError):
                        toi_seconds = 0
            toi_seconds = int(toi_seconds)
            toi_minutes = toi_seconds // 60
            toi_secs = toi_seconds % 60
            toi_formatted = f"{toi_minutes}:{toi_secs:02d}"

            # Calculate save percentage
            sv_pct = (saves / shots * 100) if shots > 0 else 0.0

            return {
                "player_id": player_id,
                "name": formatted_name,
                "position": position,
                "headshot": headshot_url or "",
                "stats": {
                    "saves_shots": f"{saves}/{shots}",
                    "sv_pct": round(sv_pct, 1),
                    "pp_saves_shots": f"{pp_saves}/{pp_shots}",
                    "sh_saves_shots": f"{sh_saves}/{sh_shots}",
                    "pim": pim,
                    "toi": toi_formatted,
                },
            }

        # Process home team players
        home_skaters = []
        home_goalies = []

        for position_group in ["forwards", "defense"]:
            players = home_players_raw.get(position_group, [])
            for player in players:
                if isinstance(player, dict) and player.get("playerId"):
                    skater_data = await process_skater(player, "home")
                    if skater_data:
                        toi = skater_data.get("stats", {}).get("toi", "0:00")
                        if toi and toi != "0:00":
                            home_skaters.append(skater_data)

        goalies = home_players_raw.get("goalies", [])
        for player in goalies:
            if isinstance(player, dict) and player.get("playerId"):
                goalie_data = await process_goalie(player, "home")
                if goalie_data:
                    toi = goalie_data.get("stats", {}).get("toi", "0:00")
                    if toi and toi != "0:00":
                        home_goalies.append(goalie_data)

        # Process away team players
        away_skaters = []
        away_goalies = []

        for position_group in ["forwards", "defense"]:
            players = away_players_raw.get(position_group, [])
            for player in players:
                if isinstance(player, dict) and player.get("playerId"):
                    skater_data = await process_skater(player, "away")
                    if skater_data:
                        toi = skater_data.get("stats", {}).get("toi", "0:00")
                        if toi and toi != "0:00":
                            away_skaters.append(skater_data)

        goalies = away_players_raw.get("goalies", [])
        for player in goalies:
            if isinstance(player, dict) and player.get("playerId"):
                goalie_data = await process_goalie(player, "away")
                if goalie_data:
                    toi = goalie_data.get("stats", {}).get("toi", "0:00")
                    if toi and toi != "0:00":
                        away_goalies.append(goalie_data)

        # Sort skaters by points (descending), then goals
        home_skaters.sort(
            key=lambda x: (x["stats"]["pts"], x["stats"]["goals"]), reverse=True
        )
        away_skaters.sort(
            key=lambda x: (x["stats"]["pts"], x["stats"]["goals"]), reverse=True
        )

        return {
            "game_id": game_id,
            "home_team": {
                "name": home_team_name,
                "logo": home_team_logo,
                "skaters": home_skaters,
                "goalies": home_goalies,
            },
            "away_team": {
                "name": away_team_name,
                "logo": away_team_logo,
                "skaters": away_skaters,
                "goalies": away_goalies,
            },
        }
    except HTTPException:
        # Re-raise HTTPExceptions (like 404) as-is
        raise
    except Exception as e:
        logger.error(f"Error fetching player stats for game {game_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Error fetching player stats: {str(e)}"
        )


def _get_valid_timestamp(data: dict) -> float:
    """Extract valid timestamp from prediction data, with fallback to current time."""
    timestamp_val = data.get("timestamp")
    ts_val = data.get("ts")

    # Try timestamp first (wall-clock time)
    if timestamp_val:
        try:
            return float(timestamp_val)
        except (ValueError, TypeError):
            pass

    # Fallback to ts (relative time) - but this is relative, not wall-clock
    # For updated_at, we want wall-clock time, so use current time if ts is relative
    if ts_val:
        try:
            ts_float = float(ts_val)
            # If ts is a small number (< 10000), it's likely relative time (0-3600s)
            # Use current time instead
            if ts_float < 10000:
                return time.time()
            # Otherwise assume it's a valid timestamp
            return ts_float
        except (ValueError, TypeError):
            pass

    # Final fallback: current time
    return time.time()


@router.get("/{game_id}/winprob/friendly")
async def get_winprob_friendly(game_id: str):
    """Human-readable win probability with percentages and game score"""
    r = get_redis()
    key = f"pred:{game_id}"
    data = await r.hgetall(key)
    if not data:
        # Check if ingestion is in progress
        ingestion_status = await r.hget(f"ingestion_status:{game_id}", "status")
        if ingestion_status == "in_progress":
            raise HTTPException(
                status_code=202,
                detail="Ingestion in progress. Please wait 60-90 seconds and try again. Check status at GET /v1/games/{game_id}/status",
            )
        # For failed or no ingestion, return a basic response with calculated win probability
        try:
            game_data = await fetch_nhl_play_by_play(game_id)
            if not game_data:
                raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

            # Get basic game info to return a minimal response
            home_team_data = game_data.get("homeTeam", {})
            away_team_data = game_data.get("awayTeam", {})
            home_team = home_team_data.get("commonName", {}).get("default", "Home Team")
            away_team = away_team_data.get("commonName", {}).get("default", "Away Team")
            home_logo = home_team_data.get("logo", "")
            away_logo = away_team_data.get("logo", "")
            home_abbrev = home_team_data.get("abbrev", "")
            away_abbrev = away_team_data.get("abbrev", "")

            game_state = game_data.get("gameState", "")
            is_live = game_state in ["LIVE", "CRIT"]

            # Get scores
            home_score = game_data.get("homeScore", 0) or home_team_data.get("score", 0)
            away_score = game_data.get("awayScore", 0) or away_team_data.get("score", 0)

            # Get period and time
            period = None
            time_in_period = ""
            plays = game_data.get("plays", [])
            if plays:
                for play in reversed(plays):
                    type_code = play.get("typeCode")
                    if type_code not in [520, 516, 517, 524]:
                        time_in_period = play.get("timeInPeriod", "00:00")
                        period = play.get("periodDescriptor", {}).get("number", 1)
                        break

            # Calculate win probability based on current game state
            p_home = calculate_win_probability(
                home_score=int(home_score) if home_score else 0,
                away_score=int(away_score) if away_score else 0,
                game_state=game_state,
                period=period,
                time_in_period=time_in_period,
                plays=plays,
            )
            p_away = 1.0 - p_home

            # Get current situation from Redis state if available
            state_key = f"state:{game_id}"
            state = await r.hgetall(state_key)
            strength = state.get("strength", "EV")
            empty_net_str = state.get("empty_net", "False")
            empty_net = (
                empty_net_str.lower() == "true"
                if isinstance(empty_net_str, str)
                else bool(empty_net_str)
            )
            last_event = state.get("last_event", "Game in progress")
            last_player_id_str = state.get("last_player_id", "")
            last_player_id = (
                int(last_player_id_str)
                if last_player_id_str and last_player_id_str != "None"
                else None
            )

            # Look up player name if available
            last_player_name = None
            if last_player_id:
                last_player_name = await get_player_name(last_player_id, r)

            # Format strength
            strength_names = {
                "EV": "Even Strength (5v5)",
                "PP": "Power Play",
                "PK": "Shorthanded",
                "EN": "Empty Net",
                "ENPP": "Empty Net + Power Play",
                "ENPK": "Empty Net + Shorthanded",
                "SH": "Shorthanded",
            }
            situation_parts = [strength_names.get(strength, strength)]
            if empty_net and strength not in ["EN", "ENPP", "ENPK"]:
                situation_parts.append("Empty Net")
            situation_description = (
                " + ".join(situation_parts)
                if len(situation_parts) > 1
                else situation_parts[0]
            )

            # Determine favorite
            if p_home > 0.55:
                favorite = f"{home_team} (favored)"
            elif p_away > 0.55:
                favorite = f"{away_team} (favored)"
            else:
                favorite = "Close game"

            # Return basic response with calculated win probability
            return {
                "game": {
                    "id": game_id,
                    "matchup": f"{away_team} @ {home_team}",
                    "is_live": is_live,
                    "game_state": game_state,
                    "period": period,
                    "time_in_period": time_in_period,
                    "favorite": favorite,
                },
                "score": {
                    "home": {
                        "team": home_team,
                        "goals": int(home_score) if home_score else 0,
                        "logo": home_logo,
                        "abbrev": home_abbrev,
                    },
                    "away": {
                        "team": away_team,
                        "goals": int(away_score) if away_score else 0,
                        "logo": away_logo,
                        "abbrev": away_abbrev,
                    },
                },
                "win_probability": {
                    home_team: round(p_home * 100, 1),
                    away_team: round(p_away * 100, 1),
                    "summary": f"{home_team}: {round(p_home * 100, 1)}% | {away_team}: {round(p_away * 100, 1)}%",
                },
                "current_situation": {
                    "strength": situation_description,
                    "empty_net": empty_net,
                    "last_event": last_event,
                    "last_player": last_player_name,
                },
                "favorite": favorite,
                "spread": None,
                "over_under": None,
                "confidence": "Low",  # Basic calculation, not from model
            }
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=404,
                detail=f"No prediction yet for game {game_id}. Start ingestion with POST /v1/games/{game_id}/start",
            )

    try:
        # Get current game time from NHL API
        game_data = await fetch_nhl_play_by_play(game_id)
        game_state = ""
        period = None
        time_in_period = ""
        plays = []

        # Get current score from Redis state
        state_key = f"state:{game_id}"
        state = await r.hgetall(state_key)

        home_score = int(state.get("home_score", 0))
        away_score = int(state.get("away_score", 0))

        if game_data:
            game_state = game_data.get("gameState", "")
            period_descriptor = game_data.get("periodDescriptor", {})
            period = period_descriptor.get("number", 1)

            # For live games, get current scores from NHL API (more up-to-date than Redis)
            if game_state in ["LIVE", "CRIT"]:
                home_team_data = game_data.get("homeTeam", {})
                away_team_data = game_data.get("awayTeam", {})
                api_home_score = game_data.get("homeScore") or home_team_data.get(
                    "score", 0
                )
                api_away_score = game_data.get("awayScore") or away_team_data.get(
                    "score", 0
                )

                if api_home_score is not None and api_away_score is not None:
                    home_score = int(api_home_score)
                    away_score = int(api_away_score)
                    # Update Redis state with latest scores
                    await r.hset(state_key, "home_score", str(home_score))
                    await r.hset(state_key, "away_score", str(away_score))

            # Get the most recent play to get current time
            plays = game_data.get("plays", [])
            if plays:
                for play in reversed(plays):
                    type_code = play.get("typeCode")
                    if type_code not in [520, 516, 517, 524]:
                        time_in_period = play.get("timeInPeriod", "00:00")
                        period = play.get("periodDescriptor", {}).get("number", period)
                        break

        # Validate prediction data before using it
        p_home = None
        p_away = None

        # Try to get prediction from Redis data
        p_home_win_val = data.get("p_home_win")
        if p_home_win_val:
            try:
                p_home = float(p_home_win_val)
                # Validate probability is in valid range
                if 0.0 <= p_home <= 1.0:
                    p_away = 1.0 - p_home
                else:
                    # Invalid range, will calculate below
                    p_home = None
            except (ValueError, TypeError):
                # Invalid prediction data, will calculate below
                pass

        # If prediction data is invalid or missing, calculate from game state
        if p_home is None:
            p_home = calculate_win_probability(
                home_score=home_score,
                away_score=away_score,
                game_state=game_state,
                period=period,
                time_in_period=time_in_period,
                plays=plays,
            )
            p_away = 1.0 - p_home
        strength = state.get("strength", "EV")
        empty_net_str = state.get("empty_net", "False")
        empty_net = (
            empty_net_str.lower() == "true"
            if isinstance(empty_net_str, str)
            else bool(empty_net_str)
        )
        last_event = state.get("last_event", "Unknown")
        last_player_id_str = state.get("last_player_id", "")
        last_player_id = (
            int(last_player_id_str)
            if last_player_id_str and last_player_id_str != "None"
            else None
        )

        # Look up player name with Redis caching
        last_player_name = None
        if last_player_id:
            last_player_name = await get_player_name(last_player_id, r)

        # Get team names and logos from cache or NHL API
        home_team = await r.get(f"game:{game_id}:home_team")
        away_team = await r.get(f"game:{game_id}:away_team")
        home_logo = await r.get(f"game:{game_id}:home_logo")
        away_logo = await r.get(f"game:{game_id}:away_logo")
        home_abbrev = await r.get(f"game:{game_id}:home_abbrev")
        away_abbrev = await r.get(f"game:{game_id}:away_abbrev")

        if (
            not home_team
            or not away_team
            or not home_logo
            or not away_logo
            or not home_abbrev
            or not away_abbrev
        ):
            # Cache miss - fetch from NHL API
            try:
                game_data = await fetch_nhl_play_by_play(game_id)
                if game_data:
                    away_team_data = game_data.get("awayTeam", {})
                    home_team_data = game_data.get("homeTeam", {})
                    away_team = away_team_data.get("commonName", {}).get(
                        "default", "Away Team"
                    )
                    home_team = home_team_data.get("commonName", {}).get(
                        "default", "Home Team"
                    )
                    away_logo = away_team_data.get("logo", "")
                    home_logo = home_team_data.get("logo", "")
                    away_abbrev = away_team_data.get("abbrev", "")
                    home_abbrev = home_team_data.get("abbrev", "")
                    # Cache team names and logos for 24 hours
                    await r.setex(f"game:{game_id}:home_team", 86400, home_team)
                    await r.setex(f"game:{game_id}:away_team", 86400, away_team)
                    if home_logo:
                        await r.setex(f"game:{game_id}:home_logo", 86400, home_logo)
                    if away_logo:
                        await r.setex(f"game:{game_id}:away_logo", 86400, away_logo)
                    if home_abbrev:
                        await r.setex(f"game:{game_id}:home_abbrev", 86400, home_abbrev)
                    if away_abbrev:
                        await r.setex(f"game:{game_id}:away_abbrev", 86400, away_abbrev)
                else:
                    away_team = "Away Team"
                    home_team = "Home Team"
                    away_logo = ""
                    home_logo = ""
                    away_abbrev = ""
                    home_abbrev = ""
            except Exception:
                # Fallback to hardcoded for known games
                if game_id == "2024020589":
                    home_team = "Capitals"
                    away_team = "Bruins"
                    home_abbrev = "WSH"
                    away_abbrev = "BOS"
                elif game_id == "TEST_GAME":
                    home_team = "Home Team"
                    away_team = "Away Team"
                    home_abbrev = "HOM"
                    away_abbrev = "AWY"
                else:
                    home_team = "Home Team"
                    away_team = "Away Team"
                    home_abbrev = ""
                    away_abbrev = ""
                away_logo = ""
                home_logo = ""
                # Cache fallback values
                await r.setex(f"game:{game_id}:home_team", 86400, home_team)
                await r.setex(f"game:{game_id}:away_team", 86400, away_team)
                if home_abbrev:
                    await r.setex(f"game:{game_id}:home_abbrev", 86400, home_abbrev)
                if away_abbrev:
                    await r.setex(f"game:{game_id}:away_abbrev", 86400, away_abbrev)

        # Format strength with empty net and shorthanded indicators
        strength_names = {
            "EV": "Even Strength (5v5)",
            "PP": "Power Play",
            "PK": "Shorthanded",
            "EN": "Empty Net",
            "ENPP": "Empty Net + Power Play",
            "ENPK": "Empty Net + Shorthanded",
            "SH": "Shorthanded",
        }

        # Build situation description
        situation_parts = [strength_names.get(strength, strength)]
        if empty_net and strength not in ["EN", "ENPP", "ENPK"]:
            situation_parts.append("Empty Net")
        situation_description = (
            " + ".join(situation_parts)
            if len(situation_parts) > 1
            else situation_parts[0]
        )

        # Determine favorite
        if p_home > 0.55:
            favorite = f"{home_team} (favored)"
        elif p_away > 0.55:
            favorite = f"{away_team} (favored)"
        else:
            favorite = "Close game"

        # Get spread (mock for now - can be replaced with real betting API)
        spread_value = None
        spread_favorite = None
        over_under = None

        return {
            "game": {
                "id": game_id,
                "matchup": f"{away_team} @ {home_team}",
                "favorite": favorite,
                "game_state": game_state,
                "period": period,
                "time_in_period": time_in_period,
                "is_live": game_state in ["LIVE", "CRIT"],
                "spread": spread_value,
                "spread_favorite": spread_favorite,
                "over_under": over_under,
            },
            "score": {
                "home": {
                    "team": home_team,
                    "abbrev": home_abbrev,
                    "goals": home_score,
                    "logo": home_logo or "",
                },
                "away": {
                    "team": away_team,
                    "abbrev": away_abbrev,
                    "goals": away_score,
                    "logo": away_logo or "",
                },
                "display": f"{home_team} {home_score} - {away_score} {away_team}",
            },
            "current_situation": {
                "strength": situation_description,
                "empty_net": empty_net,
                "last_event": last_event,
                "last_player": last_player_name,
            },
            "win_probability": {
                home_team: round(p_home * 100, 1),
                away_team: round(p_away * 100, 1),
                "summary": f"{home_team}: {round(p_home * 100, 1)}% | {away_team}: {round(p_away * 100, 1)}%",
            },
            "confidence": "High"
            if max(p_home, p_away) > 0.7
            else "Medium"
            if max(p_home, p_away) > 0.6
            else "Low",
            # Use timestamp (wall-clock time) if available, otherwise fall back to ts (relative time)
            # model_svc now stores both ts (relative) and timestamp (wall-clock)
            "updated_at": _get_valid_timestamp(data),
        }
    except HTTPException:
        raise
    except Exception as e:
        # Log the actual error for debugging
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving win probability: {str(e)}"
        )
