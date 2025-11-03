import asyncio
import json
import os
import random
import subprocess
import time
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
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
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

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

@app.get("/")
async def root():
    """Serve the main web interface"""
    static_file = os.path.join(static_dir, "index.html")
    if os.path.exists(static_file):
        return FileResponse(static_file)
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
    import time
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
                except:
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

@app.get("/v1/games")
async def list_games(date: str = None):
    """List NHL games for a specific date (YYYY-MM-DD) or today if not specified"""
    try:
        schedule = await fetch_nhl_daily_schedule(date)
        
        games = []
        games_list = schedule.get("games", []) if isinstance(schedule, dict) else []
        
        for game in games_list:
            if isinstance(game, dict):
                # Get team names
                away_team = game.get("awayTeam", {})
                home_team = game.get("homeTeam", {})
                
                # Format game time
                start_time = game.get("startTimeUTC", "")
                game_time = ""
                if start_time:
                    try:
                        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                        # Convert to local time and format
                        game_time = dt.strftime("%I:%M %p")
                    except:
                        game_time = start_time
                
                games.append({
                    "game_id": str(game.get("id", "")),
                    "away_team": away_team.get("abbrev", ""),
                    "away_team_name": away_team.get("commonName", {}).get("default", ""),
                    "away_team_logo": away_team.get("logo", ""),
                    "home_team": home_team.get("abbrev", ""),
                    "home_team_name": home_team.get("commonName", {}).get("default", ""),
                    "home_team_logo": home_team.get("logo", ""),
                    "venue": game.get("venue", {}).get("default", ""),
                    "game_time": game_time,
                    "start_time_utc": start_time,
                    "game_state": game.get("gameState", ""),
                    "away_score": game.get("awayScore", 0) if "awayScore" in game else away_team.get("score", 0),
                    "home_score": game.get("homeScore", 0) if "homeScore" in game else home_team.get("score", 0),
                })
        
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
        p_home = float(data["p_home_win"])
        p_away = 1.0 - p_home
        
        # Get current score
        state_key = f"state:{game_id}"
        state = await r.hgetall(state_key)
        
        home_score = int(state.get("home_score", 0))
        away_score = int(state.get("away_score", 0))
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
        
        # Get team names from cache or NHL API
        home_team = await r.get(f"game:{game_id}:home_team")
        away_team = await r.get(f"game:{game_id}:away_team")
        
        if not home_team or not away_team:
            # Cache miss - fetch from NHL API
            try:
                game_data = nhl_client.game_center.play_by_play(game_id)
                if game_data:
                    away_team = game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away Team")
                    home_team = game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home Team")
                    # Cache team names for 24 hours
                    await r.setex(f"game:{game_id}:home_team", 86400, home_team)
                    await r.setex(f"game:{game_id}:away_team", 86400, away_team)
                else:
                    away_team = "Away Team"
                    home_team = "Home Team"
            except Exception:
                # Fallback to hardcoded for known games
                if game_id == "2024020589":
                    home_team = "Capitals"
                    away_team = "Bruins"
                elif game_id == "TEST_GAME":
                    home_team = "Home Team"
                    away_team = "Away Team"
                else:
                    home_team = "Home Team"
                    away_team = "Away Team"
                # Cache fallback values
                await r.setex(f"game:{game_id}:home_team", 86400, home_team)
                await r.setex(f"game:{game_id}:away_team", 86400, away_team)
        
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
        
        return {
            "game": {
                "id": game_id,
                "matchup": f"{away_team} @ {home_team}",
                "favorite": favorite
            },
            "score": {
                "home": {
                    "team": home_team,
                    "goals": home_score
                },
                "away": {
                    "team": away_team,
                    "goals": away_score
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

@app.get("/v1/games/{game_id}/playbyplay")
async def get_playbyplay(game_id: str, limit: int = 30):
    """Get play-by-play events for a game directly from NHL API"""
    r = app.state.redis
    
    try:
        # Fetch play-by-play directly from NHL API for accurate data
        game_data = await fetch_nhl_play_by_play(game_id)
        if not game_data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")
        
        # Get team info
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        home_team = game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home Team")
        away_team = game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away Team")
        
        # Cache team names
        await r.setex(f"game:{game_id}:home_team", 86400, home_team)
        await r.setex(f"game:{game_id}:away_team", 86400, away_team)
        
        # Get plays from API
        plays = game_data.get("plays", [])
        if not plays:
            return {
                "game_id": game_id,
                "home_team": home_team,
                "away_team": away_team,
                "events": []
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
        }
        
        # Collect all unique player IDs for batch lookup
        player_ids = set()
        processed_plays = []
        
        for play in plays:
            type_code = play.get("typeCode")
            if type_code in [520, 516, 517, 524]:  # Skip period-start, stoppage, period-end, game-end
                continue
            
            # Only process GOAL (505) and PENALTY (509) events
            if type_code not in [505, 509]:
                continue
            
            mapped_type = type_mapping.get(type_code, "SHOT")
            details = play.get("details", {})
            
            # Extract player IDs for goals
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
            
            processed_plays.append(play)
        
        # Batch fetch player names
        player_names = await get_player_names_batch(list(player_ids), r) if player_ids else {}
        
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
                team = "HOME" if play.get("homeTeamDefendingSide") == "right" else "AWAY"
            
            # Get player info
            player_id = None
            assist1_player_id = None
            assist2_player_id = None
            assist1_name = None
            assist2_name = None
            
            if mapped_type == "GOAL":
                player_id = details.get("scoringPlayerId")
                assist1_player_id = details.get("assist1PlayerId")
                assist2_player_id = details.get("assist2PlayerId")
                # Get player names from batch lookup
                player_name = player_names.get(player_id) if player_id else None
                assist1_name = player_names.get(assist1_player_id) if assist1_player_id else None
                assist2_name = player_names.get(assist2_player_id) if assist2_player_id else None
                
                # If batch lookup returned None, try individual fetch
                if player_id and not player_name:
                    player_name = await get_player_name(player_id, r)
                if assist1_player_id and not assist1_name:
                    assist1_name = await get_player_name(assist1_player_id, r)
                if assist2_player_id and not assist2_name:
                    assist2_name = await get_player_name(assist2_player_id, r)
                    
            elif mapped_type == "PENALTY":
                player_id = details.get("committedByPlayerId")
                player_name = player_names.get(player_id) if player_id else None
                if player_id and not player_name:
                    player_name = await get_player_name(player_id, r)
            else:
                player_name = None
            
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
                except:
                    timestamp = time.time()
            else:
                timestamp = time.time()
            
            # Format descriptive event description
            event_desc = mapped_type
            
            if mapped_type == "GOAL":
                # Get shot type and build descriptive goal description
                shot_type = details.get("shotType", "").lower()
                scoring_player_total = details.get("scoringPlayerTotal", 0)
                
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
                
                # Build goal description
                # Format: "10' game-tying tip-in goal" or "2nd goal snap shot goal"
                if scoring_player_total > 0:
                    event_desc = f"{scoring_player_total}' {game_situation}{shot_desc} goal"
                else:
                    event_desc = f"{game_situation}{shot_desc} goal"
                
                # Add assists if available
                assists = []
                if assist1_name:
                    assists.append(assist1_name)
                if assist2_name:
                    assists.append(assist2_name)
                
                if assists:
                    assist_text = ", ".join(assists)
                    event_desc += f" (assists: {assist_text})"
                    
            elif mapped_type == "PENALTY":
                # Get penalty details
                penalty_type = details.get("typeCode", "")  # MAJ or MIN
                desc_key = details.get("descKey", "").lower()  # fighting, slashing, etc.
                duration = details.get("duration", 0)
                
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
            
            # Add event
            event_data = {
                "id": f"{game_id}-{play.get('eventId', len(events))}",
                "timestamp": timestamp,
                "event_type": mapped_type,
                "description": event_desc,
                "player": player_name,
                "player_id": player_id,
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
        
        # Keep chronological order (oldest first) - events are already in correct order from API
        # Reverse only for display (most recent first)
        events.reverse()
        
        return {
            "game_id": game_id,
            "home_team": home_team,
            "away_team": away_team,
            "events": events[:limit]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching play-by-play: {str(e)}")

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
