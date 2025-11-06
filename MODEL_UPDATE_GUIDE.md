# Model Update and History Testing Guide

## Quick Start

### 1. Test History Array and Graph

```bash
# List recent games
python3 test_history.py

# Test history for a specific game
python3 test_history.py 2025020161
```

The script will:
- Fetch history data from `/v1/games/{game_id}/winprob/history`
- Analyze data quality (gaps, coverage, etc.)
- Show first/last data points
- Check if data is suitable for graphing

### 2. Manage Models

```bash
# List all models
python3 manage_models.py list

# Compare model metrics
python3 manage_models.py compare

# Activate a different model
python3 manage_models.py activate --model-id lightgbm_20251104_121934_d9b5b03f

# Add a new model to registry
python3 manage_models.py add \
  --model-id my_new_model \
  --model-dir models/my_new_model \
  --model-type lightgbm \
  --metrics '{"accuracy": 0.75, "roc_auc": 0.82}' \
  --active
```

## Understanding the System

### History Data Flow

1. **Event Ingestion**: Events flow from NHL API → `events` stream → `feature_state` → `features` stream
2. **Model Prediction**: `model_svc` reads features → generates predictions → stores in:
   - Redis cache: `pred:{game_id}` (current prediction)
   - Redis stream: `predictions` (for WebSocket)
   - TimescaleDB: `predictions` table (for history)

3. **History Retrieval**: 
   - Frontend calls `/v1/games/{game_id}/winprob/history`
   - Backend queries TimescaleDB `predictions` table
   - Returns array of `{ts: seconds_from_start, p_home_win: 0.0-1.0}`

4. **Graph Rendering**:
   - Frontend `generateWinProbGraph()` creates SVG visualization
   - If < 10 data points, generates synthetic points from play-by-play
   - Shows probability changes over time with period markers

### Model Update Process

#### Option 1: Activate Existing Model (Easiest)

```bash
# See available models
python3 manage_models.py list

# Activate the best performing model
python3 manage_models.py activate --model-id lightgbm_20251104_121934_d9b5b03f

# Restart model_svc to load new model
docker compose restart model_svc
```

#### Option 2: Train and Deploy New Model

1. **Train Model** (in `services/training/`):
   ```bash
   cd services/training
   python train_model.py --output-dir models/my_new_model
   ```

2. **Add to Registry**:
   ```bash
   python3 manage_models.py add \
     --model-id my_new_model_20250106 \
     --model-dir models/my_new_model \
     --model-type lightgbm \
     --metrics '{"accuracy": 0.75, "roc_auc": 0.82, "log_loss": 0.50}' \
     --active
   ```

3. **Update Docker** (if model files need to be mounted):
   - Ensure model files are in `services/training/models/`
   - Model files should be accessible to `model_svc` container

4. **Restart Service**:
   ```bash
   docker compose restart model_svc
   ```

#### Option 3: A/B Testing (Advanced)

1. Deploy multiple model variants
2. Use `services/model_svc/ab_testing.py` to route traffic
3. Compare performance metrics
4. Gradually roll out winner

## Troubleshooting

### No History Data

**Symptoms**: `test_history.py` shows 0 data points

**Possible Causes**:
1. **Predictions not being stored**: Check `model_svc` logs
   ```bash
   docker compose logs model_svc | grep "insert error"
   ```

2. **Database connection issue**: Verify DATABASE_URL in `model_svc`
   ```bash
   docker compose exec model_svc env | grep DATABASE_URL
   ```

3. **Game hasn't started**: Predictions only generated during live games

4. **Model not processing**: Check if `model_svc` is reading from `features` stream
   ```bash
   docker compose logs model_svc | tail -20
   ```

### Graph Not Showing

**Symptoms**: Graph shows flat line or no data

**Check**:
1. History data exists: `python3 test_history.py {game_id}`
2. Browser console for errors
3. Network tab: Is `/v1/games/{game_id}/winprob/history` returning data?

### Model Not Updating

**Symptoms**: Changes to registry not reflected

**Check**:
1. Registry file location: `services/training/models/registry.json`
2. Model files exist: Check `model_dir` path in registry
3. `model_svc` environment: `MODEL_ID` env var or default active model
4. Restart service: `docker compose restart model_svc`

## Current Model Status

Based on registry analysis:
- **Active Model**: `lightgbm_20251104_115151_e21578a7`
- **Best Model** (by accuracy): `lightgbm_20251104_121934_d9b5b03f` (71.98% accuracy)

To switch to best model:
```bash
python3 manage_models.py activate --model-id lightgbm_20251104_121934_d9b5b03f
docker compose restart model_svc
```

## Next Steps

1. **Test History**: Run `python3 test_history.py` on a completed game
2. **Update Model**: Use `manage_models.py` to activate best model
3. **Monitor**: Check predictions are being stored correctly
4. **Improve**: Train new models with more recent data

