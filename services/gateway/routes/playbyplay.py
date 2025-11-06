"""Play-by-play API routes."""

import asyncio
import json
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from nhl_api import fetch_nhl_play_by_play
from player_utils import (
    get_player_name,
    get_player_headshot,
    get_player_names_batch,
    get_player_headshots_batch,
)
from event_helpers import (
    EVENT_TYPE_MAPPING,
    calculate_strength_from_situation,
    calculate_goal_distance,
    format_goal_description,
    format_shot_description,
    format_penalty_description,
    get_game_situation,
    parse_situation_code,
)

router = APIRouter(prefix="/v1/games", tags=["playbyplay"])


# Helper function to get app state (will be injected)
def get_redis() -> Redis:
    """Get Redis instance from app state."""
    from main import app

    return app.state.redis


async def _refresh_playbyplay_cache(game_id: str, r: Redis):
    """Background task to refresh play-by-play cache for live games."""
    try:
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            return
        # Cache refresh logic here - simplified for now
        print(f"[gateway] Refreshed play-by-play cache for {game_id}")
    except Exception as e:
        print(f"[gateway] Error refreshing play-by-play cache for {game_id}: {e}")


@router.get("/{game_id}/playbyplay")
async def get_playbyplay(game_id: str, limit: int = 30):
    """Get play-by-play events for a game directly from NHL API with caching"""
    r = get_redis()

    try:
        # Check cache first
        cache_key = f"playbyplay:{game_id}"
        if r:
            cached = await r.get(cache_key)
            if cached:
                cached_data = json.loads(cached)
                game_state = cached_data.get("game_state", "")
                if game_state in ["OFF", "FINAL"]:
                    events = cached_data.get("events", [])
                    if events:
                        crucial_events = [
                            e
                            for e in events
                            if e.get("event_type") in ["GOAL", "PENALTY"]
                        ]
                        crucial_events.sort(
                            key=lambda x: x.get("timestamp", 0), reverse=True
                        )
                        cached_data["events"] = crucial_events
                    return cached_data
                else:
                    cache_age_key = f"playbyplay_cache_age:{game_id}"
                    cache_age = await r.get(cache_age_key)
                    current_time = time.time()

                    if cache_age:
                        try:
                            age = current_time - float(cache_age)
                            if age > 5:
                                pass  # Fetch fresh data
                            else:
                                asyncio.create_task(
                                    _refresh_playbyplay_cache(game_id, r)
                                )
                                response = JSONResponse(content=cached_data)
                                response.headers["Cache-Control"] = (
                                    "no-cache, no-store, must-revalidate, max-age=0"
                                )
                                response.headers["Pragma"] = "no-cache"
                                response.headers["Expires"] = "0"
                                return response
                        except (ValueError, TypeError):
                            pass

        # Fetch play-by-play directly from NHL API
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        # Get team info
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        home_team_common = (
            game_data.get("homeTeam", {})
            .get("commonName", {})
            .get("default", "Home Team")
        )
        away_team_common = (
            game_data.get("awayTeam", {})
            .get("commonName", {})
            .get("default", "Away Team")
        )

        # Get full team names for penalties
        home_place_name = (
            game_data.get("homeTeam", {}).get("placeName", {}).get("default", "")
        )
        away_place_name = (
            game_data.get("awayTeam", {}).get("placeName", {}).get("default", "")
        )
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

        home_team_logo = game_data.get("homeTeam", {}).get("logo", "")
        away_team_logo = game_data.get("awayTeam", {}).get("logo", "")

        # Cache team names
        await r.setex(f"game:{game_id}:home_team", 86400, home_team_common)
        await r.setex(f"game:{game_id}:away_team", 86400, away_team_common)
        await r.setex(f"game:{game_id}:home_team_full", 86400, home_team_full)
        await r.setex(f"game:{game_id}:away_team_full", 86400, away_team_full)
        await r.setex(f"game:{game_id}:home_logo", 86400, home_team_logo)
        await r.setex(f"game:{game_id}:away_logo", 86400, away_team_logo)

        # Get plays from API
        plays = game_data.get("plays", [])
        if not plays:
            return {
                "game_id": game_id,
                "home_team": home_team_common,
                "away_team": away_team_common,
                "events": [],
                "max_period": 1,
                "game_state": game_data.get("gameState", ""),
            }

        # Get game start time for timestamp calculation
        game_start_str = game_data.get("startTimeUTC", "")
        game_start_ts = None
        if game_start_str:
            game_start = datetime.fromisoformat(game_start_str.replace("Z", "+00:00"))
            game_start_ts = game_start.timestamp()

        # Event type mapping
        type_mapping = EVENT_TYPE_MAPPING

        # Collect all unique player IDs for batch lookup
        player_ids = set()
        processed_plays = []

        for play in plays:
            type_code = play.get("typeCode")
            # Skip only certain administrative events, but keep period-end events
            if type_code in [
                516,
                524,
            ]:  # Skip stoppage, game-end (but keep period-end 517)
                continue

            # Include period-end events (517) and period-start events (520) for display
            if type_code not in [
                502,
                503,
                504,
                505,
                506,
                507,
                508,
                509,
                535,
                536,
                517,
                520,
            ]:
                continue

            mapped_type = type_mapping.get(type_code, "SHOT")
            details = play.get("details", {})

            # Extract player IDs based on event type
            if mapped_type == "GOAL":
                pid = details.get("scoringPlayerId")
                if pid:
                    player_ids.add(pid)
                assist1 = details.get("assist1PlayerId")
                if assist1:
                    player_ids.add(assist1)
                assist2 = details.get("assist2PlayerId")
                if assist2:
                    player_ids.add(assist2)
            elif mapped_type == "PENALTY":
                pid = details.get("committedByPlayerId")
                if pid:
                    player_ids.add(pid)
                drawn = details.get("drawnByPlayerId")
                if drawn:
                    player_ids.add(drawn)
            elif mapped_type == "SHOT":
                pid = details.get("shootingPlayerId")
                if pid:
                    player_ids.add(pid)
            elif mapped_type == "BLOCK":
                shooting_pid = details.get("shootingPlayerId")
                if shooting_pid:
                    player_ids.add(shooting_pid)
                blocking_pid = details.get("playerId") or details.get(
                    "blockingPlayerId"
                )
                if blocking_pid:
                    player_ids.add(blocking_pid)
            elif mapped_type == "HIT":
                pid = details.get("hittingPlayerId")
                if pid:
                    player_ids.add(pid)
            elif mapped_type == "FACEOFF":
                pid = details.get("winningPlayerId")
                if pid:
                    player_ids.add(pid)
            elif mapped_type in ["GIVEAWAY", "TAKEAWAY"]:
                pid = details.get("playerId")
                if pid:
                    player_ids.add(pid)

            processed_plays.append(play)

        # Batch fetch player names and headshots
        player_names = (
            await get_player_names_batch(list(player_ids), r) if player_ids else {}
        )
        player_headshots = (
            await get_player_headshots_batch(list(player_ids), r) if player_ids else {}
        )

        # Track score progression
        home_score = 0
        away_score = 0
        events = []
        period1_baseline = None

        # Process events in chronological order
        for play in processed_plays:
            type_code = play.get("typeCode")
            mapped_type = type_mapping.get(type_code, "SHOT")
            details = play.get("details", {})

            # Determine team
            event_owner_id = details.get("eventOwnerTeamId")
            if event_owner_id == home_team_id:
                team = "HOME"
            elif event_owner_id == away_team_id:
                team = "AWAY"
            else:
                if mapped_type == "GOAL":
                    team = (
                        "AWAY"
                        if play.get("homeTeamDefendingSide") == "right"
                        else "HOME"
                    )
                else:
                    team = (
                        "HOME"
                        if play.get("homeTeamDefendingSide") == "right"
                        else "AWAY"
                    )

            # Get player info
            player_id = None
            assist1_player_id = None
            assist2_player_id = None
            assist1_name = None
            assist2_name = None
            player_headshot = None

            if mapped_type == "GOAL":
                player_id = details.get("scoringPlayerId")
                assist1_player_id = details.get("assist1PlayerId")
                assist2_player_id = details.get("assist2PlayerId")
                player_name = player_names.get(player_id) if player_id else None
                player_headshot = player_headshots.get(player_id) if player_id else None
                assist1_name = (
                    player_names.get(assist1_player_id) if assist1_player_id else None
                )
                assist2_name = (
                    player_names.get(assist2_player_id) if assist2_player_id else None
                )

                if player_id and not player_name:
                    player_name = await get_player_name(player_id, r)
                if player_id and not player_headshot:
                    player_headshot = await get_player_headshot(player_id, r)
                if assist1_player_id and not assist1_name:
                    assist1_name = await get_player_name(assist1_player_id, r)
                if assist2_player_id and not assist2_name:
                    assist2_name = await get_player_name(assist2_player_id, r)

            elif mapped_type == "PENALTY":
                player_id = details.get("committedByPlayerId")
                desc_key = details.get("descKey", "").lower()

                is_bench_penalty = False
                if not player_id or player_id == 0:
                    is_bench_penalty = True
                elif "bench" in desc_key:
                    is_bench_penalty = True

                if is_bench_penalty:
                    player_id = None
                    player_name = home_team_full if team == "HOME" else away_team_full
                    player_headshot = (
                        home_team_logo if team == "HOME" else away_team_logo
                    )
                else:
                    player_name = player_names.get(player_id) if player_id else None
                    player_headshot = (
                        player_headshots.get(player_id) if player_id else None
                    )
                    if player_id and not player_name:
                        player_name = await get_player_name(player_id, r)
                    if player_id and not player_headshot:
                        player_headshot = await get_player_headshot(player_id, r)
            elif mapped_type in [
                "SHOT",
                "BLOCK",
                "HIT",
                "FACEOFF",
                "GIVEAWAY",
                "TAKEAWAY",
            ]:
                if mapped_type == "SHOT":
                    player_id = details.get("shootingPlayerId")
                elif mapped_type == "BLOCK":
                    player_id = (
                        details.get("playerId")
                        or details.get("blockingPlayerId")
                        or details.get("shootingPlayerId")
                    )
                elif mapped_type == "HIT":
                    player_id = details.get("hittingPlayerId")
                elif mapped_type == "FACEOFF":
                    player_id = details.get("winningPlayerId")
                elif mapped_type in ["GIVEAWAY", "TAKEAWAY"]:
                    player_id = details.get("playerId")

                player_name = player_names.get(player_id) if player_id else None
                player_headshot = player_headshots.get(player_id) if player_id else None
                if player_id and not player_name:
                    player_name = await get_player_name(player_id, r)
                if player_id and not player_headshot:
                    player_headshot = await get_player_headshot(player_id, r)
            else:
                player_name = None
                player_headshot = None

            # Parse situation code
            situation = play.get("situationCode", "1555")
            home_skaters, away_skaters = parse_situation_code(situation)

            # Calculate strength
            strength_from_api = None
            if mapped_type == "GOAL":
                strength_from_api = (
                    play.get("strength")
                    or play.get("strengthCode")
                    or play.get("strengthState")
                )
                if not strength_from_api:
                    strength_from_api = (
                        details.get("strength")
                        or details.get("strengthCode")
                        or details.get("strengthState")
                    )
                if not strength_from_api:
                    is_power_play = details.get("powerPlay") or details.get(
                        "isPowerPlay"
                    )
                    is_shorthanded = (
                        details.get("shortHanded")
                        or details.get("isShortHanded")
                        or details.get("shorthanded")
                    )
                    if is_power_play:
                        strength_from_api = "PPG"
                    elif is_shorthanded:
                        strength_from_api = "SHG"

            if not strength_from_api or mapped_type != "GOAL":
                strength = calculate_strength_from_situation(
                    situation, team, home_skaters, away_skaters
                )
                empty_net = away_skaters == 6 or home_skaters == 6
            else:
                if strength_from_api in ["PPG", "PP"]:
                    strength = "PP"
                elif strength_from_api in ["SHG", "SH"]:
                    strength = "SH"
                else:
                    strength = "EV"
                empty_net = away_skaters == 6 or home_skaters == 6

            # Calculate timestamp
            time_in_period = play.get("timeInPeriod", "00:00")
            period = play.get("periodDescriptor", {}).get("number", 1)

            if game_start_ts:
                try:
                    minutes, seconds = map(int, time_in_period.split(":"))
                    elapsed_seconds = minutes * 60 + seconds
                    period_offset = (period - 1) * 1200
                    timestamp = game_start_ts + period_offset + elapsed_seconds
                except (ValueError, TypeError):
                    timestamp = time.time()
            else:
                timestamp = time.time()

            # Format event description
            event_desc = mapped_type

            if mapped_type == "PERIOD_END":
                # Format period end message
                period_num = play.get("periodDescriptor", {}).get("number", period)
                if period_num == 1:
                    event_desc = "End of 1st Period"
                elif period_num == 2:
                    event_desc = "End of 2nd Period"
                elif period_num == 3:
                    event_desc = "End of 3rd Period"
                elif period_num == 4:
                    event_desc = "End of Overtime"
                else:
                    event_desc = f"End of {period_num}th Period"
                # Period end events don't have a team or player
                team = None
                player_name = None
                player_id = None
                player_headshot = None
                strength = None
                empty_net = False
            elif mapped_type == "PERIOD_START":
                # Format period start message
                period_num = play.get("periodDescriptor", {}).get("number", period)
                if period_num == 1:
                    event_desc = "Start of 1st Period"
                elif period_num == 2:
                    event_desc = "Start of 2nd Period"
                elif period_num == 3:
                    event_desc = "Start of 3rd Period"
                elif period_num == 4:
                    event_desc = "Start of Overtime"
                else:
                    event_desc = f"Start of {period_num}th Period"
                # Period start events don't have a team or player
                team = None
                player_name = None
                player_id = None
                player_headshot = None
                strength = None
                empty_net = False
            elif mapped_type == "SHOT":
                shot_type = details.get("shotType", "").lower()
                was_blocked = details.get("wasBlocked", False)
                was_saved = (
                    details.get("wasOnGoal", False) if not was_blocked else False
                )
                event_desc = format_shot_description(shot_type, was_saved, was_blocked)

            elif mapped_type == "BLOCK":
                blocking_player_id = details.get("playerId") or details.get(
                    "blockingPlayerId"
                )
                shooting_player_id = details.get("shootingPlayerId")

                blocking_player_name = None
                if blocking_player_id:
                    blocking_player_name = player_names.get(blocking_player_id)
                    if not blocking_player_name:
                        blocking_player_name = await get_player_name(
                            blocking_player_id, r
                        )

                shooting_player_name = None
                if shooting_player_id:
                    shooting_player_name = player_names.get(shooting_player_id)
                    if not shooting_player_name:
                        shooting_player_name = await get_player_name(
                            shooting_player_id, r
                        )

                if blocking_player_name and shooting_player_name:
                    event_desc = f"{blocking_player_name} Blocked Shot ({shooting_player_name} shot)"
                elif blocking_player_name:
                    event_desc = f"{blocking_player_name} Blocked Shot"
                elif shooting_player_name:
                    event_desc = f"Blocked Shot ({shooting_player_name} shot)"
                else:
                    event_desc = "Blocked Shot"

                if blocking_player_id:
                    player_id = blocking_player_id
                    player_name = blocking_player_name
                    player_headshot = player_headshots.get(blocking_player_id)
                    if not player_headshot and blocking_player_id:
                        player_headshot = await get_player_headshot(
                            blocking_player_id, r
                        )

            elif mapped_type == "HIT":
                event_desc = "Hit"
            elif mapped_type == "FACEOFF":
                event_desc = "Faceoff Won"
            elif mapped_type == "GIVEAWAY":
                event_desc = "Giveaway"
            elif mapped_type == "TAKEAWAY":
                event_desc = "Takeaway"
            elif mapped_type == "GOAL":
                shot_type = details.get("shotType", "").lower()
                x_coord = details.get("xCoord")
                y_coord = details.get("yCoord")
                distance = calculate_goal_distance(
                    x_coord, y_coord, play, team, period1_baseline
                )
                if distance is not None:
                    period_num = play.get("periodDescriptor", {}).get("number", 1)
                    if period_num == 1 and period1_baseline is None:
                        home_defending_side = play.get("homeTeamDefendingSide", "")
                        if home_defending_side == "right":
                            period1_baseline = {"home_goal_x": 89, "away_goal_x": -89}
                        elif home_defending_side == "left":
                            period1_baseline = {"home_goal_x": -89, "away_goal_x": 89}
                        else:
                            period1_baseline = {"home_goal_x": -89, "away_goal_x": 89}

                game_situation = get_game_situation(home_score, away_score, team)
                assists = []
                if assist1_name:
                    assists.append(assist1_name)
                if assist2_name:
                    assists.append(assist2_name)

                event_desc = format_goal_description(
                    shot_type, distance, game_situation, strength, assists
                )

            elif mapped_type == "PENALTY":
                desc_key = details.get("descKey", "").lower()
                duration = details.get("duration", 0)
                is_too_many_men = (
                    desc_key == "too-many-men" or "too-many-men" in desc_key
                )

                is_bench_penalty_check = False
                committed_by_player_id = details.get("committedByPlayerId")
                if not committed_by_player_id or committed_by_player_id == 0:
                    is_bench_penalty_check = True
                elif "bench" in desc_key:
                    is_bench_penalty_check = True

                event_desc = format_penalty_description(desc_key, duration)

                if is_too_many_men or is_bench_penalty_check:
                    team_name = home_team_full if team == "HOME" else away_team_full
                    player_name = team_name
                    team_logo = home_team_logo if team == "HOME" else away_team_logo
                    player_headshot = team_logo if team_logo else None
                    player_id = None

            # Update score for goals
            if mapped_type == "GOAL":
                if team == "HOME":
                    home_score += 1
                else:
                    away_score += 1

            # Determine final player name
            final_player_name = player_name
            if not final_player_name:
                if player_id:
                    final_player_name = await get_player_name(player_id, r)
                    if not final_player_name:
                        final_player_name = f"Player {player_id}"
                else:
                    if mapped_type == "GOAL":
                        final_player_name = "Unknown Player"
                    elif mapped_type not in ["PENALTY", "PERIOD_END", "PERIOD_START"]:
                        final_player_name = None

            # Skip events that require a player but don't have one (except period events)
            if mapped_type in [
                "HIT",
                "SHOT",
                "BLOCK",
                "FACEOFF",
                "GIVEAWAY",
                "TAKEAWAY",
            ]:
                if not final_player_name or not player_id:
                    continue

            # Ensure event description is never empty
            if not event_desc or event_desc.strip() == "":
                event_desc = mapped_type
            if event_desc == mapped_type and mapped_type not in [
                "PERIOD_END",
                "PERIOD_START",
            ]:
                event_desc = mapped_type.title()

            event_data = {
                "id": f"{game_id}-{play.get('eventId', len(events))}",
                "timestamp": timestamp,
                "event_type": mapped_type,
                "description": event_desc,
                "player": final_player_name,
                "player_id": player_id,
                "player_headshot": player_headshot,
                "team": team,
                "strength": strength,
                "empty_net": empty_net,
                "home_score": home_score,
                "away_score": away_score,
                "period": period,
                "time_in_period": time_in_period,
            }

            # Add assist information for goals
            if mapped_type == "GOAL":
                event_data["assist1"] = assist1_name
                event_data["assist1_id"] = assist1_player_id
                event_data["assist2"] = assist2_name
                event_data["assist2_id"] = assist2_player_id
                event_data["shot_type"] = details.get("shotType", "")
                event_data["goal_number"] = details.get("scoringPlayerTotal", 0)

            # Add penalty details
            if mapped_type == "PENALTY":
                event_data["penalty_type"] = details.get("typeCode", "")
                event_data["penalty_desc"] = details.get("descKey", "")
                event_data["duration"] = details.get("duration", 0)
                drawn_by_id = details.get("drawnByPlayerId")
                if drawn_by_id:
                    drawn_by_name = player_names.get(drawn_by_id)
                    if not drawn_by_name:
                        drawn_by_name = await get_player_name(drawn_by_id, r)
                    event_data["drawn_by"] = drawn_by_name
                    event_data["drawn_by_id"] = drawn_by_id

            events.append(event_data)

        # Determine max period
        max_period = 1
        for play in plays:
            period_descriptor = play.get("periodDescriptor", {})
            period_num = period_descriptor.get("number", 1)
            if period_num > max_period:
                max_period = period_num

        # Check if game is complete
        game_state = game_data.get("gameState", "")
        is_complete = game_state in ["OFF", "FINAL"]

        # Deduplicate events by ID
        seen_ids = set()
        unique_events = []
        for event in events:
            event_id = event.get("id")
            if event_id and event_id not in seen_ids:
                seen_ids.add(event_id)
                unique_events.append(event)
            elif not event_id:
                dedup_key = f"{event.get('timestamp')}-{event.get('event_type')}-{event.get('player_id')}-{event.get('period')}-{event.get('time_in_period')}"
                if dedup_key not in seen_ids:
                    seen_ids.add(dedup_key)
                    event["id"] = f"{game_id}-{len(unique_events)}"
                    unique_events.append(event)
        events = unique_events

        # Sort events by timestamp (most recent first)
        events.sort(
            key=lambda x: (
                x.get("timestamp", 0),
                x.get("period", 0),
                x.get("time_in_period", "00:00"),
            )
        )
        events.reverse()

        # Always return ALL crucial events (GOAL, PENALTY, PERIOD_END) regardless of limit
        crucial_events = [
            e
            for e in events
            if e.get("event_type") in ["GOAL", "PENALTY", "PERIOD_END"]
        ]

        if is_complete:
            all_events = crucial_events
        else:
            non_crucial_events = [
                e
                for e in events
                if e.get("event_type") not in ["GOAL", "PENALTY", "PERIOD_END"]
            ]
            limited_non_crucial = non_crucial_events[:4]
            all_events = crucial_events + limited_non_crucial

        # Sort final result by timestamp descending
        all_events.sort(
            key=lambda x: (x.get("timestamp", 0), x.get("id", "")), reverse=True
        )

        result = {
            "game_id": game_id,
            "home_team": home_team_common,
            "away_team": away_team_common,
            "events": all_events,
            "max_period": max_period,
            "game_state": game_data.get("gameState", ""),
        }

        # Return with cache-busting headers
        response = JSONResponse(content=result)
        response.headers["Cache-Control"] = (
            "no-cache, no-store, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        # Cache the result
        cache_key = f"playbyplay:{game_id}"
        if r:
            game_state = game_data.get("gameState", "")
            cache_ttl = 3600 if game_state in ["OFF", "FINAL"] else 10
            await r.setex(cache_key, cache_ttl, json.dumps(result))
            if game_state not in ["OFF", "FINAL"]:
                cache_age_key = f"playbyplay_cache_age:{game_id}"
                await r.setex(cache_age_key, 10, str(time.time()))

        return response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error fetching play-by-play: {str(e)}"
        )
