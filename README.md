# GameCast++ 

> Real-time NHL win probability prediction system with microservices architecture

GameCast++ is a production-ready streaming system that processes live NHL game events through a microservices pipeline, computing win probabilities in real-time using machine learning models.

## Features

- **Real-time streaming** using Redis Streams for high-throughput event processing
- **Microservices architecture** with horizontal scaling support
- **REST & WebSocket APIs** for live win probability predictions
- **Observability** with Prometheus metrics and Grafana dashboards
- **Time-series storage** with TimescaleDB for historical analysis
- **Event-driven design** with back-pressure handling and consumer groups

## Architecture

```
┌──────────┐     ┌──────────────┐     ┌───────────┐     ┌─────────┐
│ Ingestor │───▶ │Feature State │───▶ │ Model Svc │───▶ │ Gateway │
│          │     │              │     │           │     │         │
│ - XADD   │     │ - XREADGROUP │     │ - Predict │     │ - REST  │
│ events   │     │ - XADD       │     │ - PUBLISH │     │ - WS    │
└──────────┘     └──────────────┘     └───────────┘     └─────────┘
     │                   │                   │                 │
     └───────────────────┴───────────────────┴─────────────────┘
                                │
                        ┌───────▼────────┐
                        │ Redis Streams  │
                        └────────────────┘
```

### Services Overview

| Service | Purpose | Technology |
|---------|---------|------------|
| **Ingestor** | Generates synthetic NHL game events | Python, Redis XADD |
| **Feature State** | Maintains game state, derives features | Python, Redis Streams |
| **Model Service** | Computes win probabilities | Python, NumPy, Machine Learning |
| **Gateway** | REST API & WebSocket streaming | FastAPI, Uvicorn |
| **TimescaleDB** | Historical data storage | PostgreSQL extension |
| **Prometheus** | Metrics collection | Time-series DB |
| **Grafana** | Dashboards & visualization | Analytics platform |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)

### Installation & Run

```bash
# Clone the repository
git clone git@github.com:alexkm13/nhl-app.git
cd nhl-app

# Start all services
make up
# or: docker compose up --build

# Check service health
docker compose logs -f --tail=50
```

The system will automatically:
1. Start Redis, TimescaleDB, Prometheus, and Grafana
2. Build and run all microservices
3. Generate synthetic game events for `TEST_GAME`
4. Compute and broadcast win probabilities

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| **API Gateway** | http://localhost:8000 | REST API & WebSocket |
| **API Docs** | http://localhost:8000/docs | Interactive Swagger UI |
| **Prometheus** | http://localhost:9090 | Metrics endpoint |
| **Grafana** | http://localhost:3000 | Dashboards (`admin/admin`) |

## 📖 API Usage

### Get Latest Win Probability

```bash
curl http://localhost:8000/v1/games/TEST_GAME/winprob
```

**Response:**
```json
{
  "game_id": "TEST_GAME",
  "p_home_win": 0.6234,
  "model_id": "baseline-logit-v0",
  "ts": 1699123456.78
}
```

### WebSocket Live Stream

```bash
# Using websocat
websocat ws://localhost:8000/v1/stream/TEST_GAME

# Or connect from your app
const ws = new WebSocket('ws://localhost:8000/v1/stream/TEST_GAME');
ws.onmessage = (event) => {
  const prediction = JSON.parse(event.data);
  console.log('Win probability:', prediction.p_home_win);
};
```

### API Documentation

- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- See [docs/API.md](docs/API.md) for detailed API specs

## Testing & Development

```bash
# Run services
make up

# View logs
make logs

# Format code
make fmt

# Lint code
make lint

# Clean up
make down

# Test locally (without Docker)
pip install -r requirements.txt
python -m services.gateway.main  # Run gateway locally
```

## Monitoring

### Prometheus Metrics

- Request latency histograms
- Total predictions produced
- WebSocket connection count
- Processing time per event

Access at: http://localhost:9090

### Grafana Dashboards

Pre-configured dashboards show:
- Request rates and latency
- Event processing throughput
- Model prediction accuracy
- Service health

Access at: http://localhost:3000 (login: `admin/admin`)

## Project Structure

```
nhl-app/
├── services/
│   ├── gateway/          # REST API & WebSocket server
│   ├── ingestor/         # Event producer
│   ├── feature_state/    # State management
│   └── model_svc/        # ML predictions
├── infra/
│   ├── docker-compose.yaml   # Orchestration
│   ├── prometheus/            # Metrics config
│   ├── grafana/              # Dashboard config
│   └── timescaledb/          # DB schema
├── docs/
│   ├── API.md           # API documentation
│   ├── DESIGN.md        # Architecture design
│   ├── RUNBOOK.md       # Operations guide
│   └── BENCHMARK.md     # Performance benchmarks
├── Makefile             # Common commands
└── requirements.txt     # Python dependencies
```

## Data Flow

1. **Ingestor** generates synthetic NHL game events (goals, shots, penalties)
2. **Feature State** processes events, maintains score/strength state
3. **Model Service** computes win probability from game state
4. **Gateway** serves predictions via REST (cached) and WebSocket (live)

### Redis Streams

- `events` → Raw play-by-play events
- `features` → Derived state snapshots  
- `predictions` → Model outputs

Each service uses consumer groups for horizontal scaling and back-pressure handling.

## 🔌 Production Considerations

### Scaling

```yaml
# Scale individual services
docker compose up --scale feature_state=3 --scale model_svc=2
```

### Migration to Kafka

The system is designed to swap Redis Streams for Kafka without changing service logic:

```python
# Replace Redis Streams with aiokafka
# Same consumer group semantics apply
```

### Security

- Add HMAC token validation in gateway
- TLS termination at load balancer
- Database connection pooling
- Rate limiting per client

## Documentation

- [Architecture Design](docs/DESIGN.md) - System design & patterns
- [API Reference](docs/API.md) - Endpoint specifications
- [Runbook](docs/RUNBOOK.md) - Operations & troubleshooting
- [Benchmarks](docs/BENCHMARK.md) - Performance profiles

## Technology Stack

- **Language:** Python 3.11+
- **Streaming:** Redis Streams (can swap to Kafka)
- **API:** FastAPI, Uvicorn
- **Database:** TimescaleDB (PostgreSQL)
- **ML:** NumPy, scikit-learn (extensible)
- **Observability:** Prometheus, Grafana
- **Orchestration:** Docker Compose

## 📈 Next Steps

- [ ] Production-grade ML model training pipeline
- [ ] Real NHL data integration
- [ ] Advanced betting market calculations
- [ ] A/B testing framework for models
- [ ] Multi-tenant isolation
- [ ] CI/CD with automated testing

## 📄 License

MIT License - See LICENSE file for details

