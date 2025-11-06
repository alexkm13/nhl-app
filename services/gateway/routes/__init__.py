"""Routes package for gateway service."""
from .games import router as games_router
from .playbyplay import router as playbyplay_router
from .standings import router as standings_router
from .websocket import router as websocket_router

__all__ = ["games_router", "playbyplay_router", "standings_router", "websocket_router"]

