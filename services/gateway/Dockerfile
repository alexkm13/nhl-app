FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install main dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install test dependencies (optional, can be skipped in production)
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt || true

# Copy application code (explicitly copy important directories/files)
COPY main.py .
COPY models.py .
COPY utils.py .
COPY nhl_api.py .
COPY player_utils.py .
COPY event_helpers.py .
COPY pytest.ini .

# Copy routes directory
COPY routes/ ./routes/

# Copy static files
COPY static/ ./static/

# Copy tests directory (needed for test service)
COPY tests/ ./tests/

# Default command runs the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
