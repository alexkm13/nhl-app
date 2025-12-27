import logging
import os
import re
import sys
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

# Add parent directory to path for common imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from common.constants import (
    REDIS_DEFAULT_URL,
    PROMETHEUS_LATENCY_BUCKETS,
    CORS_ALLOW_ALL,
)
from common.logging_config import setup_logger
from common.health import check_redis_health, create_health_response
from common.rate_limiter import RateLimitMiddleware
from common.api_key_middleware import APIKeyMiddleware, get_api_key_middleware_config
from db_pool import init_db_pool, close_db_pool
from routes.games import router as games_router
from routes.playbyplay import router as playbyplay_router
from routes.standings import router as standings_router
from routes.websocket import router as websocket_router

# Configure logging
logger = setup_logger("gateway", level=logging.INFO)

REDIS_URL = os.environ.get("REDIS_URL", REDIS_DEFAULT_URL)
# DATABASE_URL should fail fast if not set properly (empty string can cause silent failures)
DATABASE_URL = os.environ.get("DATABASE_URL", None)
app = FastAPI(title="GameCast++ Gateway", version="1.0.0")

# Add CORS middleware
# Get allowed origins from environment variable or use wildcard for development
CORS_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", CORS_ALLOW_ALL)
allowed_origins = [origin.strip() for origin in CORS_ORIGINS.split(",")] if CORS_ORIGINS != CORS_ALLOW_ALL else [CORS_ALLOW_ALL]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Add API key authentication middleware (if enabled)
api_key_enabled, api_keys = get_api_key_middleware_config()
if api_key_enabled:
    app.add_middleware(APIKeyMiddleware, enabled=True, api_keys=api_keys)
    logger.info(f"API key authentication enabled with {len(api_keys)} key(s)")
else:
    logger.info("API key authentication disabled")

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
    buckets=PROMETHEUS_LATENCY_BUCKETS,
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


@app.get("/health")
async def health():
    """
    Health check endpoint.

    Returns service health status and dependency checks.
    """
    redis_status = await check_redis_health(REDIS_URL)

    health_response = create_health_response(
        service_name="gateway",
        version="1.0.0",
        redis_status=redis_status,
    )

    return health_response


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@app.on_event("startup")
async def startup():
    """Initialize resources on startup."""
    app.state.redis = Redis.from_url(REDIS_URL, decode_responses=True)

    # Initialize database connection pool
    if DATABASE_URL:
        await init_db_pool(DATABASE_URL, min_size=2, max_size=10)

    logger.info("Gateway service started")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup resources on shutdown."""
    await app.state.redis.aclose()

    # Close database connection pool
    await close_db_pool()

    logger.info("Gateway service shutting down")
