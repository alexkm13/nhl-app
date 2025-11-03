import json
import os

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
app = FastAPI(title="GameCast++ Gateway")

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

@app.on_event("startup")
async def startup():
    app.state.redis = Redis.from_url(REDIS_URL, decode_responses=True)

@app.on_event("shutdown")
async def shutdown():
    await app.state.redis.aclose()

@app.get("/v1/games/{game_id}/winprob", response_model=WinProb)
async def get_winprob(game_id: str):
    r = app.state.redis
    key = f"pred:{game_id}"
    data = await r.hgetall(key)
    if not data:
        raise HTTPException(status_code=404, detail="No prediction yet for this game")
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
        raise HTTPException(status_code=404, detail="No prediction yet for this game")
    
    try:
        p_home = float(data["p_home_win"])
        p_away = 1.0 - p_home
        
        # Get current score
        state_key = f"state:{game_id}"
        state = await r.hgetall(state_key)
        
        home_score = int(state.get("home_score", 0))
        away_score = int(state.get("away_score", 0))
        strength = state.get("strength", "EV")
        last_event = state.get("last_event", "Unknown")
        
        # Get team names for this game
        home_team = "Colorado Avalanche"
        away_team = "Minnesota Wild"
        
        # Format strength
        strength_names = {
            "EV": "Even Strength (5v5)",
            "PP": "Power Play",
            "PK": "Shorthanded"
        }
        
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
                "strength": strength_names.get(strength, strength),
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
