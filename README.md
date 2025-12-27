# ScoreCast 🏒

**Real-time NHL win probability predictions powered by machine learning**

Have you ever wished you could see live win probability predictions for NHL games, just like ESPN does for football? Want to know the odds in real-time as goals are scored, penalties are called, and momentum shifts? Look no further!

ScoreCast is a production-ready microservices system that processes live NHL game events through Redis Streams, computes win probabilities using ML models, and serves them via REST APIs and WebSocket streams. Built with Python, FastAPI, and designed for horizontal scaling.

![ScoreCast Dashboard](https://via.placeholder.com/800x400?text=ScoreCast+Dashboard)

## 🌟 Features

- **Real-time predictions** - Sub-100ms win probability updates as game events occur
- **Live WebSocket streaming** - Push updates to clients instantly
- **Microservices architecture** - Horizontally scalable event processing pipeline
- **ML-powered** - LightGBM models trained on historical NHL data
- **Production-ready** - Prometheus metrics, Grafana dashboards, health checks
- **Event-driven** - Redis Streams with consumer groups for reliable processing

## 📀 Installation

### Quick Start with Docker

The easiest way to get started:

```bash
# Clone the repository
git clone https://github.com/alexkm13/nhl-app.git
cd nhl-app

# Start all services
make up
# or: docker compose up --build
```

The system will automatically:
- Start Redis, TimescaleDB, Prometheus, and Grafana
- Build and run all microservices (ingestor, feature_state, model_svc, gateway)
- Begin processing game events and generating predictions

### For Local Development

```bash
# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # For linting/testing

# Run services individually
python -m services.gateway.main
python -m services.ingestor.main
python -m services.feature_state.main
python -m services.model_svc.main
```

## 🎮 Usage

### Get Win Probability for a Game

```bash
curl http://localhost:8000/v1/games/2025020161/winprob
```

**Response:**
```json
{
  "game_id": "2025020161",
  "p_home_win": 0.6234,
  "model_id": "lightgbm_20251104_121934_d9b5b03f",
  "ts": 1699123456.78
}
```

### Services

- **Ingestor** - Fetches NHL API data and publishes events to Redis Streams
- **Feature State** - Maintains game state (score, strength, time) and computes 27+ features
- **Model Service** - Runs ML inference to generate win probability predictions
- **Gateway** - FastAPI server providing REST endpoints and WebSocket streaming

## 📊 Monitoring

### Prometheus Metrics

- Request latency histograms
- Total predictions produced
- WebSocket connection count
- Event processing throughput

Access at: http://localhost:9090

### Grafana Dashboards

Pre-configured dashboards show:
- Request rates and latency
- Event processing throughput
- Model prediction accuracy
- Service health

Access at: http://localhost:3000 (login: `admin/admin`)

## 🔧 Configuration

Environment variables can be set in `.env` file:

```bash
# Database
DATABASE_URL=postgresql://postgres:postgres@timescaledb:5432/gamecast

# Redis
REDIS_URL=redis://redis:6379/0

# Model
MODEL_ID=lightgbm_20251104_121934_d9b5b03f

# A/B Testing (optional)
AB_TEST_ENABLED=false
AB_TEST_CONFIG='{"variants": [...]}'
```

## 📦 Dependencies

### Core
- **fastapi** - Modern async web framework
- **redis** - Streams for event processing
- **psycopg** - PostgreSQL/TimescaleDB driver
- **numpy** - Numerical computations
- **lightgbm** - ML model inference

### Dev Dependencies
- **pytest** - Testing framework
- **ruff** - Fast Python linter
- **black** - Code formatter
- **mypy** - Type checking


## 📜 License

MIT License - See LICENSE file for details

_Disclaimer: Not affiliated with the NHL._

## 🤝 Contributing

Contributions welcome! Feel free to:
- Open issues for bugs or feature requests
- Submit pull requests
- Improve documentation

## 📧 Contact

Questions? Open an issue on GitHub!

---

**If you like what you see, consider giving it a star ⭐**
