import os
import re
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from redis.asyncio import Redis

from routes.games import router as games_router
from routes.playbyplay import router as playbyplay_router
from routes.standings import router as standings_router
from routes.websocket import router as websocket_router

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
    # Custom static file handler with no-cache headers
    class NoCacheStaticFiles(StaticFiles):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        async def __call__(self, scope, receive, send):
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = dict(message.get("headers", []))
                    # Add no-cache headers
                    headers[b"cache-control"] = (
                        b"no-cache, no-store, must-revalidate, max-age=0"
                    )
                    headers[b"pragma"] = b"no-cache"
                    headers[b"expires"] = b"0"
                    message["headers"] = list(headers.items())
                await send(message)

            await super().__call__(scope, receive, send_wrapper)

    app.mount("/static", NoCacheStaticFiles(directory=static_dir), name="static")

# NHL API base URL (kept for backward compatibility)
NHL_API_BASE = "https://api-web.nhle.com/v1"


@app.get("/favicon.ico")
async def favicon():
    """Return 204 No Content for favicon requests to suppress 404 errors"""
    return Response(status_code=204)


@app.get("/")
async def root():
    """Serve the main web interface"""
    static_file = os.path.join(static_dir, "index.html")
    if os.path.exists(static_file):
        with open(static_file, "r", encoding="utf-8") as f:
            content = f.read()
        # Add cache-busting timestamp to script tags and CSS
        timestamp = int(time.time())
        # Replace CSS references with versioned ones (handle both v= and v=number formats)
        content = re.sub(
            r"/static/styles\.css(\?v=\d+)?",
            f"/static/styles.css?v={timestamp}",
            content,
        )
        # Replace any other static asset references
        content = re.sub(
            r'/static/([^"\']+\.(css|js))(\?v=\d+)?',
            rf"/static/\1?v={timestamp}",
            content,
        )
        # Add cache-busting comment to force browser refresh
        content = content.replace("</html>", f"<!-- Cache bust: {timestamp} --></html>")
        return Response(
            content=content,
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0, private",
                "Pragma": "no-cache",
                "Expires": "0",
                "Vary": "Accept-Encoding",
                "X-Content-Type-Options": "nosniff",
            },
        )
    return {"message": "NHL Game Predictor API", "docs": "/docs"}


# Prometheus metrics
REQUESTS = Counter(
    "gateway_requests_total", "Total HTTP requests", ["path", "method", "status"]
)
LATENCY = Histogram(
    "gateway_request_latency_seconds",
    "Request latency",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2],
)
WS_CONNECTIONS = Gauge("gateway_ws_connections", "Current websocket connections")


@app.middleware("http")
async def metrics_middleware(request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    LATENCY.observe(time.perf_counter() - start)
    try:
        REQUESTS.labels(
            path=request.url.path, method=request.method, status=response.status_code
        ).inc()
    except Exception:
        REQUESTS.labels(
            path=str(request.url.path),
            method=request.method,
            status=getattr(response, "status_code", 0),
        ).inc()
    return response


# Register routers
app.include_router(games_router)
app.include_router(playbyplay_router)
app.include_router(standings_router)
app.include_router(websocket_router)


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
