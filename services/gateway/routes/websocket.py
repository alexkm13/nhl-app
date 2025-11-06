"""WebSocket API routes."""

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

router = APIRouter(prefix="/v1", tags=["websocket"])


# Import WS_CONNECTIONS from main
def get_ws_connections():
    """Get WS_CONNECTIONS gauge from main."""
    from main import WS_CONNECTIONS

    return WS_CONNECTIONS


# Helper function to get app state
def get_redis() -> Redis:
    """Get Redis instance from app state."""
    from main import app

    return app.state.redis


@router.websocket("/stream/{game_id}")
async def stream_game(ws: WebSocket, game_id: str):
    await ws.accept()
    WS_CONNECTIONS = get_ws_connections()
    WS_CONNECTIONS.inc()
    r = get_redis()
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
