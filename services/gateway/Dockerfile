FROM python:3.11-slim

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Note: This Dockerfile is optimized for production builds
# For development with live file updates, use docker-compose.override.yml
# to mount local directories as volumes

# Copy and install Python dependencies
# Copy requirements first for better layer caching
COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install test dependencies (optional, can be skipped in production)
COPY services/gateway/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt || true

# Copy common module (shared across services)
COPY common/ ./common/

# Copy all application code and files
# Grouped to ensure changes are detected while maintaining cache efficiency
COPY services/gateway/main.py \
     services/gateway/models.py \
     services/gateway/utils.py \
     services/gateway/nhl_api.py \
     services/gateway/player_utils.py \
     services/gateway/event_helpers.py \
     services/gateway/db_pool.py \
     services/gateway/pytest.ini \
     ./

# Copy routes directory (copy all Python files to ensure changes are detected)
COPY services/gateway/routes/ ./routes/

# Copy static files LAST to ensure any static file change invalidates cache from this point
# This is important so static file updates are immediately reflected
COPY services/gateway/static/ ./static/

# Copy tests directory (needed for test service)
COPY services/gateway/tests/ ./tests/

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Default command runs the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
