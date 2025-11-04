import asyncio
import json
import math
import os
import time
from datetime import datetime

import httpx
import psycopg
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
app = FastAPI(title="GameCast++ Gateway")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    from fastapi.staticfiles import StaticFiles
    
    # Custom static file handler with no-cache headers
    class NoCacheStaticFiles(StaticFiles):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
        
        async def __call__(self, scope, receive, send):
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = dict(message.get("headers", []))
                    # Add no-cache headers
                    headers[b"cache-control"] = b"no-cache, no-store, must-revalidate, max-age=0"
                    headers[b"pragma"] = b"no-cache"
                    headers[b"expires"] = b"0"
                    message["headers"] = list(headers.items())
                await send(message)
            
            await super().__call__(scope, receive, send_wrapper)
    
    app.mount("/static", NoCacheStaticFiles(directory=static_dir), name="static")

# NHL API base URL
NHL_API_BASE = "https://api-web.nhle.com/v1"

async def fetch_nhl_play_by_play(game_id: str) -> dict:
    """Fetch play-by-play data directly from NHL API"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play")
            if response.status_code == 200:
                return response.json()
            else:
                print(f"[gateway] NHL API error {response.status_code} for game {game_id}")
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
                print(f"[gateway] NHL API boxscore error {response.status_code} for game {game_id}")
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
                                "ot_losses": int(ot_losses)
                            }
                
                # Cache for 1 hour if we got data
                if redis and standings_data:
                    await redis.setex("team_standings_cache", 3600, json.dumps(standings_data))
                
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

async def get_player_name(player_id: int, redis: Redis = None) -> str:
    """Get player name from NHL API with Redis caching"""
    if not player_id:
        return None
    
    # Check Redis cache first if available
    if redis:
        cached_name = await redis.get(f"player_name:{player_id}")
        if cached_name:
            return cached_name
    
    try:
        # Use NHL API public endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api-web.nhle.com/v1/player/{player_id}/landing",
                timeout=5.0  # Increased timeout
            )
            if response.status_code == 200:
                data = response.json()
                # Extract player name
                first_name = data.get("firstName", {}).get("default", "")
                last_name = data.get("lastName", {}).get("default", "")
                if first_name and last_name:
                    name = f"{first_name} {last_name}"
                    # Cache in Redis if available
                    if redis:
                        await redis.setex(f"player_name:{player_id}", 86400, name)  # Cache for 24 hours
                    return name
            elif response.status_code == 404:
                print(f"[gateway] Player {player_id} not found in NHL API")
            else:
                print(f"[gateway] NHL API error {response.status_code} for player {player_id}")
    except httpx.TimeoutException:
        print(f"[gateway] Timeout fetching player {player_id}")
    except Exception as e:
        print(f"[gateway] Error fetching player {player_id}: {e}")
    
    # Fallback - return None so caller can handle it
    return None

async def get_player_headshot(player_id: int, redis: Redis = None) -> str:
    """Get player headshot URL from NHL API with Redis caching"""
    if not player_id:
        return None
    
    # Check Redis cache first if available
    if redis:
        cached_headshot = await redis.get(f"player_headshot:{player_id}")
        if cached_headshot:
            return cached_headshot
    
    try:
        # Use NHL API public endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api-web.nhle.com/v1/player/{player_id}/landing",
                timeout=5.0  # Increased timeout
            )
            if response.status_code == 200:
                data = response.json()
                # Extract player headshot URL
                headshot = data.get("headshot", "")
                if headshot:
                    # Cache in Redis if available
                    if redis:
                        await redis.setex(f"player_headshot:{player_id}", 86400, headshot)  # Cache for 24 hours
                    return headshot
            elif response.status_code == 404:
                print(f"[gateway] Player {player_id} not found in NHL API")
            else:
                print(f"[gateway] NHL API error {response.status_code} for player {player_id}")
    except httpx.TimeoutException:
        print(f"[gateway] Timeout fetching player headshot {player_id}")
    except Exception as e:
        print(f"[gateway] Error fetching player headshot {player_id}: {e}")
    
    # Fallback - return None so caller can handle it
    return None

def calculate_win_probability(
    home_score: int,
    away_score: int,
    game_state: str,
    period: int = None,
    time_in_period: str = "",
    plays: list = None
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
    time_factor = 1.0 - (total_time_remaining / regulation_time_total) if regulation_time_total > 0 else 0.5
    time_factor = max(0.0, min(1.0, time_factor))  # Clamp between 0 and 1
    
    # Score differential weight increases as game progresses
    score_weight = 1.2 + (time_factor * 0.8)  # 1.2 to 2.0
    
    # Calculate base log-odds from score differential
    base_z = score_diff * score_weight
    
    # Factor in time remaining (more time = less certainty)
    # If lots of time remaining, probability is closer to 50%
    # If little time remaining, probability is more extreme
    time_penalty = total_time_remaining / regulation_time_total if regulation_time_total > 0 else 0.5
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

async def get_player_names_batch(player_ids: list, redis: Redis = None) -> dict:
    """Batch fetch player names in parallel"""
    if not player_ids:
        return {}
    
    # Remove None and duplicates
    unique_ids = list(set([pid for pid in player_ids if pid]))
    if not unique_ids:
        return {}
    
    # Check Redis cache first (batch read)
    cached_names = {}
    if redis and unique_ids:
        # Batch read from Redis
        keys = [f"player_name:{pid}" for pid in unique_ids]
        values = await redis.mget(keys)
        for pid, value in zip(unique_ids, values):
            if value:
                cached_names[pid] = value
    
    # Find missing player IDs
    missing_ids = [pid for pid in unique_ids if pid not in cached_names]
    
    if not missing_ids:
        return cached_names
    
    # Fetch missing players in parallel
    async def fetch_player(pid):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api-web.nhle.com/v1/player/{pid}/landing",
                    timeout=3.0
                )
                if response.status_code == 200:
                    data = response.json()
                    first_name = data.get("firstName", {}).get("default", "")
                    last_name = data.get("lastName", {}).get("default", "")
                    if first_name and last_name:
                        name = f"{first_name} {last_name}"
                        # Cache in Redis
                        if redis:
                            await redis.setex(f"player_name:{pid}", 86400, name)
                        return pid, name
                elif response.status_code == 404:
                    print(f"[gateway] Player {pid} not found in NHL API")
                else:
                    print(f"[gateway] NHL API error {response.status_code} for player {pid}")
        except httpx.TimeoutException:
            print(f"[gateway] Timeout fetching player {pid}")
        except Exception as e:
            print(f"[gateway] Error fetching player {pid}: {e}")
        # Return None if not found - caller will handle fallback
        return pid, None
    
    # Fetch all missing players in parallel
    tasks = [fetch_player(pid) for pid in missing_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Combine results
    for result in results:
        if isinstance(result, Exception):
            print(f"[gateway] Exception in batch player fetch: {result}")
            continue
        if isinstance(result, tuple):
            pid, name = result
            if name:  # Only add if name was successfully fetched
                cached_names[pid] = name
    
    return cached_names

async def get_player_headshots_batch(player_ids: list, redis: Redis = None) -> dict:
    """Batch fetch player headshots in parallel"""
    if not player_ids:
        return {}
    
    # Remove None and duplicates
    unique_ids = list(set([pid for pid in player_ids if pid]))
    if not unique_ids:
        return {}
    
    # Check Redis cache first (batch read)
    cached_headshots = {}
    if redis and unique_ids:
        # Batch read from Redis
        keys = [f"player_headshot:{pid}" for pid in unique_ids]
        values = await redis.mget(keys)
        for pid, value in zip(unique_ids, values):
            if value:
                cached_headshots[pid] = value
    
    # Find missing player IDs
    missing_ids = [pid for pid in unique_ids if pid not in cached_headshots]
    
    if not missing_ids:
        return cached_headshots
    
    # Fetch missing players in parallel
    async def fetch_player_headshot(pid):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api-web.nhle.com/v1/player/{pid}/landing",
                    timeout=3.0
                )
                if response.status_code == 200:
                    data = response.json()
                    headshot = data.get("headshot", "")
                    if headshot:
                        # Cache in Redis
                        if redis:
                            await redis.setex(f"player_headshot:{pid}", 86400, headshot)
                        return pid, headshot
                elif response.status_code == 404:
                    print(f"[gateway] Player {pid} not found in NHL API")
                else:
                    print(f"[gateway] NHL API error {response.status_code} for player {pid}")
        except httpx.TimeoutException:
            print(f"[gateway] Timeout fetching player headshot {pid}")
        except Exception as e:
            print(f"[gateway] Error fetching player headshot {pid}: {e}")
        # Return None if not found - caller will handle fallback
        return pid, None
    
    # Fetch all missing players in parallel
    tasks = [fetch_player_headshot(pid) for pid in missing_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Combine results
    for result in results:
        if isinstance(result, Exception):
            print(f"[gateway] Exception in batch player headshot fetch: {result}")
            continue
        if isinstance(result, tuple):
            pid, headshot = result
            if headshot:  # Only add if headshot was successfully fetched
                cached_headshots[pid] = headshot
    
    return cached_headshots

@app.get("/favicon.ico")
async def favicon():
    """Return 204 No Content for favicon requests to suppress 404 errors"""
    from fastapi.responses import Response
    return Response(status_code=204)

@app.get("/")
async def root():
    """Serve the main web interface"""
    from fastapi.responses import Response
    import time
    static_file = os.path.join(static_dir, "index.html")
    if os.path.exists(static_file):
        with open(static_file, 'r', encoding='utf-8') as f:
            content = f.read()
        # Add cache-busting timestamp to script tags and CSS
        timestamp = int(time.time())
        # Replace CSS and JS references with versioned ones
        content = content.replace('/static/styles.css?v=', f'/static/styles.css?v={timestamp}&')
        return Response(
            content=content,
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0, private",
                "Pragma": "no-cache",
                "Expires": "0",
                "Vary": "Accept-Encoding",
                "X-Content-Type-Options": "nosniff"
            }
        )
    return {"message": "NHL Game Predictor API", "docs": "/docs"}

class WinProb(BaseModel):
    game_id: str
    p_home_win: float
    model_id: str
    ts: float


REQUESTS = Counter("gateway_requests_total", "Total HTTP requests", ["path", "method", "status"])
LATENCY = Histogram("gateway_request_latency_seconds", "Request latency", buckets=[0.005,0.01,0.025,0.05,0.1,0.25,0.5,1,2])
WS_CONNECTIONS = Gauge("gateway_ws_connections", "Current websocket connections")

@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    LATENCY.observe(time.perf_counter() - start)
    try:
        REQUESTS.labels(path=request.url.path, method=request.method, status=response.status_code).inc()
    except Exception:
        REQUESTS.labels(path=str(request.url.path), method=request.method, status=getattr(response, "status_code", 0)).inc()
    return response

@app.get("/metrics")
async def metrics():
    data = generate_latest()
    return (
        data,
        200,
        {"Content-Type": CONTENT_TYPE_LATEST},
    )

async def run_ingestion(game_id: str, redis: Redis):
    """Run NHL game ingestion in background"""
    try:
        # Clear old data for this game
        await redis.delete(f"events:{game_id}")
        # Clear game state and predictions to prevent accumulation
        await redis.delete(f"state:{game_id}")
        await redis.delete(f"pred:{game_id}")
        # Set a flag to signal feature_state to reset this game's state
        await redis.setex(f"reset_game:{game_id}", 60, "1")  # Expires in 60 seconds
        
        # Fetch and process game data from official NHL API
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
            await redis.hset(f"ingestion_status:{game_id}", "error", "No game data found")
            return
        
        plays = game_data.get("plays", [])
        if not plays:
            await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
            await redis.hset(f"ingestion_status:{game_id}", "error", "No plays found")
            return
        
        # Get team IDs and names
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        home_team_name = game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home Team")
        away_team_name = game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away Team")
        
        # Cache team names for 24 hours
        await redis.setex(f"game:{game_id}:home_team", 86400, home_team_name)
        await redis.setex(f"game:{game_id}:away_team", 86400, away_team_name)
        
        # Get game start time
        game_start_str = game_data.get("startTimeUTC", "")
        game_start_ts = None
        if game_start_str:
            game_start = datetime.fromisoformat(game_start_str.replace('Z', '+00:00'))
            game_start_ts = game_start.timestamp()
        
        # Process events and publish to Redis
        for play in plays:
            # Skip non-relevant events
            type_code = str(play.get("typeCode", ""))
            if type_code in ["520", "516", "517", "524"]:  # period-start, stoppage, period-end, game-end
                continue
            
            # Map event types
            type_mapping = {
                "502": "FACEOFF", "503": "HIT", "504": "HIT",
                "505": "GOAL", "506": "SHOT", "507": "SHOT",
                "508": "BLOCK", "509": "PENALTY",
            }
            mapped_type = type_mapping.get(type_code, "SHOT")
            
            # Get team
            details = play.get("details", {})
            event_owner_id = details.get("eventOwnerTeamId")
            if event_owner_id == home_team_id:
                team = "HOME"
            elif event_owner_id == away_team_id:
                team = "AWAY"
            else:
                team = "HOME" if play.get("homeTeamDefendingSide") == "right" else "AWAY"
            
            # Get strength with empty net and shorthanded detection
            situation = play.get("situationCode", "1551")
            away_skaters = int(situation[1]) if len(situation) >= 2 else 5
            home_skaters = int(situation[3]) if len(situation) >= 4 else 5
            
            # Detect empty net situations (6 skaters or 0 skaters = goalie pulled)
            empty_net = False
            if away_skaters == 6 or home_skaters == 6 or away_skaters == 0 or home_skaters == 0:
                empty_net = True
            
            # Determine strength from the event-owning team's perspective
            if team == "HOME":
                if empty_net:
                    if home_skaters == 6:
                        if away_skaters < 5:
                            strength = "ENPP"  # Empty net + power play (opponent has < 5 skaters)
                        else:
                            strength = "EN"  # Empty net even strength (6v5)
                    elif away_skaters == 6:
                        # Away has empty net (6 skaters) - HOME is defending against empty net
                        if home_skaters < 5:
                            strength = "PK"  # HOME is shorthanded (penalty kill situation)
                        else:
                            strength = "PK"  # HOME defending against empty net (disadvantage)
                    elif home_skaters == 0:
                        strength = "PK"  # Home is shorthanded
                    elif away_skaters == 0:
                        strength = "PP"  # Home is on power play
                elif home_skaters == 5 and away_skaters == 5:
                    strength = "EV"
                elif home_skaters > away_skaters:
                    strength = "PP"
                elif home_skaters < away_skaters:
                    if home_skaters < 5:
                        strength = "SH"  # Shorthanded
                    else:
                        strength = "PK"
                else:
                    strength = "EV"
            else:  # team == "AWAY"
                if empty_net:
                    if away_skaters == 6:
                        if home_skaters < 5:
                            strength = "ENPP"  # Empty net + power play (opponent has < 5 skaters)
                        else:
                            strength = "EN"  # Empty net even strength (6v5)
                    elif home_skaters == 6:
                        # Home has empty net (6 skaters) - AWAY is defending against empty net
                        if away_skaters < 5:
                            strength = "PK"  # AWAY is shorthanded (penalty kill situation)
                        else:
                            strength = "PK"  # AWAY defending against empty net (disadvantage)
                    elif away_skaters == 0:
                        strength = "PK"  # Away is shorthanded
                    elif home_skaters == 0:
                        strength = "PP"  # Away is on power play
                elif away_skaters == 5 and home_skaters == 5:
                    strength = "EV"
                elif away_skaters > home_skaters:
                    strength = "PP"
                elif away_skaters < home_skaters:
                    if away_skaters < 5:
                        strength = "SH"  # Shorthanded
                    else:
                        strength = "PK"
                else:
                    strength = "EV"
            
            # Get timestamp
            time_in_period = play.get("timeInPeriod", "00:00")
            period = play.get("periodDescriptor", {}).get("number", 1)
            
            if game_start_ts:
                try:
                    minutes, seconds = map(int, time_in_period.split(":"))
                    elapsed_seconds = minutes * 60 + seconds
                    period_offset = (period - 1) * 1200
                    timestamp = game_start_ts + period_offset + elapsed_seconds
                except (ValueError, TypeError):
                    import time
                    timestamp = time.time()
            else:
                import time
                timestamp = time.time()
            
            # Get coordinates (API returns xCoord and yCoord in feet)
            import random
            x = details.get("xCoord", random.uniform(-100, 100))
            y = details.get("yCoord", random.uniform(-42.5, 42.5))
            
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
            
            # Create event
            event = {
                "game_id": game_id,
                "ts": timestamp,
                "team": team,
                "event_type": mapped_type,
                "strength": strength,
                "empty_net": empty_net,
                "player_id": player_id,
                "x": x,
                "y": y,
                "shot_quality": random.random(),
            }
            
            # Publish to Redis
            await redis.xadd("events", {"json": json.dumps(event)})
        
        # Mark as complete
        await redis.hset(f"ingestion_status:{game_id}", "status", "completed")
        
    except Exception as e:
        await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
        await redis.hset(f"ingestion_status:{game_id}", "error", str(e))
        print(f"Error in background ingestion: {e}")

@app.on_event("startup")
async def startup():
    app.state.redis = Redis.from_url(REDIS_URL, decode_responses=True)

@app.on_event("shutdown")
async def shutdown():
    await app.state.redis.aclose()

async def check_overtime_type(game_id: str) -> str:
    """Check if a game went to overtime or shootout. Returns None, 'OT', or 'SO'"""
    try:
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            return None
        
        plays = game_data.get("plays", [])
        if not plays:
            return None
        
        # Find the maximum period number from all plays
        max_period = 3  # Default to 3 periods (regulation)
        for play in plays:
            period_descriptor = play.get("periodDescriptor", {})
            period_number = period_descriptor.get("number", 1)
            if period_number > max_period:
                max_period = period_number
        
        # Period 4 = Overtime, Period 5+ = Shootout
        if max_period == 4:
            return "OT"
        elif max_period >= 5:
            return "SO"
        
        return None
    except Exception:
        return None

@app.get("/v1/games")
async def list_games(date: str = None):
    """List NHL games for a specific date (YYYY-MM-DD) or today if not specified"""
    try:
        schedule = await fetch_nhl_daily_schedule(date)
        
        # Fetch team standings for records
        r = app.state.redis
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
                # Format: spread value, favorite team (home/away), over/under
                spread_value = None
                spread_favorite = None
                over_under = None
                
                # TODO: Integrate with betting API (e.g., OddsJam, Wager API, etc.)
                # For now, return None - will be displayed as "N/A" on frontend
                
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
                    # Check various possible fields for current clock time
                    is_time_remaining = False  # Track if time is already remaining or elapsed
                    if period_descriptor:
                        # timeRemaining is already time remaining, use directly
                        if period_descriptor.get("timeRemaining"):
                            time_in_period = period_descriptor.get("timeRemaining")
                            is_time_remaining = True
                        # timeInPeriod from periodDescriptor might be remaining or elapsed - check context
                        elif period_descriptor.get("timeInPeriod"):
                            time_in_period = period_descriptor.get("timeInPeriod")
                            # If from periodDescriptor, it's likely time remaining
                            is_time_remaining = True
                        elif period_descriptor.get("clock"):
                            time_in_period = period_descriptor.get("clock")
                            is_time_remaining = True
                        elif period_descriptor.get("time"):
                            time_in_period = period_descriptor.get("time")
                            is_time_remaining = True
                    
                    # If not found in periodDescriptor, try to get from boxscore for more current time
                    if not time_in_period:
                        try:
                            boxscore_data = await fetch_nhl_boxscore(game_id)
                            if boxscore_data:
                                boxscore_period = boxscore_data.get("periodDescriptor", {})
                                if boxscore_period:
                                    # Always update period from boxscore if available (most current)
                                    boxscore_period_num = boxscore_period.get("number", None)
                                    if boxscore_period_num:
                                        period = boxscore_period_num
                                    
                                    if boxscore_period.get("timeRemaining"):
                                        time_in_period = boxscore_period.get("timeRemaining")
                                        is_time_remaining = True
                                    elif boxscore_period.get("timeInPeriod"):
                                        time_in_period = boxscore_period.get("timeInPeriod")
                                        is_time_remaining = True
                                    elif boxscore_period.get("clock"):
                                        time_in_period = boxscore_period.get("clock")
                                        is_time_remaining = True
                                    elif boxscore_period.get("time"):
                                        time_in_period = boxscore_period.get("time")
                                        is_time_remaining = True
                        except Exception:
                            pass  # Fall back to plays if boxscore fails
                    
                    # If still not found, get from most recent play
                    # This might be stale but it's better than nothing
                    if not time_in_period:
                        plays = game.get("plays", [])
                        if plays:
                            # Get the most recent play (any play, not just non-stoppage)
                            # This gives us the most current time available
                            for play in reversed(plays):
                                play_time = play.get("timeInPeriod", None)
                                if play_time:
                                    time_in_period = play_time
                                    # Always get period from the play to ensure accuracy
                                    play_period = play.get("periodDescriptor", {}).get("number", None)
                                    if play_period:
                                        period = play_period
                                    break
                
                # Track completed games to check OT/SO status
                if game_state in ["OFF", "FINAL"]:
                    completed_game_ids.append(game_id)
                
                games.append({
                    "game_id": game_id,
                    "away_team": away_team.get("abbrev", ""),
                    "away_team_name": away_team.get("commonName", {}).get("default", ""),
                    "away_team_logo": away_team.get("logo", ""),
                    "away_team_record": away_record,  # W-L-OTL format
                    "home_team": home_team.get("abbrev", ""),
                    "home_team_name": home_team.get("commonName", {}).get("default", ""),
                    "home_team_logo": home_team.get("logo", ""),
                    "home_team_record": home_record,  # W-L-OTL format
                    "venue": game.get("venue", {}).get("default", ""),
                    "start_time_utc": start_time,  # UTC timestamp for client-side conversion
                    "game_state": game_state,
                    "away_score": game.get("awayScore", 0) if "awayScore" in game else away_team.get("score", 0),
                    "home_score": game.get("homeScore", 0) if "homeScore" in game else home_team.get("score", 0),
                    "period": period,  # Current period (for live games)
                    "time_in_period": time_in_period,  # Time in period (format depends on source - may be elapsed or remaining)
                    "is_time_remaining": is_time_remaining if time_in_period else None,  # True if time is already remaining, False if elapsed
                    "spread": spread_value,  # e.g., -1.5, +2.5
                    "spread_favorite": spread_favorite,  # "home" or "away"
                    "over_under": over_under,  # e.g., 6.5
                    "overtime_type": overtime_type  # None, "OT", or "SO" - will be populated below
                })
        
        # Check OT/SO status for completed games in parallel
        if completed_game_ids:
            ot_checks = await asyncio.gather(*[check_overtime_type(game_id) for game_id in completed_game_ids])
            # Create a mapping of game_id -> overtime_type
            ot_map = dict(zip(completed_game_ids, ot_checks))
            # Update games with OT/SO information
            for game in games:
                if game["game_id"] in ot_map:
                    game["overtime_type"] = ot_map[game["game_id"]]
        
        # Sort games by start time
        games.sort(key=lambda x: x.get("start_time_utc", ""))
        
        return {
            "date": schedule.get("date", "") if isinstance(schedule, dict) else "",
            "games": games,
            "total_games": len(games)
        }
    except Exception as e:
        return {
            "error": str(e),
            "games": [],
            "total_games": 0
        }

@app.post("/v1/games/{game_id}/start")
async def start_game_ingestion(game_id: str):
    """Trigger ingestion for a specific game"""
    try:
        # Verify game exists
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")
        
        home_team = game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home")
        away_team = game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away")
        
        # Trigger ingestion by calling ingestor service
        # We'll use a background task to run the ingestion
        r = app.state.redis
        
        # Check if ingestion is already in progress
        existing = await r.hget(f"ingestion_status:{game_id}", "status")
        if existing and existing == "in_progress":
            return {
                "message": f"Ingestion already in progress for {away_team} @ {home_team}",
                "game_id": game_id,
                "matchup": f"{away_team} @ {home_team}",
                "status": "in_progress"
            }
        
        # Mark as in progress
        await r.hset(f"ingestion_status:{game_id}", mapping={
            "status": "in_progress",
            "game_id": game_id,
            "matchup": f"{away_team} @ {home_team}"
        })
        
        # Run ingestion in background
        asyncio.create_task(run_ingestion(game_id, r))
        
        return {
            "message": f"Started ingestion for {away_team} @ {home_team}",
            "game_id": game_id,
            "matchup": f"{away_team} @ {home_team}",
            "status": "started"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/v1/games/{game_id}/status")
async def get_game_status(game_id: str):
    """Check ingestion and prediction status for a game"""
    r = app.state.redis
    
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
            "Prediction available" if has_prediction
            else "Ingestion in progress, please wait..." if status == "in_progress"
            else "Ingestion completed, waiting for prediction..." if status == "completed"
            else "Ingestion failed" if status == "failed"
            else "No ingestion started yet. Call POST /v1/games/{game_id}/start to begin."
        )
    }

@app.get("/v1/games/{game_id}/winprob", response_model=WinProb)
async def get_winprob(game_id: str):
    r = app.state.redis
    key = f"pred:{game_id}"
    data = await r.hgetall(key)
    if not data:
        # Check if ingestion is in progress
        ingestion_status = await r.hget(f"ingestion_status:{game_id}", "status")
        if ingestion_status == "in_progress":
            raise HTTPException(
                status_code=202,
                detail="Ingestion in progress. Please wait 60-90 seconds and try again. Check status at GET /v1/games/{game_id}/status"
            )
        elif ingestion_status == "failed":
            error = await r.hget(f"ingestion_status:{game_id}", "error")
            raise HTTPException(
                status_code=500,
                detail=f"Ingestion failed: {error}. Check status at GET /v1/games/{game_id}/status"
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"No prediction yet for game {game_id}. Start ingestion with POST /v1/games/{game_id}/start"
            )
    try:
        return WinProb(
            game_id=data["game_id"],
            p_home_win=float(data["p_home_win"]),
            model_id=data["model_id"],
            ts=float(data["ts"]),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="No prediction yet for this game")

@app.get("/v1/games/{game_id}/winprob/history")
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
                    # Parse game start time (format: "YYYY-MM-DDTHH:MM:SSZ")
                    game_start = datetime.fromisoformat(game_start_str.replace('Z', '+00:00'))
                    game_start_ts = game_start.timestamp()
                except Exception:
                    pass
        
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT ts, p_home_win 
                    FROM predictions 
                    WHERE game_id = %s 
                    ORDER BY ts ASC
                    """,
                    (game_id,)
                )
                rows = await cur.fetchall()
                
                # Calculate relative time (seconds elapsed from game start)
                data = []
                for ts, p_home_win in rows:
                    # If we have game start time, calculate relative time
                    if game_start_ts:
                        relative_time = float(ts.timestamp()) - game_start_ts
                        # Only include positive relative times (after game start)
                        if relative_time >= 0:
                            data.append({"ts": relative_time, "p_home_win": float(p_home_win)})
                    else:
                        # Fallback: assume ts is already relative time (for backwards compatibility)
                        # If ts is a timestamp that looks like it's from 1970, it's probably relative time
                        ts_float = float(ts.timestamp())
                        if ts_float < 1000000:  # Less than ~11 days after epoch, probably relative time
                            data.append({"ts": ts_float, "p_home_win": float(p_home_win)})
                        else:
                            # It's an absolute timestamp but we don't have game start - skip or use as-is
                            # For now, we'll use it but the graph won't be accurate
                            data.append({"ts": ts_float, "p_home_win": float(p_home_win)})
                
                return {"game_id": game_id, "data": data}
    except Exception as e:
        print(f"[gateway] Error fetching win probability history: {e}")
        import traceback
        traceback.print_exc()
        return {"game_id": game_id, "data": []}

@app.get("/v1/games/{game_id}/rosters")
async def get_game_rosters(game_id: str):
    """Get rosters for both teams in a game"""
    try:
        boxscore = await fetch_nhl_boxscore(game_id)
        if not boxscore:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found or boxscore unavailable")
        
        # Extract roster data
        home_team = boxscore.get("homeTeam", {})
        away_team = boxscore.get("awayTeam", {})
        
        # Get roster from boxscore
        # Structure: boxscore.awayTeam.roster.roster or boxscore.homeTeam.roster.roster
        home_roster_data = home_team.get("roster", {})
        away_roster_data = away_team.get("roster", {})
        
        home_roster = home_roster_data.get("roster", []) if isinstance(home_roster_data, dict) else []
        away_roster = away_roster_data.get("roster", []) if isinstance(away_roster_data, dict) else []
        
        # Format roster players
        def format_player(player):
            """Format player data from roster"""
            return {
                "id": player.get("playerId"),
                "name": player.get("firstName", {}).get("default", "") + " " + player.get("lastName", {}).get("default", ""),
                "position": player.get("position"),
                "number": player.get("sweaterNumber"),
            }
        
        home_roster_formatted = [format_player(p) for p in home_roster if p.get("playerId")]
        away_roster_formatted = [format_player(p) for p in away_roster if p.get("playerId")]
        
        return {
            "game_id": game_id,
            "home_team": {
                "id": home_team.get("id"),
                "name": home_team.get("commonName", {}).get("default", ""),
                "abbrev": home_team.get("abbrev", ""),
                "logo": home_team.get("logo", ""),
                "roster": home_roster_formatted
            },
            "away_team": {
                "id": away_team.get("id"),
                "name": away_team.get("commonName", {}).get("default", ""),
                "abbrev": away_team.get("abbrev", ""),
                "logo": away_team.get("logo", ""),
                "roster": away_roster_formatted
            }
        }
    except Exception as e:
        print(f"[gateway] Error fetching rosters: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching rosters: {str(e)}")

@app.get("/v1/games/{game_id}/stats")
async def get_game_stats(game_id: str):
    """Get game statistics (shots, hits, faceoffs, etc.) for head-to-head display"""
    try:
        boxscore = await fetch_nhl_boxscore(game_id)
        if not boxscore:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found or boxscore unavailable")
        
        home_team = boxscore.get("homeTeam", {})
        away_team = boxscore.get("awayTeam", {})
        
        # Extract team info
        home_team_name = home_team.get("commonName", {}).get("default", "")
        away_team_name = away_team.get("commonName", {}).get("default", "")
        home_team_logo = home_team.get("logo", "")
        away_team_logo = away_team.get("logo", "")
        
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
        
        # Calculate faceoff stats - need to sum wins and calculate percentage
        def calculate_faceoff_stats(players_dict):
            for position_group in ["forwards", "defense", "goalies"]:
                players = players_dict.get(position_group, [])
                for player in players:
                    if isinstance(player, dict):
                        fo_pct = player.get("faceoffWinningPctg", 0.0)
                        # Try to estimate faceoffs from TOI and position
                        # For centers, assume ~15-20 faceoffs per game
                        # This is approximate, but better than 0
                        if player.get("position") == "C" and fo_pct > 0:
                            # If we have a percentage, try to infer
                            # For now, we'll need to calculate from actual faceoff data
                            # But the API might not provide total faceoffs
                            pass
            # For now, calculate from winning percentage if available
            # We'll need to get this from play-by-play or calculate differently
            return 0, 0
        
        # Get shots directly from team objects
        home_shots = home_team.get("sog", 0)
        away_shots = away_team.get("sog", 0)
        
        # Sum other stats from player data
        home_hits = sum_player_stat(home_players, "hits")
        away_hits = sum_player_stat(away_players, "hits")
        
        home_blocked = sum_player_stat(home_players, "blockedShots")
        away_blocked = sum_player_stat(away_players, "blockedShots")
        
        # Try to get takeaways/giveaways from team level first, then fall back to player sum
        # Check multiple possible field names (camelCase, lowercase, etc.)
        # Use get() with None as default to distinguish between 0 (valid) and missing (None)
        home_takeaways = (home_team.get("takeaways") if "takeaways" in home_team 
                         else home_team.get("takeAways") if "takeAways" in home_team 
                         else None)
        if home_takeaways is None:
            home_takeaways = sum_player_stat(home_players, "takeaways") or sum_player_stat(home_players, "takeAways")
        
        away_takeaways = (away_team.get("takeaways") if "takeaways" in away_team 
                         else away_team.get("takeAways") if "takeAways" in away_team 
                         else None)
        if away_takeaways is None:
            away_takeaways = sum_player_stat(away_players, "takeaways") or sum_player_stat(away_players, "takeAways")
        
        home_giveaways = (home_team.get("giveaways") if "giveaways" in home_team 
                         else home_team.get("giveAways") if "giveAways" in home_team 
                         else None)
        if home_giveaways is None:
            home_giveaways = sum_player_stat(home_players, "giveaways") or sum_player_stat(home_players, "giveAways")
        
        away_giveaways = (away_team.get("giveaways") if "giveaways" in away_team 
                         else away_team.get("giveAways") if "giveAways" in away_team 
                         else None)
        if away_giveaways is None:
            away_giveaways = sum_player_stat(away_players, "giveaways") or sum_player_stat(away_players, "giveAways")
        
        home_pim = sum_player_stat(home_players, "pim")
        away_pim = sum_player_stat(away_players, "pim")
        
        # Calculate faceoff percentage from actual play-by-play data
        async def calculate_faceoff_pct_from_plays(game_id, home_team_id, away_team_id):
            """Count actual faceoffs from play-by-play data"""
            try:
                # Fetch play-by-play data
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
                        
                        # Determine which team won based on eventOwnerTeamId or winningPlayerId
                        # eventOwnerTeamId is the team that won the faceoff
                        if event_owner_team_id == home_team_id:
                            home_won += 1
                        elif event_owner_team_id == away_team_id:
                            away_won += 1
                        else:
                            # Fallback: try to determine from winningPlayerId if we have player team info
                            # For now, skip if we can't determine
                            continue
                        
                        total_faceoffs += 1
                
                # Calculate percentages as doubles
                if total_faceoffs > 0:
                    home_pct = round((home_won / total_faceoffs) * 100, 1)
                    away_pct = round((away_won / total_faceoffs) * 100, 1)
                    return home_pct, away_pct
                else:
                    return 0.0, 0.0
            except Exception as e:
                print(f"[gateway] Error calculating faceoff percentage: {e}")
                return 0, 0
        
        # Get team IDs for faceoff calculation
        home_team_id = home_team.get("id")
        away_team_id = away_team.get("id")
        
        # Calculate faceoff percentages from actual play-by-play data
        home_fo_pct, away_fo_pct = await calculate_faceoff_pct_from_plays(game_id, home_team_id, away_team_id)
        
        # Calculate power play stats - get from team stats first, fallback to player stats
        # First try to get power play goals from team stats (most reliable)
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
            home_skater_stats = home_stats.get("teamSkaterStats", {}) if home_stats else {}
            away_skater_stats = away_stats.get("teamSkaterStats", {}) if away_stats else {}
            
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
        async def calculate_pp_opportunities_from_plays(game_id, home_team_id, away_team_id):
            """Count actual power play opportunities by counting penalties"""
            try:
                # Fetch play-by-play data
                game_data = await fetch_nhl_play_by_play(game_id)
                if not game_data:
                    return 0, 0
                
                plays = game_data.get("plays", [])
                if not plays:
                    return 0, 0
                
                home_pp_opp = 0
                away_pp_opp = 0
                
                # Count penalties (type_code 509 = PENALTY)
                # Each penalty gives the other team a power play opportunity
                # Track penalties by period and time to detect offsetting penalties
                # Use a more lenient approach - only skip if penalties are EXACTLY at the same second
                penalty_times = {}  # Track penalties by timestamp to detect offsetting
                
                for play in plays:
                    type_code = play.get("typeCode")
                    if type_code == 509:  # PENALTY
                        details = play.get("details", {})
                        penalty_duration = details.get("duration", 0)
                        
                        # Only count penalties that result in a power play (2+ minutes, excluding fighting majors)
                        if penalty_duration >= 2:
                            event_owner_team_id = details.get("eventOwnerTeamId")
                            
                            # Get timestamp to detect offsetting penalties
                            period = play.get("periodDescriptor", {}).get("number", 1)
                            time_in_period = play.get("timeInPeriod", "00:00")
                            try:
                                minutes, seconds = map(int, time_in_period.split(":"))
                                # Use period:minute:second as key for offsetting detection
                                timestamp_key = f"{period}:{minutes}:{seconds}"
                            except (ValueError, TypeError):
                                timestamp_key = None
                            
                            # The team that took the penalty gives the other team a PP opportunity
                            if event_owner_team_id == home_team_id:
                                # Home team took penalty, so away team gets PP opportunity
                                # Check if this is offsetting (both teams had penalty at same EXACT time)
                                if timestamp_key and timestamp_key in penalty_times:
                                    other_penalty = penalty_times[timestamp_key]
                                    if other_penalty["team"] == "away":
                                        # Both teams had penalties at same exact time - offsetting, don't count
                                        penalty_times.pop(timestamp_key)
                                        continue
                                
                                away_pp_opp += 1
                                if timestamp_key:
                                    penalty_times[timestamp_key] = {"team": "home"}
                            elif event_owner_team_id == away_team_id:
                                # Away team took penalty, so home team gets PP opportunity
                                # Check if this is offsetting
                                if timestamp_key and timestamp_key in penalty_times:
                                    other_penalty = penalty_times[timestamp_key]
                                    if other_penalty["team"] == "home":
                                        # Both teams had penalties at same exact time - offsetting, don't count
                                        penalty_times.pop(timestamp_key)
                                        continue
                                
                                home_pp_opp += 1
                                if timestamp_key:
                                    penalty_times[timestamp_key] = {"team": "away"}
                            else:
                                # Can't determine team from eventOwnerTeamId
                                # Try to use committedByPlayerId to look up player's team
                                # For now, skip if we can't determine
                                print(f"[gateway] Warning: Penalty without eventOwnerTeamId in game {game_id}")
                                pass
                
                print(f"[gateway] Calculated PP opportunities from play-by-play: home={home_pp_opp}, away={away_pp_opp}")
                
                return home_pp_opp, away_pp_opp
            except Exception as e:
                print(f"[gateway] Error calculating power play opportunities: {e}")
                return 0, 0
        
        # First, try to get power play opportunities directly from boxscore team stats
        # Check various possible field names - NHL API might use different casing
        home_pp_opp = None
        away_pp_opp = None
        
        # Check team-level stats first (most reliable)
        # Try multiple possible field names and also check if they're 0 (which is valid)
        for field_name in ["powerPlayOpportunities", "powerPlayOpps", "ppOpportunities", "ppOpps", "powerPlayOps", "ppOpportunities"]:
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
            home_skater_stats = home_stats.get("teamSkaterStats", {}) if home_stats else {}
            away_skater_stats = away_stats.get("teamSkaterStats", {}) if away_stats else {}
            
            if home_skater_stats:
                for field_name in ["powerPlayOpportunities", "powerPlayOpps", "ppOpportunities"]:
                    if field_name in home_skater_stats:
                        val = home_skater_stats.get(field_name)
                        if val is not None and val != "":
                            home_pp_opp = val
                            break
            if away_skater_stats:
                for field_name in ["powerPlayOpportunities", "powerPlayOpps", "ppOpportunities"]:
                    if field_name in away_skater_stats:
                        val = away_skater_stats.get(field_name)
                        if val is not None and val != "":
                            away_pp_opp = val
                            break
            
            # Also check teamStats directly (fallback)
            if home_pp_opp is None and home_stats:
                for field_name in ["powerPlayOpportunities", "powerPlayOpps", "ppOpportunities"]:
                    if field_name in home_stats:
                        val = home_stats.get(field_name)
                        if val is not None and val != "":
                            home_pp_opp = val
                            break
            if away_pp_opp is None and away_stats:
                for field_name in ["powerPlayOpportunities", "powerPlayOpps", "ppOpportunities"]:
                    if field_name in away_stats:
                        val = away_stats.get(field_name)
                        if val is not None and val != "":
                            away_pp_opp = val
                            break
        
        # If not found in team stats, try to calculate from play-by-play
        if home_pp_opp is None or away_pp_opp is None:
            print(f"[gateway] PP opportunities not in boxscore for game {game_id}, calculating from play-by-play")
            print(f"[gateway] Home team keys: {list(home_team.keys())[:20]}")
            print(f"[gateway] Away team keys: {list(away_team.keys())[:20]}")
            calculated_home_pp_opp, calculated_away_pp_opp = await calculate_pp_opportunities_from_plays(game_id, home_team_id, away_team_id)
            
            if home_pp_opp is None:
                home_pp_opp = calculated_home_pp_opp
            if away_pp_opp is None:
                away_pp_opp = calculated_away_pp_opp
        else:
            print(f"[gateway] Using PP opportunities from boxscore for game {game_id}: home={home_pp_opp}, away={away_pp_opp}")
        
        # Ensure we have valid integers
        home_pp_opp = int(home_pp_opp) if home_pp_opp is not None else 0
        away_pp_opp = int(away_pp_opp) if away_pp_opp is not None else 0
        
        # Calculate PP percentage (only if we have opportunities)
        home_pp_pct = round((home_pp_goals / home_pp_opp * 100), 1) if home_pp_opp > 0 else 0.0
        away_pp_pct = round((away_pp_goals / away_pp_opp * 100), 1) if away_pp_opp > 0 else 0.0
        
        stats = {
            "shots": {
                "home": int(home_shots) if home_shots else 0,
                "away": int(away_shots) if away_shots else 0
            },
            "hits": {
                "home": home_hits,
                "away": away_hits
            },
            "faceoff_win_pct": {
                "home": home_fo_pct,
                "away": away_fo_pct
            },
            "penalty_minutes": {
                "home": home_pim,
                "away": away_pim
            },
            "power_play_pct": {
                "home": home_pp_pct,
                "away": away_pp_pct
            },
            "power_play_opportunities": {
                "home": home_pp_opp,
                "away": away_pp_opp
            },
            "blocked_shots": {
                "home": home_blocked,
                "away": away_blocked
            },
            "takeaways": {
                "home": home_takeaways,
                "away": away_takeaways
            },
            "giveaways": {
                "home": home_giveaways,
                "away": away_giveaways
            }
        }
        
        return {
            "game_id": game_id,
            "home_team": {
                "name": home_team_name,
                "logo": home_team_logo
            },
            "away_team": {
                "name": away_team_name,
                "logo": away_team_logo
            },
            "stats": stats
        }
    except Exception as e:
        print(f"[gateway] Error fetching game stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching game stats: {str(e)}")

@app.get("/v1/games/{game_id}/player-stats")
async def get_player_stats(game_id: str):
    """Get individual player statistics for both teams"""
    try:
        boxscore = await fetch_nhl_boxscore(game_id)
        if not boxscore:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found or boxscore unavailable")
        
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
        
        r = app.state.redis
        
        # Helper function to format player name: Use full name from NHL API (preserve proper capitalization)
        def format_player_name(first_name: str, last_name: str) -> str:
            if not first_name or not last_name:
                return last_name or first_name or "Unknown"
            # Return full name as provided by NHL API (preserves proper capitalization like McDavid, Nugent-Hopkins)
            return f"{first_name} {last_name}"
        
        # Helper function to process skater stats
        async def process_skater(player_data: dict, team: str) -> dict:
            player_id = player_data.get("playerId")
            if not player_id:
                return None
            
            # Get player name
            player_name_obj = player_data.get("name", {})
            first_name = player_name_obj.get("default", "").split()[0] if player_name_obj.get("default") else ""
            last_name = " ".join(player_name_obj.get("default", "").split()[1:]) if player_name_obj.get("default") else ""
            
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
            toi_seconds = player_data.get("toi", 0) or player_data.get("timeOnIce", 0) or 0
            if isinstance(toi_seconds, str):
                # If it's a string like "15:30", parse it
                if ':' in toi_seconds:
                    try:
                        parts = toi_seconds.split(':')
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
                    "toi": toi_formatted
                }
            }
        
        # Helper function to process goalie stats
        async def process_goalie(player_data: dict, team: str) -> dict:
            player_id = player_data.get("playerId")
            if not player_id:
                return None
            
            # Get player name
            player_name_obj = player_data.get("name", {})
            first_name = player_name_obj.get("default", "").split()[0] if player_name_obj.get("default") else ""
            last_name = " ".join(player_name_obj.get("default", "").split()[1:]) if player_name_obj.get("default") else ""
            
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
                    # If it's already a formatted string like "0/0", extract the first number
                    if '/' in value:
                        try:
                            return int(value.split('/')[0])
                        except (ValueError, IndexError):
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
            toi_seconds = player_data.get("toi", 0) or player_data.get("timeOnIce", 0) or 0
            if isinstance(toi_seconds, str):
                # If it's a string like "15:30", parse it
                if ':' in toi_seconds:
                    try:
                        parts = toi_seconds.split(':')
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
                    "toi": toi_formatted
                }
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
                        # Filter out players with 0 TOI
                        toi = skater_data.get("stats", {}).get("toi", "0:00")
                        if toi and toi != "0:00":
                            home_skaters.append(skater_data)
        
        goalies = home_players_raw.get("goalies", [])
        for player in goalies:
            if isinstance(player, dict) and player.get("playerId"):
                goalie_data = await process_goalie(player, "home")
                if goalie_data:
                    # Filter out goalies with 0 TOI
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
                        # Filter out players with 0 TOI
                        toi = skater_data.get("stats", {}).get("toi", "0:00")
                        if toi and toi != "0:00":
                            away_skaters.append(skater_data)
        
        goalies = away_players_raw.get("goalies", [])
        for player in goalies:
            if isinstance(player, dict) and player.get("playerId"):
                goalie_data = await process_goalie(player, "away")
                if goalie_data:
                    # Filter out goalies with 0 TOI
                    toi = goalie_data.get("stats", {}).get("toi", "0:00")
                    if toi and toi != "0:00":
                        away_goalies.append(goalie_data)
        
        # Sort skaters by points (descending), then goals
        home_skaters.sort(key=lambda x: (x["stats"]["pts"], x["stats"]["goals"]), reverse=True)
        away_skaters.sort(key=lambda x: (x["stats"]["pts"], x["stats"]["goals"]), reverse=True)
        
        return {
            "game_id": game_id,
            "home_team": {
                "name": home_team_name,
                "logo": home_team_logo,
                "skaters": home_skaters,
                "goalies": home_goalies
            },
            "away_team": {
                "name": away_team_name,
                "logo": away_team_logo,
                "skaters": away_skaters,
                "goalies": away_goalies
            }
        }
    except Exception as e:
        print(f"[gateway] Error fetching player stats: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error fetching player stats: {str(e)}")

@app.get("/v1/games/{game_id}/winprob/friendly")
async def get_winprob_friendly(game_id: str):
    """Human-readable win probability with percentages and game score"""
    r = app.state.redis
    key = f"pred:{game_id}"
    data = await r.hgetall(key)
    if not data:
        # Check if ingestion is in progress
        ingestion_status = await r.hget(f"ingestion_status:{game_id}", "status")
        if ingestion_status == "in_progress":
            raise HTTPException(
                status_code=202,
                detail="Ingestion in progress. Please wait 60-90 seconds and try again. Check status at GET /v1/games/{game_id}/status"
            )
        # For failed or no ingestion, return a basic response with calculated win probability
        # This allows the feed and win probability to load even if ingestion isn't available
        try:
                game_data = await fetch_nhl_play_by_play(game_id)
                if not game_data:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Game {game_id} not found"
                    )
                
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
                    plays=plays
                )
                p_away = 1.0 - p_home
                
                # Get current situation from Redis state if available
                state_key = f"state:{game_id}"
                state = await r.hgetall(state_key)
                strength = state.get("strength", "EV")
                empty_net_str = state.get("empty_net", "False")
                empty_net = empty_net_str.lower() == "true" if isinstance(empty_net_str, str) else bool(empty_net_str)
                last_event = state.get("last_event", "Game in progress")
                last_player_id_str = state.get("last_player_id", "")
                last_player_id = int(last_player_id_str) if last_player_id_str and last_player_id_str != "None" else None
                
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
                    "SH": "Shorthanded"
                }
                situation_parts = [strength_names.get(strength, strength)]
                if empty_net and strength not in ["EN", "ENPP", "ENPK"]:
                    situation_parts.append("Empty Net")
                situation_description = " + ".join(situation_parts) if len(situation_parts) > 1 else situation_parts[0]
                
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
                        "favorite": favorite
                    },
                    "score": {
                        "home": {
                            "team": home_team,
                            "goals": int(home_score) if home_score else 0,
                            "logo": home_logo,
                            "abbrev": home_abbrev
                        },
                        "away": {
                            "team": away_team,
                            "goals": int(away_score) if away_score else 0,
                            "logo": away_logo,
                            "abbrev": away_abbrev
                        }
                    },
                    "win_probability": {
                        home_team: round(p_home * 100, 1),
                        away_team: round(p_away * 100, 1),
                        "summary": f"{home_team}: {round(p_home * 100, 1)}% | {away_team}: {round(p_away * 100, 1)}%"
                    },
                    "current_situation": {
                        "strength": situation_description,
                        "empty_net": empty_net,
                        "last_event": last_event,
                        "last_player": last_player_name
                    },
                    "favorite": favorite,
                    "spread": None,
                    "over_under": None,
                    "confidence": "Low"  # Basic calculation, not from model
                }
        except HTTPException:
            raise
        except Exception:
            # If we can't fetch game data, return 404
            raise HTTPException(
                status_code=404,
                detail=f"No prediction yet for game {game_id}. Start ingestion with POST /v1/games/{game_id}/start"
            )
    
    try:
        # Get current game time from NHL API
        game_data = await fetch_nhl_play_by_play(game_id)
        game_state = ""
        period = None
        time_in_period = ""
        period_descriptor = None
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
                # Get scores from NHL API
                api_home_score = game_data.get("homeScore") or home_team_data.get("score", 0)
                api_away_score = game_data.get("awayScore") or away_team_data.get("score", 0)
                
                # Use API scores if available, otherwise fall back to Redis
                if api_home_score is not None and api_away_score is not None:
                    home_score = int(api_home_score)
                    away_score = int(api_away_score)
                    # Update Redis state with latest scores
                    await r.hset(state_key, "home_score", str(home_score))
                    await r.hset(state_key, "away_score", str(away_score))
            
            # Get the most recent play to get current time
            plays = game_data.get("plays", [])
            if plays:
                # Get the last non-stoppage play
                for play in reversed(plays):
                    type_code = play.get("typeCode")
                    if type_code not in [520, 516, 517, 524]:  # Skip period-start, stoppage, period-end, game-end
                        time_in_period = play.get("timeInPeriod", "00:00")
                        period = play.get("periodDescriptor", {}).get("number", period)
                        break
        
        # Calculate win probability based on current game state
        p_home = calculate_win_probability(
            home_score=home_score,
            away_score=away_score,
            game_state=game_state,
            period=period,
            time_in_period=time_in_period,
            plays=plays
        )
        p_away = 1.0 - p_home
        strength = state.get("strength", "EV")
        empty_net_str = state.get("empty_net", "False")
        empty_net = empty_net_str.lower() == "true" if isinstance(empty_net_str, str) else bool(empty_net_str)
        last_event = state.get("last_event", "Unknown")
        last_player_id_str = state.get("last_player_id", "")
        last_player_id = int(last_player_id_str) if last_player_id_str and last_player_id_str != "None" else None
        
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
        
        if not home_team or not away_team or not home_logo or not away_logo or not home_abbrev or not away_abbrev:
            # Cache miss - fetch from NHL API
            try:
                game_data = await fetch_nhl_play_by_play(game_id)
                if game_data:
                    away_team_data = game_data.get("awayTeam", {})
                    home_team_data = game_data.get("homeTeam", {})
                    away_team = away_team_data.get("commonName", {}).get("default", "Away Team")
                    home_team = home_team_data.get("commonName", {}).get("default", "Home Team")
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
            "SH": "Shorthanded"
        }
        
        # Build situation description
        situation_parts = [strength_names.get(strength, strength)]
        if empty_net and strength not in ["EN", "ENPP", "ENPK"]:
            situation_parts.append("Empty Net")
        situation_description = " + ".join(situation_parts) if len(situation_parts) > 1 else situation_parts[0]
        
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
        
        # TODO: Integrate with betting API (e.g., OddsJam, Wager API, etc.)
        # For now, return None - will be displayed as "N/A" on frontend
        
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
                "over_under": over_under
            },
            "score": {
                "home": {
                    "team": home_team,
                    "abbrev": home_abbrev,
                    "goals": home_score,
                    "logo": home_logo or ""
                },
                "away": {
                    "team": away_team,
                    "abbrev": away_abbrev,
                    "goals": away_score,
                    "logo": away_logo or ""
                },
                "display": f"{home_team} {home_score} - {away_score} {away_team}"
            },
            "current_situation": {
                "strength": situation_description,
                "empty_net": empty_net,
                "last_event": last_event,
                "last_player": last_player_name
            },
            "win_probability": {
                home_team: round(p_home * 100, 1),
                away_team: round(p_away * 100, 1),
                "summary": f"{home_team}: {round(p_home * 100, 1)}% | {away_team}: {round(p_away * 100, 1)}%"
            },
            "confidence": "High" if max(p_home, p_away) > 0.7 else "Medium" if max(p_home, p_away) > 0.6 else "Low",
            "updated_at": float(data["ts"])
        }
    except Exception:
        raise HTTPException(status_code=404, detail="No prediction yet for this game")

@app.get("/v1/games/{game_id}/final")
async def get_final_score(game_id: str):
    """Get final score and game state for a completed game"""
    try:
        # Fetch game data directly from NHL API
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
        
        # Check if game went to overtime or shootout by looking at the maximum period
        max_period = 3  # Default to 3 periods (regulation)
        overtime_type = None  # None, "OT", or "SO"
        
        plays = game_data.get("plays", [])
        if plays:
            # Find the maximum period number from all plays
            for play in plays:
                period_descriptor = play.get("periodDescriptor", {})
                period_number = period_descriptor.get("number", 1)
                if period_number > max_period:
                    max_period = period_number
                    # Period 4 = Overtime, Period 5 = Shootout
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
            "overtime_type": overtime_type
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching final score: {str(e)}")

@app.get("/v1/games/{game_id}/playbyplay")
async def get_playbyplay(game_id: str, limit: int = 30):
    """Get play-by-play events for a game directly from NHL API with caching"""
    r = app.state.redis
    
    try:
        # Check cache first (cache for 5 minutes for live games, 1 hour for completed games)
        cache_key = f"playbyplay:{game_id}"
        if r:
            cached = await r.get(cache_key)
            if cached:
                cached_data = json.loads(cached)
                # Check if game is still live - if so, cache might be stale
                game_state = cached_data.get("game_state", "")
                if game_state in ["OFF", "FINAL"]:
                    # For completed games, apply filtering to show only crucial events
                    # Even if cached, we need to filter out non-crucial events
                    events = cached_data.get("events", [])
                    if events:
                        # Filter to only crucial events (GOAL, PENALTY)
                        crucial_events = [e for e in events if e.get("event_type") in ["GOAL", "PENALTY"]]
                        # Sort by timestamp descending
                        crucial_events.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
                        cached_data["events"] = crucial_events
                    return cached_data
                else:
                    # For live games, check cache age - if it's older than 5 seconds, fetch fresh
                    # Otherwise return cached but refresh in background
                    cache_age_key = f"playbyplay_cache_age:{game_id}"
                    cache_age = await r.get(cache_age_key)
                    current_time = time.time()
                    
                    # If cache is older than 5 seconds, fetch fresh data (don't use stale cache)
                    if cache_age:
                        try:
                            age = current_time - float(cache_age)
                            if age > 5:  # Cache is older than 5 seconds, fetch fresh
                                # Don't return stale cache - fetch fresh data instead
                                pass  # Will fall through to fetch fresh data
                            else:
                                # Cache is fresh (< 5 seconds old), return it and refresh in background
                                asyncio.create_task(_refresh_playbyplay_cache(game_id, r))
                                return cached_data
                        except (ValueError, TypeError):
                            # If we can't parse cache age, assume it's stale and fetch fresh
                            pass  # Will fall through to fetch fresh data
                    else:
                        # No cache age recorded, assume it's stale and fetch fresh
                        pass  # Will fall through to fetch fresh data
        
        # Fetch play-by-play directly from NHL API for accurate data
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")
        
        # Get team info
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        home_team_common = game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home Team")
        away_team_common = game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away Team")
        
        # Get full team names (placeName + commonName) for "too many men" penalties
        home_place_name = game_data.get("homeTeam", {}).get("placeName", {}).get("default", "")
        away_place_name = game_data.get("awayTeam", {}).get("placeName", {}).get("default", "")
        home_team_full = f"{home_place_name} {home_team_common}".strip() if home_place_name else home_team_common
        away_team_full = f"{away_place_name} {away_team_common}".strip() if away_place_name else away_team_common
        
        # Get team logos for "too many men" penalties
        home_team_logo = game_data.get("homeTeam", {}).get("logo", "")
        away_team_logo = game_data.get("awayTeam", {}).get("logo", "")
        
        # Cache team names (using common names for regular use, full names available for special cases)
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
                "game_state": game_data.get("gameState", "")
            }
        
        # Get game start time for timestamp calculation
        game_start_str = game_data.get("startTimeUTC", "")
        game_start_ts = None
        if game_start_str:
            game_start = datetime.fromisoformat(game_start_str.replace('Z', '+00:00'))
            game_start_ts = game_start.timestamp()
        
        # Event type mapping
        type_mapping = {
            502: "FACEOFF", 503: "HIT", 504: "HIT",
            505: "GOAL", 506: "SHOT", 507: "SHOT",
            508: "BLOCK", 509: "PENALTY",
            535: "GIVEAWAY", 536: "TAKEAWAY",
        }
        
        # Collect all unique player IDs for batch lookup
        player_ids = set()
        processed_plays = []
        
        for play in plays:
            type_code = play.get("typeCode")
            if type_code in [520, 516, 517, 524]:  # Skip period-start, stoppage, period-end, game-end
                continue
            
            # Process GOAL, PENALTY, SHOT, FACEOFF, HIT, BLOCK, GIVEAWAY, and TAKEAWAY events
            # Skip other event types (period events, stoppages, etc.)
            if type_code not in [502, 503, 504, 505, 506, 507, 508, 509, 535, 536]:
                continue
            
            mapped_type = type_mapping.get(type_code, "SHOT")
            details = play.get("details", {})
            
            # Extract player IDs based on event type
            if mapped_type == "GOAL":
                pid = details.get("scoringPlayerId")
                if pid:
                    player_ids.add(pid)
                # Also get assist player IDs
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
                # For blocked shots, we need both the blocking player and the shooting player
                shooting_pid = details.get("shootingPlayerId")
                if shooting_pid:
                    player_ids.add(shooting_pid)
                # The blocking player might be in playerId or we'll need to get it from event owner
                blocking_pid = details.get("playerId") or details.get("blockingPlayerId")
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
                # Giveaway/takeaway events have playerId in details
                pid = details.get("playerId")
                if pid:
                    player_ids.add(pid)
            
            processed_plays.append(play)
        
        # Batch fetch player names and headshots
        player_names = await get_player_names_batch(list(player_ids), r) if player_ids else {}
        player_headshots = await get_player_headshots_batch(list(player_ids), r) if player_ids else {}
        
        # Track score progression chronologically
        home_score = 0
        away_score = 0
        events = []
        
        # Process events in chronological order (they're already sorted by the API)
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
                # For goals, never use defending side fallback (defending team is the one that got scored on)
                # Goals are crucial events and should always have eventOwnerTeamId
                if mapped_type == "GOAL":
                    # For goals, use the scoring team - if homeTeamDefendingSide is "right", 
                    # home is defending, so away scored (opposite of defending)
                    print(f"[gateway] WARNING: Goal missing eventOwnerTeamId for game {game_id}, using scoring team logic")
                    team = "AWAY" if play.get("homeTeamDefendingSide") == "right" else "HOME"
                else:
                    # For non-crucial events, fallback to defending side if eventOwnerTeamId not available
                    team = "HOME" if play.get("homeTeamDefendingSide") == "right" else "AWAY"
            
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
                # Get player names and headshots from batch lookup
                player_name = player_names.get(player_id) if player_id else None
                player_headshot = player_headshots.get(player_id) if player_id else None
                assist1_name = player_names.get(assist1_player_id) if assist1_player_id else None
                assist2_name = player_names.get(assist2_player_id) if assist2_player_id else None
                
                # If batch lookup returned None, try individual fetch
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
                desc_key = details.get("descKey", "").lower()  # Get desc_key early for bench penalty check
                
                # Check if this is a bench penalty (no player assigned or explicitly a bench penalty)
                is_bench_penalty = False
                if not player_id or player_id == 0:
                    # No player assigned - this is a bench penalty
                    is_bench_penalty = True
                elif "bench" in desc_key:
                    # Explicitly a bench penalty (e.g., "bench minor")
                    is_bench_penalty = True
                
                if is_bench_penalty:
                    # Use full team name and team logo for bench penalties
                    player_id = None  # Clear player_id for bench penalties
                    player_name = home_team_full if team == "HOME" else away_team_full
                    player_headshot = home_team_logo if team == "HOME" else away_team_logo
                else:
                    # Regular penalty - fetch player info
                    player_name = player_names.get(player_id) if player_id else None
                    player_headshot = player_headshots.get(player_id) if player_id else None
                    if player_id and not player_name:
                        player_name = await get_player_name(player_id, r)
                    if player_id and not player_headshot:
                        player_headshot = await get_player_headshot(player_id, r)
            elif mapped_type in ["SHOT", "BLOCK", "HIT", "FACEOFF", "GIVEAWAY", "TAKEAWAY"]:
                # Extract player ID based on event type
                if mapped_type == "SHOT":
                    player_id = details.get("shootingPlayerId")
                elif mapped_type == "BLOCK":
                    # For blocked shots, the blocking player is the main player (event owner)
                    # The shooting player will be handled separately in the description
                    player_id = details.get("playerId") or details.get("blockingPlayerId") or details.get("shootingPlayerId")
                elif mapped_type == "HIT":
                    player_id = details.get("hittingPlayerId")
                elif mapped_type == "FACEOFF":
                    player_id = details.get("winningPlayerId")
                elif mapped_type in ["GIVEAWAY", "TAKEAWAY"]:
                    player_id = details.get("playerId")
                
                # For these event types, fetch player info from batch lookup
                player_name = player_names.get(player_id) if player_id else None
                player_headshot = player_headshots.get(player_id) if player_id else None
                # Fallback to individual fetch if batch lookup failed
                if player_id and not player_name:
                    player_name = await get_player_name(player_id, r)
                if player_id and not player_headshot:
                    player_headshot = await get_player_headshot(player_id, r)
            else:
                player_name = None
                player_headshot = None
            
            # Get strength situation
            situation = play.get("situationCode", "1551")
            away_skaters = int(situation[1]) if len(situation) >= 2 else 5
            home_skaters = int(situation[3]) if len(situation) >= 4 else 5
            
            empty_net = (away_skaters == 6 or home_skaters == 6 or away_skaters == 0 or home_skaters == 0)
            
            # Determine strength
            if team == "HOME":
                if empty_net:
                    if home_skaters == 6:
                        strength = "ENPP" if away_skaters < 5 else "EN"
                    elif away_skaters == 6:
                        strength = "PK"
                    else:
                        strength = "PK"
                elif home_skaters == 5 and away_skaters == 5:
                    strength = "EV"
                elif home_skaters > away_skaters:
                    strength = "PP"
                elif home_skaters < away_skaters:
                    strength = "SH" if home_skaters < 5 else "PK"
                else:
                    strength = "EV"
            else:  # AWAY
                if empty_net:
                    if away_skaters == 6:
                        strength = "ENPP" if home_skaters < 5 else "EN"
                    elif home_skaters == 6:
                        strength = "PK"
                    else:
                        strength = "PK"
                elif away_skaters == 5 and home_skaters == 5:
                    strength = "EV"
                elif away_skaters > home_skaters:
                    strength = "PP"
                elif away_skaters < home_skaters:
                    strength = "SH" if away_skaters < 5 else "PK"
                else:
                    strength = "EV"
            
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
            
            # Format descriptive event description
            event_desc = mapped_type
            
            if mapped_type == "SHOT":
                # Build shot description with new format
                shot_type = details.get("shotType", "").lower()
                # Convert shot type to the format user wants (e.g., "wrist" -> "wrister")
                # Keep "snap", "slap", and "backhand" as-is, convert others
                shot_type_converter = {
                    "snap": "snap",
                    "slap": "slap",
                    "wrist": "wrister",
                    "backhand": "backhand",
                    "tip-in": "tip-in",
                    "deflected": "deflected",
                    "wrap-around": "wrap-around",
                }
                shot_type_name = shot_type_converter.get(shot_type, shot_type if shot_type else "shot")
                
                # Check if shot was saved or missed
                was_blocked = details.get("wasBlocked", False)
                was_saved = details.get("wasOnGoal", False) if not was_blocked else False
                
                if was_saved:
                    # Saved: "Saved wrister shot on goal"
                    event_desc = f"Saved {shot_type_name} shot on goal"
                elif was_blocked:
                    # Blocked shots are handled separately, but format similarly
                    event_desc = f"Blocked {shot_type_name} shot"
                else:
                    # Missed: "Missed wrister shot"
                    event_desc = f"Missed {shot_type_name} shot"
                        
            elif mapped_type == "BLOCK":
                # Get both blocking player and shooting player
                blocking_player_id = details.get("playerId") or details.get("blockingPlayerId")
                shooting_player_id = details.get("shootingPlayerId")
                
                # Get player names
                blocking_player_name = None
                if blocking_player_id:
                    blocking_player_name = player_names.get(blocking_player_id)
                    if not blocking_player_name:
                        blocking_player_name = await get_player_name(blocking_player_id, r)
                
                shooting_player_name = None
                if shooting_player_id:
                    shooting_player_name = player_names.get(shooting_player_id)
                    if not shooting_player_name:
                        shooting_player_name = await get_player_name(shooting_player_id, r)
                
                # Build description: "PlayerName Blocked Shot (PlayerName shot)"
                if blocking_player_name and shooting_player_name:
                    event_desc = f"{blocking_player_name} Blocked Shot ({shooting_player_name} shot)"
                elif blocking_player_name:
                    event_desc = f"{blocking_player_name} Blocked Shot"
                elif shooting_player_name:
                    event_desc = f"Blocked Shot ({shooting_player_name} shot)"
                else:
                    event_desc = "Blocked Shot"
                
                # Use blocking player as the main player for display
                if blocking_player_id:
                    player_id = blocking_player_id
                    player_name = blocking_player_name
                    player_headshot = player_headshots.get(blocking_player_id)
                    if not player_headshot and blocking_player_id:
                        player_headshot = await get_player_headshot(blocking_player_id, r)
                
            elif mapped_type == "HIT":
                event_desc = "Hit"
                
            elif mapped_type == "FACEOFF":
                event_desc = "Faceoff Won"
            elif mapped_type == "GIVEAWAY":
                event_desc = "Giveaway"
            elif mapped_type == "TAKEAWAY":
                event_desc = "Takeaway"
                
            elif mapped_type == "GOAL":
                # Get shot type and build descriptive goal description
                shot_type = details.get("shotType", "").lower()
                
                # Calculate distance from goal
                # NHL API uses a coordinate system where:
                # - x ranges from 0 to 200 (one end to the other)
                # - Goals are positioned at x=0 (one end) and x=200 (the other end)
                # - y ranges from -42.5 to 42.5 (rink width is 85 feet)
                # Center ice is at x=100
                x_coord = details.get("xCoord")
                y_coord = details.get("yCoord")
                distance = None
                
                if x_coord is not None and y_coord is not None:
                    # NHL API uses a coordinate system where:
                    # - x ranges from 0 to 200 (one goal to the other)
                    # - Goals are at x=0 and x=200
                    # - Center ice is at x=100
                    # Determine which goal based on shot location
                    # If shot is in left half (x < 100), it's going towards goal at x=0
                    # If shot is in right half (x > 100), it's going towards goal at x=200
                    
                    # Handle both coordinate systems:
                    # - 0-200 system: goals at 0 and 200, center at 100
                    # - -100 to 100 system: goals at -89 and 89, center at 0
                    
                    if x_coord < 0:
                        # Negative coordinates: -100 to 100 system
                        # Determine goal based on which side of center (x=0)
                        # If x < 0, shot is going towards goal at x=-89
                        # If x > 0 (but we're in negative block, so this won't happen), goal at x=89
                        goal_x = -89  # Goal in negative x direction
                    elif x_coord <= 200:
                        # 0-200 coordinate system (most common)
                        if x_coord <= 100:
                            # Shot is in left half, going towards goal at x=0
                            goal_x = 0
                        else:
                            # Shot is in right half, going towards goal at x=200
                            goal_x = 200
                    else:
                        # Coordinates outside expected range, use center-relative system
                        # Goals at -89 and 89
                        if x_coord < 100:
                            goal_x = 89
                        else:
                            goal_x = -89
                    
                    # Calculate distance using Euclidean distance
                    distance = math.sqrt((x_coord - goal_x)**2 + y_coord**2)
                    
                    # Round to nearest foot
                    distance = int(round(distance))
                    
                    # Clamp distance to reasonable range (0-100 feet)
                    # Most NHL goals are scored from within 60-70 feet
                    distance = max(0, min(100, distance))
                
                # Determine game situation (game-tying, go-ahead, etc.)
                # Check what the score will be AFTER this goal
                future_home_score = home_score + 1 if team == "HOME" else home_score
                future_away_score = away_score + 1 if team == "AWAY" else away_score
                
                game_situation = ""
                # Game-tying: score becomes tied after this goal
                if future_home_score == future_away_score and home_score != away_score:
                    game_situation = "game-tying "
                # Go-ahead: team takes the lead with this goal
                elif (team == "HOME" and future_home_score > away_score and home_score <= away_score) or \
                     (team == "AWAY" and future_away_score > home_score and away_score <= home_score):
                    game_situation = "go-ahead "
                # Insurance: team already winning and extends lead
                elif (team == "HOME" and home_score > away_score) or (team == "AWAY" and away_score > home_score):
                    game_situation = "insurance "
                
                # Format shot type
                shot_type_map = {
                    "snap": "snap shot",
                    "wrist": "wrist shot",
                    "slap": "slap shot",
                    "backhand": "backhand shot",
                    "tip-in": "tip-in",
                    "deflected": "deflected shot",
                    "wrap-around": "wrap-around",
                    "penalty-shot": "penalty shot",
                }
                shot_desc = shot_type_map.get(shot_type, shot_type + " shot" if shot_type else "shot")
                
                # Build goal description with distance
                # Format: "7' Go-Ahead Slap Shot Goal"
                if distance is not None:
                    event_desc = f"{distance}' {game_situation}{shot_desc} goal"
                else:
                    event_desc = f"{game_situation}{shot_desc} goal"
                
                # Add assists if available
                assists = []
                if assist1_name:
                    assists.append(assist1_name)  # Use names as-is from NHL API (proper capitalization)
                if assist2_name:
                    assists.append(assist2_name)  # Use names as-is from NHL API (proper capitalization)
                
                if assists:
                    assist_text = ", ".join(assists)
                    event_desc += f" (assists: {assist_text})"
                
                # Capitalize the description but preserve player names exactly as they come from the NHL API
                # Extract the assist names from the description first, then capitalize the rest
                # Player names are already properly capitalized from the NHL API, so we don't want to modify them
                # Only capitalize the description text parts, not the names in parentheses
                if " (assists: " in event_desc:
                    # Split description into main part and assists part
                    main_desc, assists_part = event_desc.split(" (assists: ", 1)
                    assists_part = assists_part.rstrip(")")  # Remove closing parenthesis
                    # Capitalize only the main description (not player names)
                    main_desc = " ".join(word.capitalize() for word in main_desc.split())
                    # Reconstruct with assists part unchanged (names already properly capitalized)
                    event_desc = f"{main_desc} (assists: {assists_part})"
                else:
                    # No assists, just capitalize the description
                    event_desc = " ".join(word.capitalize() for word in event_desc.split())
                    
            elif mapped_type == "PENALTY":
                # Get penalty details
                # desc_key already extracted earlier, reuse it
                duration = details.get("duration", 0)
                
                # Check if this is a "too many men" penalty
                is_too_many_men = desc_key == "too-many-men" or "too-many-men" in desc_key
                
                # Check if this is a bench penalty (no player or explicitly bench)
                is_bench_penalty_check = False
                committed_by_player_id = details.get("committedByPlayerId")
                if not committed_by_player_id or committed_by_player_id == 0:
                    is_bench_penalty_check = True
                elif "bench" in desc_key:
                    is_bench_penalty_check = True
                
                # Format penalty description
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
                    event_desc = f"{duration} min {penalty_desc} penalty"
                else:
                    event_desc = f"{penalty_desc} penalty"
                
                # Capitalize the penalty description
                event_desc = " ".join(word.capitalize() for word in event_desc.split())
                
                # For "too many men" penalties or bench penalties, use full team name and team logo instead of player
                if is_too_many_men or is_bench_penalty_check:
                    # Use full team name (e.g., "Tampa Bay Lightning" instead of just "Lightning")
                    team_name = home_team_full if team == "HOME" else away_team_full
                    player_name = team_name  # Replace player with full team name
                    # Use team logo instead of player headshot
                    team_logo = home_team_logo if team == "HOME" else away_team_logo
                    player_headshot = team_logo if team_logo else None
                    player_id = None  # Clear player_id for team penalties
                else:
                    # For other penalties, keep using player name and headshot (set earlier)
                    pass
                
                # Add drawn by player if available
                drawn_by_id = details.get("drawnByPlayerId")
                if drawn_by_id:
                    drawn_by_name = player_names.get(drawn_by_id)
                    if drawn_by_name:
                        event_desc += f" (drawn by {drawn_by_name})"
            
            # Update score for goals
            if mapped_type == "GOAL":
                if team == "HOME":
                    home_score += 1
                else:
                    away_score += 1
            
            # Add event - ensure player_name has a fallback
            final_player_name = player_name
            if not final_player_name:
                if player_id:
                    # If we have a player_id but no name, try one more time to fetch it
                    final_player_name = await get_player_name(player_id, r)
                    if not final_player_name:
                        final_player_name = f"Player {player_id}"
                else:
                    # No player_id - this might be a team event or event without a specific player
                    # For team events (bench penalties), player_name should already be set to team name
                    # For other events, set to None and frontend will handle it appropriately
                    # For goals, always try to set a fallback name even if player_id is missing
                    if mapped_type == "GOAL":
                        # Goals are crucial events - always include them even without player info
                        final_player_name = "Unknown Player" if not final_player_name else final_player_name
                    elif mapped_type not in ["PENALTY"]:  # PENALTY already handles team name for bench penalties
                        final_player_name = None
            
            # Skip events that require a player but don't have one (HIT, SHOT, BLOCK, FACEOFF, GIVEAWAY, TAKEAWAY)
            # Goals are ALWAYS included - they are crucial events and should never be skipped
            # Penalties can have team names for bench penalties
            if mapped_type in ["HIT", "SHOT", "BLOCK", "FACEOFF", "GIVEAWAY", "TAKEAWAY"]:
                if not final_player_name or not player_id:
                    continue  # Skip this event - no player information available
            
            # Ensure event description is never empty and capitalize if needed
            if not event_desc or event_desc.strip() == "":
                event_desc = mapped_type
            
            # Capitalize event description if it's still just the mapped type (fallback case)
            if event_desc == mapped_type:
                event_desc = mapped_type.title()
            
            event_data = {
                "id": f"{game_id}-{play.get('eventId', len(events))}",
                "timestamp": timestamp,
                "event_type": mapped_type,
                "description": event_desc,
                "player": final_player_name,
                "player_id": player_id,
                "player_headshot": player_headshot,  # Add headshot URL
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
        
        # Determine max period from all plays to help frontend determine game state
        max_period = 1
        for play in plays:
            period_descriptor = play.get("periodDescriptor", {})
            period_num = period_descriptor.get("number", 1)
            if period_num > max_period:
                max_period = period_num
        
        # Check if game is complete
        game_state = game_data.get("gameState", "")
        is_complete = game_state in ["OFF", "FINAL"]
        
        # Deduplicate events by ID (in case same event appears multiple times)
        seen_ids = set()
        unique_events = []
        for event in events:
            event_id = event.get("id")
            if event_id and event_id not in seen_ids:
                seen_ids.add(event_id)
                unique_events.append(event)
            elif not event_id:
                # If no ID, create one based on timestamp and content to deduplicate
                dedup_key = f"{event.get('timestamp')}-{event.get('event_type')}-{event.get('player_id')}-{event.get('period')}-{event.get('time_in_period')}"
                if dedup_key not in seen_ids:
                    seen_ids.add(dedup_key)
                    # Create a proper ID for this event
                    event["id"] = f"{game_id}-{len(unique_events)}"
                    unique_events.append(event)
        events = unique_events
        
        # Sort events by timestamp (oldest first, then reverse for most recent first)
        # Use period and time_in_period as secondary sort keys for stability
        events.sort(key=lambda x: (
            x.get("timestamp", 0),
            x.get("period", 0),
            x.get("time_in_period", "00:00")
        ))
        events.reverse()  # Most recent first
        
        # Always return ALL crucial events (GOAL, PENALTY) regardless of limit
        crucial_events = [e for e in events if e.get("event_type") in ["GOAL", "PENALTY"]]
        
        if is_complete:
            # For completed games, show ONLY crucial events (goals and penalties)
            all_events = crucial_events
        else:
            # For live games, include non-crucial events (keep only the 4 most recent)
            non_crucial_events = [e for e in events if e.get("event_type") not in ["GOAL", "PENALTY"]]
            
            # Keep only the 4 most recent non-crucial events (already sorted most recent first)
            limited_non_crucial = non_crucial_events[:4]  # Only keep 4 most recent non-crucial events
            
            # Combine: ALL crucial events + 4 most recent non-crucial events
            all_events = crucial_events + limited_non_crucial
        
        # Sort final result by timestamp descending (most recent first)
        # Use event ID as secondary sort for stability
        all_events.sort(key=lambda x: (
            x.get("timestamp", 0),
            x.get("id", "")
        ), reverse=True)
        
        result = {
            "game_id": game_id,
            "home_team": home_team_common,
            "away_team": away_team_common,
            "events": all_events,
            "max_period": max_period,
            "game_state": game_data.get("gameState", "")
        }
        
        # Cache the result (1 hour for completed games, 10 seconds for live games)
        cache_key = f"playbyplay:{game_id}"
        if r:
            game_state = game_data.get("gameState", "")
            cache_ttl = 3600 if game_state in ["OFF", "FINAL"] else 10  # 1 hour for final, 10 seconds for live
            await r.setex(cache_key, cache_ttl, json.dumps(result))
            # Also record cache age for live games to detect stale cache
            if game_state not in ["OFF", "FINAL"]:
                cache_age_key = f"playbyplay_cache_age:{game_id}"
                await r.setex(cache_age_key, 10, str(time.time()))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching play-by-play: {str(e)}")

async def _refresh_playbyplay_cache(game_id: str, r: Redis):
    """Background task to refresh play-by-play cache for live games.
    
    This function proactively fetches fresh data and updates the cache
    so that subsequent requests can return cached data immediately.
    """
    try:
        # Fetch fresh data from API
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            return
        
        # Get team info
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        home_team_common = game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home Team")
        away_team_common = game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away Team")
        home_team_full = game_data.get("homeTeam", {}).get("name", {}).get("default", home_team_common)
        away_team_full = game_data.get("awayTeam", {}).get("name", {}).get("default", away_team_common)
        home_team_logo = game_data.get("homeTeam", {}).get("logo", "")
        away_team_logo = game_data.get("awayTeam", {}).get("logo", "")
        
        # Get plays from API
        plays = game_data.get("plays", [])
        if not plays:
            return
        
        # Get game start time for timestamp calculation
        game_start_str = game_data.get("startTimeUTC", "")
        game_start_ts = None
        if game_start_str:
            try:
                game_start = datetime.fromisoformat(game_start_str.replace('Z', '+00:00'))
                game_start_ts = game_start.timestamp()
            except (ValueError, AttributeError):
                pass
        
        # Event type mapping (same as get_playbyplay)
        type_mapping = {
            502: "FACEOFF", 503: "HIT", 504: "HIT",
            505: "GOAL", 506: "SHOT", 507: "SHOT",
            508: "BLOCK", 509: "PENALTY",
            535: "GIVEAWAY", 536: "TAKEAWAY",
        }
        
        # Collect all unique player IDs for batch lookup
        player_ids = set()
        processed_plays = []
        for play in plays:
            type_code = play.get("typeCode")
            if type_code in [520, 516, 517, 524]:  # Skip period-start, stoppage, period-end, game-end
                continue
            if type_code not in [502, 503, 504, 505, 506, 507, 508, 509, 535, 536]:
                continue
            mapped_type = type_mapping.get(type_code, "SHOT")
            details = play.get("details", {})
            
            # Extract player IDs
            if mapped_type == "GOAL":
                if details.get("scoringPlayerId"):
                    player_ids.add(details.get("scoringPlayerId"))
                if details.get("assist1PlayerId"):
                    player_ids.add(details.get("assist1PlayerId"))
                if details.get("assist2PlayerId"):
                    player_ids.add(details.get("assist2PlayerId"))
            elif mapped_type == "PENALTY":
                if details.get("committedByPlayerId"):
                    player_ids.add(details.get("committedByPlayerId"))
                if details.get("drawnByPlayerId"):
                    player_ids.add(details.get("drawnByPlayerId"))
            elif mapped_type == "SHOT":
                if details.get("shootingPlayerId"):
                    player_ids.add(details.get("shootingPlayerId"))
            elif mapped_type == "BLOCK":
                # For blocked shots, we need both the blocking player and the shooting player
                if details.get("shootingPlayerId"):
                    player_ids.add(details.get("shootingPlayerId"))
                blocking_pid = details.get("playerId") or details.get("blockingPlayerId")
                if blocking_pid:
                    player_ids.add(blocking_pid)
            elif mapped_type == "HIT":
                if details.get("hittingPlayerId"):
                    player_ids.add(details.get("hittingPlayerId"))
            elif mapped_type == "FACEOFF":
                if details.get("winningPlayerId"):
                    player_ids.add(details.get("winningPlayerId"))
            elif mapped_type in ["GIVEAWAY", "TAKEAWAY"]:
                if details.get("playerId"):
                    player_ids.add(details.get("playerId"))
            
            processed_plays.append(play)
        
        # Batch fetch player names and headshots
        player_names = await get_player_names_batch(list(player_ids), r) if player_ids else {}
        player_headshots = await get_player_headshots_batch(list(player_ids), r) if player_ids else {}
        
        # Process events (simplified version - same core logic as get_playbyplay)
        events = []
        home_score = 0
        away_score = 0
        
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
                team = "AWAY" if (mapped_type == "GOAL" and play.get("homeTeamDefendingSide") == "right") else "HOME"
                if mapped_type != "GOAL":
                    team = "HOME" if play.get("homeTeamDefendingSide") == "right" else "AWAY"
            
            # Get player info
            player_id = None
            if mapped_type == "GOAL":
                player_id = details.get("scoringPlayerId")
            elif mapped_type == "PENALTY":
                player_id = details.get("committedByPlayerId")
            elif mapped_type in ["SHOT", "BLOCK"]:
                player_id = details.get("shootingPlayerId")
            elif mapped_type == "HIT":
                player_id = details.get("hittingPlayerId")
            elif mapped_type == "FACEOFF":
                player_id = details.get("winningPlayerId")
            elif mapped_type in ["GIVEAWAY", "TAKEAWAY"]:
                player_id = details.get("playerId")
            
            player_name = player_names.get(player_id) if player_id else None
            player_headshot = player_headshots.get(player_id) if player_id else None
            
            # Skip events without player info (except goals and penalties)
            if mapped_type in ["HIT", "SHOT", "BLOCK", "FACEOFF", "GIVEAWAY", "TAKEAWAY"]:
                if not player_name or not player_id:
                    continue
            
            if mapped_type == "GOAL" and not player_name:
                player_name = "Unknown Player"
            
            # Get period and time
            period = play.get("periodDescriptor", {}).get("number", 1)
            time_in_period = play.get("timeInPeriod", "00:00")
            
            # Calculate timestamp
            timestamp = game_start_ts if game_start_ts else time.time()
            if game_start_ts:
                try:
                    minutes, seconds = map(int, time_in_period.split(":"))
                    elapsed_seconds = minutes * 60 + seconds
                    period_offset = (period - 1) * 1200
                    timestamp = game_start_ts + period_offset + elapsed_seconds
                except (ValueError, TypeError):
                    pass
            
            # Update score for goals
            if mapped_type == "GOAL":
                if team == "HOME":
                    home_score += 1
                else:
                    away_score += 1
            
            # Get strength
            situation_code = play.get("situationCode", "1551")
            away_skaters = int(situation_code[1]) if len(situation_code) >= 2 else 5
            home_skaters = int(situation_code[3]) if len(situation_code) >= 4 else 5
            strength = "EV"
            if away_skaters != 5 or home_skaters != 5:
                if away_skaters < home_skaters:
                    strength = "PP"
                elif home_skaters < away_skaters:
                    strength = "PK"
            empty_net = away_skaters == 6 or home_skaters == 6 or away_skaters == 0 or home_skaters == 0
            
            # Build event description (same logic as main function - don't use API description)
            event_desc = mapped_type
            
            if mapped_type == "SHOT":
                # Build shot description with new format
                shot_type = details.get("shotType", "").lower()
                shot_type_converter = {
                    "snap": "snap",
                    "slap": "slap",
                    "wrist": "wrister",
                    "backhand": "backhand",
                    "tip-in": "tip-in",
                    "deflected": "deflected",
                    "wrap-around": "wrap-around",
                }
                shot_type_name = shot_type_converter.get(shot_type, shot_type if shot_type else "shot")
                
                was_blocked = details.get("wasBlocked", False)
                was_saved = details.get("wasOnGoal", False) if not was_blocked else False
                
                if was_saved:
                    event_desc = f"Saved {shot_type_name} shot on goal"
                elif was_blocked:
                    event_desc = f"Blocked {shot_type_name} shot"
                else:
                    event_desc = f"Missed {shot_type_name} shot"
                        
            elif mapped_type == "BLOCK":
                # Get both blocking player and shooting player
                blocking_player_id = details.get("playerId") or details.get("blockingPlayerId")
                shooting_player_id = details.get("shootingPlayerId")
                
                # Get player names
                blocking_player_name = None
                if blocking_player_id:
                    blocking_player_name = player_names.get(blocking_player_id)
                    if not blocking_player_name:
                        blocking_player_name = await get_player_name(blocking_player_id, r)
                
                shooting_player_name = None
                if shooting_player_id:
                    shooting_player_name = player_names.get(shooting_player_id)
                    if not shooting_player_name:
                        shooting_player_name = await get_player_name(shooting_player_id, r)
                
                # Build description: "PlayerName Blocked Shot (PlayerName shot)"
                if blocking_player_name and shooting_player_name:
                    event_desc = f"{blocking_player_name} Blocked Shot ({shooting_player_name} shot)"
                elif blocking_player_name:
                    event_desc = f"{blocking_player_name} Blocked Shot"
                elif shooting_player_name:
                    event_desc = f"Blocked Shot ({shooting_player_name} shot)"
                else:
                    event_desc = "Blocked Shot"
                
                # Use blocking player as the main player for display
                if blocking_player_id:
                    player_id = blocking_player_id
                    player_name = blocking_player_name
                    player_headshot = player_headshots.get(blocking_player_id)
                    if not player_headshot and blocking_player_id:
                        player_headshot = await get_player_headshot(blocking_player_id, r)
                
            elif mapped_type == "HIT":
                event_desc = "Hit"
                
            elif mapped_type == "FACEOFF":
                event_desc = "Faceoff Won"
            elif mapped_type == "GIVEAWAY":
                event_desc = "Giveaway"
            elif mapped_type == "TAKEAWAY":
                event_desc = "Takeaway"
                
            elif mapped_type == "GOAL":
                # Get shot type and build descriptive goal description (same as main function)
                shot_type = details.get("shotType", "").lower()
                
                # Calculate distance from goal
                x_coord = details.get("xCoord")
                y_coord = details.get("yCoord")
                distance = None
                
                if x_coord is not None and y_coord is not None:
                    if x_coord < 0:
                        goal_x = -89
                    elif x_coord <= 200:
                        if x_coord <= 100:
                            goal_x = 0
                        else:
                            goal_x = 200
                    else:
                        if x_coord < 100:
                            goal_x = 89
                        else:
                            goal_x = -89
                    
                    distance = math.sqrt((x_coord - goal_x)**2 + y_coord**2)
                    distance = int(round(distance))
                    distance = max(0, min(100, distance))
                
                # Determine game situation
                future_home_score = home_score + 1 if team == "HOME" else home_score
                future_away_score = away_score + 1 if team == "AWAY" else away_score
                
                game_situation = ""
                if future_home_score == future_away_score and home_score != away_score:
                    game_situation = "game-tying "
                elif (team == "HOME" and future_home_score > away_score and home_score <= away_score) or \
                     (team == "AWAY" and future_away_score > home_score and away_score <= home_score):
                    game_situation = "go-ahead "
                elif (team == "HOME" and home_score > away_score) or (team == "AWAY" and away_score > home_score):
                    game_situation = "insurance "
                
                # Format shot type
                shot_type_map = {
                    "snap": "snap shot",
                    "wrist": "wrist shot",
                    "slap": "slap shot",
                    "backhand": "backhand shot",
                    "tip-in": "tip-in",
                    "deflected": "deflected shot",
                    "wrap-around": "wrap-around",
                    "penalty-shot": "penalty shot",
                }
                shot_desc = shot_type_map.get(shot_type, shot_type + " shot" if shot_type else "shot")
                
                # Build goal description with distance
                if distance is not None:
                    event_desc = f"{distance}' {game_situation}{shot_desc} goal"
                else:
                    event_desc = f"{game_situation}{shot_desc} goal"
                
                # Get assist player IDs for goals
                assist1_player_id = details.get("assist1PlayerId")
                assist2_player_id = details.get("assist2PlayerId")
                assist1_name = player_names.get(assist1_player_id) if assist1_player_id else None
                assist2_name = player_names.get(assist2_player_id) if assist2_player_id else None
                
                # Add assists if available
                assists = []
                if assist1_name:
                    assists.append(assist1_name)
                if assist2_name:
                    assists.append(assist2_name)
                
                if assists:
                    assist_text = ", ".join(assists)
                    event_desc += f" (assists: {assist_text})"
                
                # Capitalize the description but preserve player names
                if " (assists: " in event_desc:
                    main_desc, assists_part = event_desc.split(" (assists: ", 1)
                    assists_part = assists_part.rstrip(")")
                    main_desc = " ".join(word.capitalize() for word in main_desc.split())
                    event_desc = f"{main_desc} (assists: {assists_part})"
                else:
                    event_desc = " ".join(word.capitalize() for word in event_desc.split())
                    
            elif mapped_type == "PENALTY":
                # Get penalty details
                desc_key = details.get("descKey", "").lower()
                duration = details.get("duration", 0)
                
                # Check if this is a "too many men" penalty
                is_too_many_men = desc_key == "too-many-men" or "too-many-men" in desc_key
                
                # Check if this is a bench penalty (no player or explicitly bench)
                is_bench_penalty_check = False
                committed_by_player_id = details.get("committedByPlayerId")
                if not committed_by_player_id or committed_by_player_id == 0:
                    is_bench_penalty_check = True
                elif "bench" in desc_key:
                    is_bench_penalty_check = True
                
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
                    event_desc = f"{duration} min {penalty_desc} penalty"
                else:
                    event_desc = f"{penalty_desc} penalty"
                
                # Capitalize the penalty description
                event_desc = " ".join(word.capitalize() for word in event_desc.split())
                
                # For "too many men" penalties or bench penalties, use full team name and team logo instead of player
                if is_too_many_men or is_bench_penalty_check:
                    # Use full team name (e.g., "Tampa Bay Lightning" instead of just "Lightning")
                    team_name = home_team_full if team == "HOME" else away_team_full
                    player_name = team_name  # Replace player with full team name
                    # Use team logo instead of player headshot
                    team_logo = home_team_logo if team == "HOME" else away_team_logo
                    player_headshot = team_logo if team_logo else None
                    player_id = None  # Clear player_id for team penalties
                else:
                    # For other penalties, keep using player name and headshot (set earlier)
                    pass
                
                # Add drawn by player if available
                drawn_by_id = details.get("drawnByPlayerId")
                if drawn_by_id:
                    drawn_by_name = player_names.get(drawn_by_id)
                    if drawn_by_name:
                        event_desc += f" (drawn by {drawn_by_name})"
            
            # Ensure event description is never empty
            if not event_desc or event_desc.strip() == "":
                event_desc = mapped_type
            
            # Capitalize event description if it's still just the mapped type (fallback case)
            if event_desc == mapped_type:
                event_desc = mapped_type.title()
            
            event_data = {
                "id": f"{game_id}-{play.get('eventId', len(events))}",
                "timestamp": timestamp,
                "event_type": mapped_type,
                "description": event_desc,
                "player": player_name,
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
            events.append(event_data)
        
        # Deduplicate and sort events (same logic as get_playbyplay)
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
        
        # Sort events by timestamp descending (most recent first)
        events.sort(key=lambda x: (x.get("timestamp", 0), x.get("period", 0), x.get("time_in_period", "00:00")))
        events.reverse()
        
        # Get max period and game state
        max_period = 1
        for play in plays:
            period_num = play.get("periodDescriptor", {}).get("number", 1)
            if period_num > max_period:
                max_period = period_num
        
        game_state = game_data.get("gameState", "")
        is_complete = game_state in ["OFF", "FINAL"]
        
        # Filter events (crucial events only for completed games, all crucial + 4 recent for live)
        crucial_events = [e for e in events if e.get("event_type") in ["GOAL", "PENALTY"]]
        if is_complete:
            all_events = crucial_events
        else:
            non_crucial_events = [e for e in events if e.get("event_type") not in ["GOAL", "PENALTY"]]
            limited_non_crucial = non_crucial_events[:4]
            all_events = crucial_events + limited_non_crucial
        
        all_events.sort(key=lambda x: (x.get("timestamp", 0), x.get("id", "")), reverse=True)
        
        # Update cache with fresh data
        result = {
            "game_id": game_id,
            "home_team": home_team_common,
            "away_team": away_team_common,
            "events": all_events,
            "max_period": max_period,
            "game_state": game_state
        }
        
        cache_key = f"playbyplay:{game_id}"
        cache_ttl = 3600 if is_complete else 10
        await r.setex(cache_key, cache_ttl, json.dumps(result))
        if not is_complete:
            cache_age_key = f"playbyplay_cache_age:{game_id}"
            await r.setex(cache_age_key, 10, str(time.time()))
        
    except Exception as e:
        print(f"[gateway] Error refreshing play-by-play cache for {game_id}: {e}")

@app.get("/v1/standings")
async def get_standings():
    """Get current NHL standings with full team information"""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(f"{NHL_API_BASE}/standings/now")
            if response.status_code == 200:
                data = response.json()
                
                # The API returns { "standings": [...] }
                standings = data.get("standings", [])
                standings_list = []
                
                # Process standings - extract all relevant information
                for team_data in standings:
                    if isinstance(team_data, dict):
                        team_info = {
                            "abbreviation": team_data.get("teamAbbrev", {}).get("default", ""),
                            "name": team_data.get("teamName", {}).get("default", ""),
                            "place_name": team_data.get("placeName", {}).get("default", ""),
                            "common_name": team_data.get("commonName", {}).get("default", ""),
                            "wins": team_data.get("wins", 0),
                            "losses": team_data.get("losses", 0),
                            "ot_losses": team_data.get("otLosses", 0),
                            "points": team_data.get("points", 0),
                            "games_played": team_data.get("gamesPlayed", 0),
                            "goals_for": team_data.get("goalFor", 0),
                            "goals_against": team_data.get("goalAgainst", 0),
                            "logo": team_data.get("teamLogo", "")
                        }
                        
                        # Create full team name
                        full_name = f"{team_info['place_name']} {team_info['common_name']}".strip()
                        if not full_name:
                            full_name = team_info['name']
                        team_info['full_name'] = full_name
                        
                        standings_list.append(team_info)
                
                # Sort by points (descending), then by wins
                standings_list.sort(key=lambda x: (x['points'], x['wins']), reverse=True)
                
                return {"standings": standings_list}
            else:
                raise HTTPException(status_code=response.status_code, detail=f"Standings API error {response.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching standings: {str(e)}")

@app.websocket("/v1/stream/{game_id}")
async def stream_game(ws: WebSocket, game_id: str):
    await ws.accept()
    WS_CONNECTIONS.inc()
    r = app.state.redis
    pubsub = r.pubsub()
    channel = f"pred_stream:{game_id}"
    await pubsub.subscribe(channel)
    try:
        # Send snapshot if exists
        snap = await r.hgetall(f"pred:{game_id}")
        if snap:
            await ws.send_text(json.dumps(snap))
        # Stream deltas
        async for msg in pubsub.listen():
            if msg and msg.get("type") == "message":
                await ws.send_text(msg["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        WS_CONNECTIONS.dec()

@app.get("/v1/games/{game_id}/powerplay")
async def get_powerplay_status(game_id: str):
    """Get current power play status and time remaining"""
    r = app.state.redis
    
    try:
        # Fetch game data from NHL API
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")
        
        # Get current game state
        game_state = game_data.get("gameState", "")
        if game_state not in ["LIVE", "CRIT"]:
            # Game is not live, no power play
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None
            }
        
        # Get plays from game data
        plays = game_data.get("plays", [])
        if not plays:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None
            }
        
        # Check current situation code from most recent play to determine if there's a power play
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
                "team_logo": None
            }
        
        # Check situation code to determine if there's a power play
        situation_code = current_play.get("situationCode", "1551")
        # Format: ABCD where typically:
        # - Position 1: away_goalie (1=present, 0=pulled)
        # - Position 2: away_skaters (0-6)
        # - Position 3: home_goalie (1=present, 0=pulled)
        # - Position 4: home_skaters (0-6)
        if len(situation_code) < 4:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None
            }
        
        away_skaters = int(situation_code[1]) if len(situation_code) >= 2 else 5
        home_skaters = int(situation_code[3]) if len(situation_code) >= 4 else 5
        
        # Determine which team is on the power play based on skater count
        pp_team = None
        if away_skaters != home_skaters and away_skaters != 6 and home_skaters != 6:
            # One team has more skaters = power play
            if home_skaters > away_skaters:
                pp_team = "HOME"  # Home has more skaters, home is on PP
            elif away_skaters > home_skaters:
                pp_team = "AWAY"  # Away has more skaters, away is on PP
        
        if not pp_team:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None
            }
        
        # Get team IDs
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        
        # Find the most recent penalty event that matches the current power play
        most_recent_penalty = None
        penalty_time = None
        penalty_duration = 0
        
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
                    penalty_team = "AWAY"  # Home team took penalty, away is on PP
                elif event_owner_id == away_team_id:
                    penalty_team = "HOME"  # Away team took penalty, home is on PP
                
                # Only process if this penalty matches the current power play team
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
                        # Convert to seconds elapsed (not remaining)
                        # If time is 19:00, that's 60 seconds elapsed (20:00 - 19:00 = 1:00 = 60s)
                        return (20 * 60) - (minutes * 60 + seconds)
                    except (ValueError, TypeError):
                        return 0
                
                penalty_elapsed = time_to_seconds(penalty_time)  # Time elapsed in period when penalty occurred
                current_elapsed = time_to_seconds(current_time)  # Time elapsed in current period
                
                # Calculate total time elapsed since penalty
                if current_period == period:
                    # Same period: elapsed = current_elapsed - penalty_elapsed
                    time_elapsed = current_elapsed - penalty_elapsed
                elif current_period > period:
                    # Penalty was in previous period(s)
                    # Time elapsed = time remaining in penalty period + time played in current period
                    time_remaining_in_penalty_period = (20 * 60) - penalty_elapsed
                    time_elapsed = time_remaining_in_penalty_period + current_elapsed
                    # Add full periods in between (if any)
                    if current_period > period + 1:
                        time_elapsed += (current_period - period - 1) * 20 * 60
                else:
                    # Shouldn't happen (current period before penalty period)
                    time_elapsed = penalty_duration * 60 + 1  # Mark as expired
                
                # Penalty duration is in minutes, convert to seconds
                penalty_duration_seconds = penalty_duration * 60
                
                # Calculate time remaining
                time_remaining_seconds = max(0, penalty_duration_seconds - time_elapsed)
                
                # Only use this penalty if it's still active (time remaining > 0 and elapsed >= 0)
                if time_remaining_seconds > 0 and time_elapsed >= 0:
                    most_recent_penalty = {
                        "team": pp_team,
                        "duration": penalty_duration,
                        "time_remaining": time_remaining_seconds
                    }
                    break
        
        if most_recent_penalty and most_recent_penalty["time_remaining"] > 0:
            # Get the team logo for the team ON the power play
            # pp_team is already set from the situation code analysis above
            
            # Get team logo for the team on PP
            team_logo_key = f"game:{game_id}:{'home' if pp_team == 'HOME' else 'away'}_logo"
            team_logo = await r.get(team_logo_key)
            
            # If not in cache, get from game data
            if not team_logo:
                if pp_team == "HOME":
                    team_logo = game_data.get("homeTeam", {}).get("logo", "")
                else:
                    team_logo = game_data.get("awayTeam", {}).get("logo", "")
            
            # Get player strengths from situation code using current_play (already found above)
            situation_code = current_play.get("situationCode", "1551") if current_play else "1551"
            away_skaters = int(situation_code[1]) if len(situation_code) >= 2 else 5
            home_skaters = int(situation_code[3]) if len(situation_code) >= 4 else 5
            
            # Determine which team is on PP and format strength
            # pp_team is the team on PP, so they should have more skaters
            if pp_team == "HOME":
                # Home is on PP, so home has more skaters
                strength = f"{home_skaters} on {away_skaters}"
            else:
                # Away is on PP, so away has more skaters
                strength = f"{away_skaters} on {home_skaters}"
            
            # Get time remaining from most_recent_penalty (already calculated in the loop)
            time_remaining_seconds = most_recent_penalty["time_remaining"]
            
            # Calculate time elapsed: duration - remaining
            penalty_duration_seconds = most_recent_penalty["duration"] * 60
            time_elapsed = penalty_duration_seconds - time_remaining_seconds
            
            return {
                "is_powerplay": True,
                "team": pp_team,  # Team on power play (correct team)
                "time_remaining": time_remaining_seconds,  # Time remaining on PP (correctly calculated)
                "time_elapsed": time_elapsed,  # Time elapsed on PP
                "team_logo": team_logo or None,
                "strength": strength  # e.g., "5 on 4"
            }
        else:
            return {
                "is_powerplay": False,
                "team": None,
                "time_remaining": None,
                "team_logo": None
            }
    
    except Exception as e:
        print(f"[gateway] Error getting power play status: {e}")
        return {
            "is_powerplay": False,
            "team": None,
            "time_remaining": None,
            "team_logo": None
        }
