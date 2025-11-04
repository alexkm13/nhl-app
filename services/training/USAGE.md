# Training Pipeline Usage Guide

## Quick Start

### 1. Install Dependencies

```bash
cd services/training
pip install -r requirements.txt
```

### 2. Configure Training

Edit `config.yaml` to set:
- Data date ranges (train/test splits)
- Model type (xgboost, lightgbm, catboost)
- Hyperparameters
- Feature engineering options

### 3. Train Model

```bash
# Basic training
python train.py --config config.yaml

# With custom model type
python train.py --config config.yaml --model-type xgboost

# With overridden hyperparameters
python train.py --config config.yaml --epochs 300 --learning-rate 0.01

# Save to registry
python train.py --config config.yaml --save-model
```

### 4. Use Trained Model in Production

Set `MODEL_ID` environment variable to the trained model ID:

```bash
export MODEL_ID=xgboost_20240101_120000_abc12345
```

Or update the model service to load from registry.

## Configuration

### Model Types

- **xgboost**: Gradient boosting (default, recommended)
- **lightgbm**: Lightweight gradient boosting (faster)
- **catboost**: Categorical boosting (good for categorical features)

### Hyperparameters

Key hyperparameters in `config.yaml`:

- `n_estimators`: Number of boosting rounds (200-500)
- `max_depth`: Tree depth (4-8)
- `learning_rate`: Learning rate (0.01-0.1)
- `subsample`: Row sampling (0.7-1.0)
- `colsample_bytree`: Column sampling (0.7-1.0)
- `min_child_weight`: Minimum samples in leaf (1-10)
- `reg_alpha`: L1 regularization (0-1)
- `reg_lambda`: L2 regularization (0-10)

### Feature Engineering

Features are automatically engineered from:
- Score features (differential, ratio, leading indicators)
- Time features (period, time remaining, normalized time)
- Strength features (power play, penalty kill, empty net)
- Momentum features (rolling score changes, recent goals)
- Recent events (last event type)

Enable/disable features in `config.yaml` under `features:`.

## Model Registry

Models are saved to `models/` directory with:
- Model pickle file
- Metadata JSON
- Feature importance CSV
- Configuration YAML

### List Models

```python
from registry import ModelRegistry

registry = ModelRegistry()
models_df = registry.list_models()
print(models_df)
```

### Activate Model

```python
from registry import ModelRegistry

registry = ModelRegistry()
registry.set_active_model('xgboost_20240101_120000_abc12345')
```

## Evaluation Metrics

The pipeline evaluates:
- **Log Loss**: Primary metric (lower is better)
- **Brier Score**: Calibration metric (lower is better)
- **ROC AUC**: Discrimination (higher is better, 0.5-1.0)
- **Accuracy**: Classification accuracy
- **Calibration Error**: Expected calibration error (ECE)

Metrics are calculated:
- Overall
- By time period (0-10min, 10-20min, etc.)
- By score differential (-3, -2, -1, 0, +1, +2, +3+)

## Experiment Tracking

Each training run creates an experiment directory with:
- Model file
- Metrics JSON
- Configuration YAML
- Feature importance CSV

Experiments are timestamped: `experiments/experiment_YYYYMMDD_HHMMSS/`

## Production Deployment

### Option 1: Environment Variable

Set `MODEL_ID` in model service:
```bash
export MODEL_ID=xgboost_20240101_120000_abc12345
```

### Option 2: Direct Path

Set `MODEL_PATH` in model service:
```bash
export MODEL_PATH=/path/to/models/xgboost_20240101_120000_abc12345/model.pkl
```

### Option 3: Registry Active Model

The model service automatically loads the active model from registry.

## Troubleshooting

### Import Errors

If training dependencies are missing, install:
```bash
pip install -r services/training/requirements.txt
```

### Data Not Found

Ensure:
- TimescaleDB is running
- `DATABASE_URL` is set correctly
- Date ranges in config match available data

### Feature Mismatch

If prediction fails with feature mismatch:
- Ensure feature engineering matches training
- Check feature columns in model metadata
- Verify all required features are present

### Model Not Found

If model not found:
- Check model ID is correct
- Verify model file exists in registry
- Check file permissions

