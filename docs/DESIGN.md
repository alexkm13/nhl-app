# DESIGN.md (initial)

## Overview
A minimal streaming pipeline using **Redis Streams** as the bus:
`ingestor (XADD events) → feature_state (XREADGROUP events → XADD features) → model_svc (XREADGROUP features → XADD predictions & PUBLISH) → gateway (serves REST & WS).`

- **Idempotency:** Stream IDs act as message IDs; each service acks after durable write.
- **Back-pressure:** `XREADGROUP BLOCK` controls pull; each service scales horizontally with its consumer group.
- **Hot state:** Latest prediction per game is cached in Redis `pred:GAME_ID` for fast REST.
- **WS fan-out:** model_svc also `PUBLISH`es to `pred_stream:GAME_ID` for live clients.

## Streams
- `events` → raw play-by-play events
- `features` → derived features/state snapshots
- `predictions` → model outputs

## Keys
- `state:GAME_ID` (hash) — current score, strength, clock
- `pred:GAME_ID` (hash) — last prediction `{p_home_win, model_id, ts}`

## Security & SLOs (next steps)
- Signed client tokens (HMAC) in gateway.
- SLOs: p95 REST < 50ms (cached), WS broadcast < 150ms. Prom + Grafana to be added.
