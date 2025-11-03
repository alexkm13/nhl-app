import asyncio
import json
import os
import random
import subprocess
from datetime import datetime

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from nhlpy import NHLClient
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
app = FastAPI(title="GameCast++ Gateway")

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize NHL client
nhl_client = NHLClient()

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
        nhl_client = NHLClient()
        
        # Clear old data for this game
        await redis.delete(f"events:{game_id}")
        # Clear game state and predictions to prevent accumulation
        await redis.delete(f"state:{game_id}")
        await redis.delete(f"pred:{game_id}")
        # Set a flag to signal feature_state to reset this game's state
        await redis.setex(f"reset_game:{game_id}", 60, "1")  # Expires in 60 seconds
        
        # Fetch and process game data
        game_data = nhl_client.game_center.play_by_play(game_id)
        if not game_data:
            await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
            await redis.hset(f"ingestion_status:{game_id}", "error", "No game data found")
            return
        
        plays = game_data.get("plays", [])
        if not plays:
            await redis.hset(f"ingestion_status:{game_id}", "status", "failed")
            await redis.hset(f"ingestion_status:{game_id}", "error", "No plays found")
            return
        
        # Get team IDs
        home_team_id = game_data.get("homeTeam", {}).get("id")
        away_team_id = game_data.get("awayTeam", {}).get("id")
        
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
            if type_code in ["520", "516", "517"]:  # period-start, stoppage, period-end
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
                        if away_skaters <= 3:
                            strength = "ENPP"  # Empty net + power play (definite penalty situation)
                        else:
                            strength = "EN"  # Empty net even strength (6v5 or 6v4)
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
                        if home_skaters <= 3:
                            strength = "ENPP"  # Empty net + power play (definite penalty situation)
                        else:
                            strength = "EN"  # Empty net even strength (6v5 or 6v4)
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
            
            # Get coordinates
            import random
            x = details.get("xCoordInFeet", random.uniform(-100, 100))
            y = details.get("yCoordInFeet", random.uniform(-42.5, 42.5))
            
            # Create event
            event = {
                "game_id": game_id,
                "ts": timestamp,
                "team": team,
                "event_type": mapped_type,
                "strength": strength,
                "empty_net": empty_net,
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
async def list_games():
    """List today's NHL games"""
    try:
        schedule = nhl_client.schedule.daily_schedule()
        
        games = []
        if isinstance(schedule, dict) and "games" in schedule:
            schedule = schedule["games"]
        elif isinstance(schedule, dict) and "gameWeek" in schedule:
            schedule = schedule["gameWeek"][0].get("games", []) if schedule["gameWeek"] else []
        
        for game in schedule:
            if isinstance(game, dict):
                games.append({
                    "game_id": str(game.get("id", "")),
                    "away_team": game.get("awayTeam", {}).get("abbrev", ""),
                    "home_team": game.get("homeTeam", {}).get("abbrev", ""),
                    "venue": game.get("venue", {}).get("default", ""),
                    "game_time": game.get("startTimeUTC", ""),
                    "game_state": game.get("gameState", ""),
                })
        
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
        game_data = nhl_client.game_center.play_by_play(game_id)
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
        
        # Get team names dynamically from NHL API
        try:
            game_data = nhl_client.game_center.play_by_play(game_id)
            if game_data:
                away_team = game_data.get("awayTeam", {}).get("commonName", {}).get("default", "Away Team")
                home_team = game_data.get("homeTeam", {}).get("commonName", {}).get("default", "Home Team")
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
                "last_event": last_event
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
