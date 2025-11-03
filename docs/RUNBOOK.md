# RUNBOOK.md (initial)

- Restart a stuck consumer:
  - `docker compose restart feature_state` (or model_svc/ingestor).
- Observe lag:
  - Use `XLEN events` / `features` / `predictions` to sanity check growth.
- Clear local data:
  - `docker compose down -v` to reset Redis and streams.
