"""NHL API client functions for fetching game data."""

import json
import httpx
from redis.asyncio import Redis

NHL_API_BASE = "https://api-web.nhle.com/v1"


async def fetch_nhl_play_by_play(game_id: str) -> dict:
    """Fetch play-by-play data directly from NHL API"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play"
            )
            if response.status_code == 200:
                return response.json()
            else:
                print(
                    f"[gateway] NHL API error {response.status_code} for game {game_id}"
                )
                return None
    except Exception as e:
        print(f"[gateway] Error fetching NHL play-by-play for game {game_id}: {e}")
        return None


async def fetch_nhl_boxscore(game_id: str) -> dict:
    """Fetch boxscore data directly from NHL API"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{NHL_API_BASE}/gamecenter/{game_id}/boxscore")
            if response.status_code == 200:
                return response.json()
            else:
                print(
                    f"[gateway] NHL API boxscore error {response.status_code} for game {game_id}"
                )
                return None
    except Exception as e:
        print(f"[gateway] Error fetching NHL boxscore for game {game_id}: {e}")
        return None


async def fetch_team_standings(redis: Redis = None) -> dict:
    """Fetch team standings/records from NHL API and cache in Redis.
    Returns a dict mapping team abbreviation to {wins, losses, ot_losses}
    """
    try:
        # Check cache first (cache for 1 hour)
        if redis:
            cached = await redis.get("team_standings_cache")
            if cached:
                return json.loads(cached)

        # Fetch from standings endpoint (follows redirects automatically)
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(f"{NHL_API_BASE}/standings/now")
            if response.status_code == 200:
                data = response.json()

                # The API returns { "standings": [...] }
                standings = data.get("standings", [])
                standings_data = {}

                # Process standings - map by team abbreviation since there's no team ID
                for team_data in standings:
                    if isinstance(team_data, dict):
                        team_abbrev = team_data.get("teamAbbrev", {}).get("default", "")
                        wins = team_data.get("wins", 0)
                        losses = team_data.get("losses", 0)
                        ot_losses = team_data.get("otLosses", 0)

                        if team_abbrev:
                            standings_data[team_abbrev] = {
                                "wins": int(wins),
                                "losses": int(losses),
                                "ot_losses": int(ot_losses),
                            }

                # Cache for 1 hour if we got data
                if redis and standings_data:
                    await redis.setex(
                        "team_standings_cache", 3600, json.dumps(standings_data)
                    )

                return standings_data
            else:
                print(f"[gateway] Standings API error {response.status_code}")
                return {}
    except Exception as e:
        print(f"[gateway] Error fetching team standings: {e}")
        return {}


async def fetch_nhl_daily_schedule(date: str = None) -> dict:
    """Fetch daily schedule from NHL API (date format: YYYY-MM-DD)"""
    try:
        if date is None:
            # Get today's date
            from datetime import date as dt_date

            date = dt_date.today().strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try the schedule endpoint with date
            response = await client.get(f"{NHL_API_BASE}/schedule/{date}")
            if response.status_code == 200:
                data = response.json()
                # The API returns gameWeek array with dates
                if isinstance(data, dict) and "gameWeek" in data:
                    for week in data.get("gameWeek", []):
                        if week.get("date") == date:
                            return week
                    # If no exact match, return first day's games
                    if data.get("gameWeek"):
                        return data["gameWeek"][0]
                return data
            print(f"[gateway] NHL API schedule error {response.status_code} for {date}")
            return {"games": [], "date": date}
    except Exception as e:
        print(f"[gateway] Error fetching NHL schedule for {date}: {e}")
        import traceback

        traceback.print_exc()
        return {"games": [], "date": date}
