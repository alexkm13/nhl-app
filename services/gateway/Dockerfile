FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install main dependencies
COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install test dependencies (optional, can be skipped in production)
COPY services/gateway/requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt || true

# Copy common module (shared across services)
COPY common/ ./common/

# Copy application code (explicitly copy important directories/files)
COPY services/gateway/main.py .
COPY services/gateway/models.py .
COPY services/gateway/utils.py .
COPY services/gateway/nhl_api.py .
COPY services/gateway/player_utils.py .
COPY services/gateway/event_helpers.py .
COPY services/gateway/pytest.ini .

# Copy routes directory
COPY services/gateway/routes/ ./routes/

# Copy static files
COPY services/gateway/static/ ./static/

# Copy tests directory (needed for test service)
COPY services/gateway/tests/ ./tests/

# Default command runs the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
