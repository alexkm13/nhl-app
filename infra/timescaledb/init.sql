-- Enable TimescaleDB & create hypertables
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- events table (if you later insert events)
CREATE TABLE IF NOT EXISTS events (
  ts TIMESTAMPTZ NOT NULL,
  game_id TEXT NOT NULL,
  team TEXT NOT NULL,
  event_type TEXT NOT NULL,
  strength TEXT NOT NULL,
  x DOUBLE PRECISION,
  y DOUBLE PRECISION,
  shot_quality DOUBLE PRECISION
);
SELECT create_hypertable('events', by_range('ts'), if_not_exists => TRUE);

-- features snapshots
CREATE TABLE IF NOT EXISTS features (
  ts TIMESTAMPTZ NOT NULL,
  game_id TEXT NOT NULL,
  home_score INT NOT NULL,
  away_score INT NOT NULL,
  strength TEXT NOT NULL,
  last_event TEXT NOT NULL
);
SELECT create_hypertable('features', by_range('ts'), if_not_exists => TRUE);

-- predictions
CREATE TABLE IF NOT EXISTS predictions (
  ts TIMESTAMPTZ NOT NULL,
  game_id TEXT NOT NULL,
  model_id TEXT NOT NULL,
  p_home_win DOUBLE PRECISION NOT NULL
);
SELECT create_hypertable('predictions', by_range('ts'), if_not_exists => TRUE);

-- simple retention policy (optional)
-- SELECT add_retention_policy('events', INTERVAL '30 days', if_not_exists => TRUE);
