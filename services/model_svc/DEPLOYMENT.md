# Model Deployment Guide

## Using the Trained Model

The trained LightGBM model (`lightgbm_20251104_115151_e21578a7`) is now configured for production use.

### Model Performance
- **ROC AUC**: 0.7996
- **Accuracy**: 71.63%
- **Log Loss**: 0.5302
- **Calibration Error**: 0.0360

### Deployment

The model is automatically loaded when:
1. `MODEL_ID` environment variable is set to `lightgbm_20251104_115151_e21578a7`
2. Or the model is set as active in the registry

### Configuration

Update `docker-compose.yaml`:
```yaml
model_svc:
  environment:
    - MODEL_ID=lightgbm_20251104_115151_e21578a7
```

### Verification

The model service will:
1. Load the trained model from the registry
2. Engineer features matching the training pipeline
3. Make predictions using the LightGBM model

### Fallback

If the trained model cannot be loaded (missing dependencies or file not found), the service automatically falls back to the baseline model.

