FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Copy service-specific requirements and install dependencies
COPY services/feature_state/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy common module (shared across services)
COPY common/ ./common/

# Copy service-specific files
COPY services/feature_state/ ./

CMD ["python", "main.py"]
