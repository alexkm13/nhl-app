# Model Service Verification Guide

This guide helps you verify if the LightGBM model service is running and generating predictions.

## Quick Checks

### 1. Check if Docker Containers are Running

```bash
docker compose ps
```

Look for:
- `model_svc` - should be running
- `gateway` - should be running  
- `redis` - should be running
- `feature_state` - should be running

### 2. Check Model Service Logs

```bash
docker compose logs model_svc --tail=50
```

Look for:
- ✅ `[model_svc] Loaded lightgbm model: lightgbm_20251104_215914_53104e84`
- ✅ `[model_svc] {mid} -> pred id={sid} game={game_id} p_home={p_home_win:.4f}`
- ❌ Any error messages about model loading or prediction failures

### 3. Check for Predictions in Redis

```bash
docker compose exec redis redis-cli
```

Then in Redis CLI:
```redis
# Check for prediction keys
KEYS pred:*

# Check a specific game's prediction
HGETALL pred:2025020161

# Check predictions stream length
XLEN predictions

# Get latest predictions
XREVRANGE predictions COUNT 5
```

### 4. Check Gateway Logs for Fallback Warnings

```bash
docker compose logs gateway --tail=50 | grep "falling back"
```

If you see warnings like:
```
[gateway] No model prediction available for game {game_id}, falling back to calculated probability
```

This means the model service is NOT generating predictions for that game.

### 5. Check if Features are Being Generated

```bash
docker compose exec redis redis-cli XLEN features
```

If this returns `0`, then no features are being generated, which means no predictions can be made.

### 6. Test the API Endpoint

```bash
curl http://localhost:8000/v1/games/2025020161/winprob/friendly
```

Check the response for:
- `model_id` field - should show the LightGBM model ID (e.g., `lightgbm_20251104_215914_53104e84`)
- If it's missing, the model service may not be running

### 7. Run the Python Verification Script

```bash
# Make sure redis package is installed
pip install redis

# Run the verification script
python3 check_model_service.py
```

## Troubleshooting

### Model Service Not Running

If `docker compose ps` shows `model_svc` as not running:

```bash
# Restart the model service
docker compose restart model_svc

# Check logs for errors
docker compose logs model_svc
```

### No Predictions Found

If Redis has no predictions:

1. **Check if events are being generated:**
   ```bash
   docker compose exec redis redis-cli XLEN events
   ```

2. **Check if features are being generated:**
   ```bash
   docker compose exec redis redis-cli XLEN features
   ```

3. **Check feature_state service:**
   ```bash
   docker compose logs feature_state --tail=50
   ```

### Model Not Loading

If you see errors about model loading:

1. **Check if model file exists:**
   ```bash
   ls -la services/training/models/lightgbm_20251104_215914_53104e84/
   ```

2. **Check model_svc volumes in docker-compose.yaml:**
   - Should have: `./services/training/models:/app/models:ro`

3. **Check MODEL_ID environment variable:**
   ```bash
   docker compose exec model_svc env | grep MODEL_ID
   ```

## Expected Behavior

When everything is working correctly:

1. ✅ Model service loads LightGBM model on startup
2. ✅ Events are generated and added to `events` stream
3. ✅ Feature state service processes events and adds to `features` stream
4. ✅ Model service reads features and generates predictions
5. ✅ Predictions are stored in Redis at `pred:{game_id}`
6. ✅ Gateway service retrieves predictions from Redis
7. ✅ Website displays model predictions (not calculated fallback)

## Verification Checklist

- [ ] Docker containers are running
- [ ] Model service logs show model loaded successfully
- [ ] Redis has prediction keys (`pred:*`)
- [ ] Predictions stream has entries (`XLEN predictions` > 0)
- [ ] Gateway logs show no "falling back" warnings
- [ ] API endpoint returns predictions with `model_id` field
- [ ] Website graph shows historical predictions from database

