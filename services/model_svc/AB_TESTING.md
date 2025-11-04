# A/B Testing Framework

A production-ready A/B testing framework for comparing multiple ML models in real-time.

## Features

- **Traffic Splitting**: Route percentage of traffic to different models
- **Consistent Routing**: Same game/user gets same variant (deterministic)
- **Prediction Tracking**: All predictions logged with variant information
- **Metrics Comparison**: Compare performance metrics between variants
- **Gradual Rollout**: Easily adjust traffic percentages over time

## Configuration

### Environment Variables

```bash
# Enable A/B testing
AB_TEST_ENABLED=true

# A/B test configuration (JSON)
AB_TEST_CONFIG='{
  "variants": [
    {
      "model_id": "lightgbm_20251104_115151_e21578a7",
      "name": "new_model",
      "traffic_percentage": 50,
      "enabled": true
    },
    {
      "model_id": "baseline-logit-v0",
      "name": "baseline",
      "traffic_percentage": 50,
      "enabled": true
    }
  ]
}'
```

### Configuration File

Alternatively, create a JSON file and load it:

```json
{
  "variants": [
    {
      "model_id": "lightgbm_20251104_115151_e21578a7",
      "name": "new_model",
      "traffic_percentage": 50,
      "enabled": true
    },
    {
      "model_id": "baseline-logit-v0",
      "name": "baseline",
      "traffic_percentage": 50,
      "enabled": true
    }
  ]
}
```

## Usage

### Basic Setup

1. **Enable A/B testing** in docker-compose.yaml:

```yaml
model_svc:
  environment:
    - AB_TEST_ENABLED=true
    - AB_TEST_CONFIG='{"variants": [...]}'
```

2. **Configure variants** with traffic percentages (must sum to 100% or less)

3. **Restart service** to load configuration

### Traffic Distribution

- Traffic is distributed based on `traffic_percentage` for each variant
- Routing is deterministic (same game_id gets same variant)
- Uses consistent hashing for stable assignments

### Example Configurations

#### 50/50 Split
```json
{
  "variants": [
    {"model_id": "model_a", "name": "variant_a", "traffic_percentage": 50, "enabled": true},
    {"model_id": "model_b", "name": "variant_b", "traffic_percentage": 50, "enabled": true}
  ]
}
```

#### Gradual Rollout (10% new model)
```json
{
  "variants": [
    {"model_id": "new_model", "name": "new", "traffic_percentage": 10, "enabled": true},
    {"model_id": "current_model", "name": "current", "traffic_percentage": 90, "enabled": true}
  ]
}
```

#### Multi-variant Test
```json
{
  "variants": [
    {"model_id": "model_a", "name": "baseline", "traffic_percentage": 33, "enabled": true},
    {"model_id": "model_b", "name": "variant_1", "traffic_percentage": 33, "enabled": true},
    {"model_id": "model_c", "name": "variant_2", "traffic_percentage": 34, "enabled": true}
  ]
}
```

## Analysis

### Get Metrics

```python
from ab_testing import ABTestTracker
from ab_test_analyzer import ABTestAnalyzer

# Get tracker
tracker = ABTestTracker()

# Get metrics
metrics = tracker.get_metrics(
    game_id="2024020001",  # Optional
    start_time=datetime(2024, 1, 1),  # Optional
    end_time=datetime(2024, 1, 31)  # Optional
)

# Generate report
analyzer = ABTestAnalyzer(db_url)
report = analyzer.get_comparison_report(
    start_time=datetime(2024, 1, 1),
    end_time=datetime(2024, 1, 31)
)

# Print formatted report
from ab_test_analyzer import print_ab_test_report
print_ab_test_report(report)
```

### Command Line Analysis

```bash
# Run analysis script
python3 -c "
from ab_test_analyzer import ABTestAnalyzer, print_ab_test_report
from datetime import datetime, timedelta
import os

analyzer = ABTestAnalyzer(os.environ.get('DATABASE_URL'))
end_time = datetime.utcnow()
start_time = end_time - timedelta(days=7)

report = analyzer.get_comparison_report(start_time=start_time, end_time=end_time)
print_ab_test_report(report)
"
```

## Database Schema

Predictions are stored in `ab_test_predictions` table:

```sql
CREATE TABLE ab_test_predictions (
    id SERIAL PRIMARY KEY,
    game_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    variant_name TEXT NOT NULL,
    prediction FLOAT NOT NULL,
    features JSONB,
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ab_test_game_model 
ON ab_test_predictions(game_id, model_id, timestamp);
```

## Best Practices

1. **Start Small**: Begin with 10% traffic to new model
2. **Monitor Metrics**: Watch for significant differences
3. **Gradual Increase**: Increase traffic percentage over time
4. **Consistent Routing**: Same game always gets same variant
5. **Track Everything**: All predictions logged for analysis
6. **Rollback Plan**: Keep previous model enabled for quick rollback

## Monitoring

- Prometheus metrics include model_id and variant_name
- Database logs all predictions with variant information
- Real-time metrics available via API

## Troubleshooting

### A/B Testing Not Active

- Check `AB_TEST_ENABLED=true`
- Verify at least 2 variants are enabled
- Ensure traffic percentages are configured

### Model Not Loading

- Check model_id exists in registry
- Verify model files are accessible
- Check service logs for errors

### Traffic Distribution Issues

- Verify traffic percentages sum to 100% or less
- Check that variants are enabled
- Ensure consistent hashing is working

