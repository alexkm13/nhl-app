# ML Training Pipeline

Production-grade machine learning training pipeline for win probability prediction.

## Structure

- `train.py` - Main training script with CLI
- `config.yaml` - Training configuration
- `features.py` - Feature engineering module
- `data.py` - Data loading and preprocessing
- `model.py` - Model definitions and training
- `evaluate.py` - Model evaluation metrics
- `registry.py` - Model versioning and registry
- `utils.py` - Helper utilities

## Usage

```bash
# Train with default config
python train.py

# Train with custom config
python train.py --config config.yaml

# Train specific model type
python train.py --model-type xgboost

# Override specific parameters
python train.py --epochs 100 --learning-rate 0.01
```

## Features

- Rich feature engineering from game events and statistics
- Multiple model types (XGBoost, LightGBM, Neural Network)
- Cross-validation and holdout testing
- Model versioning with MLflow/Weights & Biases
- Hyperparameter tuning with Optuna
- Model registry for deployment
- Comprehensive evaluation metrics

