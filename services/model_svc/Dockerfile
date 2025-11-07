FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install system dependencies for LightGBM
RUN apt-get update && apt-get install -y \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy service-specific requirements and install dependencies
COPY services/model_svc/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy common module (shared across services)
COPY common/ ./common/

# Copy service-specific files
COPY services/model_svc/ ./

CMD ["python", "main.py"]
