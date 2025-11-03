# GameCast++ (Python-first)

Real-time NHL win-probability & micro-markets **demo** in Python using **Redis Streams** for the event bus
(you can swap to Kafka later). This scaffold gives you a working local pipeline:

`ingestor → feature_state → model_svc → gateway(REST+WebSocket)`

### Quick start
```bash
# 1) From repo root:
docker compose up --build

# 2) Open API docs for the gateway:
#    http://localhost:8000/docs

# 3) Watch live predictions:
#    curl http://localhost:8000/v1/games/TEST_GAME/winprob

# 4) WebSocket stream (in a new terminal):
#    websocat ws://localhost:8000/v1/stream/TEST_GAME
#    (or use any WS client)
```
The ingestor generates a **synthetic game** (`game_id=TEST_GAME`) with goals/shot events.
The model produces a toy probability so the whole flow works out-of-the-box.

### Services
- **ingestor** — synthesizes play-by-play events → Redis Stream `events`
- **feature_state** — consumes `events`, maintains game state, emits derived `features`
- **model_svc** — consumes `features`, computes `predictions` + publishes WS broadcast
- **gateway** — REST + WebSocket; serves `/v1/games/:id/winprob` and `/v1/stream/:gameId`

### Swap to Kafka later
Start here with Redis Streams for simplicity. You can replace the bus in `*-bus.py` files with
Kafka (aiokafka/Faust) and keep service boundaries identical.

---
**Folders:** see `services/` and `infra/`. Dashboards/metrics/TimescaleDB are easy extensions.
