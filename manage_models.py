#!/usr/bin/env python3
"""Helper script for managing and updating ML models."""
import json
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Default paths - try multiple locations
SCRIPT_DIR = Path(__file__).parent
POSSIBLE_TRAINING_DIRS = [
    SCRIPT_DIR / "services" / "training",
    SCRIPT_DIR.parent / "services" / "training",
    Path("/app") / "services" / "training",  # Docker
]

TRAINING_DIR = None
for td in POSSIBLE_TRAINING_DIRS:
    if td.exists():
        TRAINING_DIR = td
        break

if TRAINING_DIR is None:
    # Fallback: use first one and create if needed
    TRAINING_DIR = POSSIBLE_TRAINING_DIRS[0]

REGISTRY_PATH = TRAINING_DIR / "models" / "registry.json"
MODELS_DIR = TRAINING_DIR / "models"

def load_registry():
    """Load the model registry."""
    if not REGISTRY_PATH.exists():
        print(f"Registry not found at {REGISTRY_PATH}")
        return {}
    
    with open(REGISTRY_PATH, 'r') as f:
        return json.load(f)

def save_registry(registry):
    """Save the model registry."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, 'w') as f:
        json.dump(registry, f, indent=2)
    print(f"Registry saved to {REGISTRY_PATH}")

def list_models():
    """List all models in the registry."""
    registry = load_registry()
    
    if not registry:
        print("No models found in registry.")
        return
    
    print("\n" + "="*80)
    print("Available Models")
    print("="*80)
    
    active_model = None
    for model_id, info in registry.items():
        is_active = info.get('is_active', False)
        status = "✓ ACTIVE" if is_active else "  inactive"
        if is_active:
            active_model = model_id
        
        metrics = info.get('metrics', {})
        print(f"\n{status} | {model_id}")
        print(f"  Type: {info.get('model_type', 'unknown')}")
        print(f"  Timestamp: {info.get('timestamp', 'unknown')}")
        print(f"  Directory: {info.get('model_dir', 'unknown')}")
        
        if metrics:
            print("  Metrics:")
            print(f"    - Accuracy: {metrics.get('accuracy', 0):.4f}")
            print(f"    - ROC AUC: {metrics.get('roc_auc', 0):.4f}")
            print(f"    - Log Loss: {metrics.get('log_loss', 0):.4f}")
            print(f"    - Brier Score: {metrics.get('brier_score', 0):.4f}")
    
    print("\n" + "="*80)
    if active_model:
        print(f"Active Model: {active_model}")
    else:
        print("⚠️  No active model set!")
    print("="*80 + "\n")

def activate_model(model_id: str):
    """Activate a model by setting is_active=True."""
    registry = load_registry()
    
    if model_id not in registry:
        print(f"❌ Model '{model_id}' not found in registry.")
        print(f"Available models: {', '.join(registry.keys())}")
        return False
    
    # Deactivate all models
    for mid in registry:
        registry[mid]['is_active'] = False
    
    # Activate the selected model
    registry[model_id]['is_active'] = True
    
    save_registry(registry)
    print(f"✓ Activated model: {model_id}")
    
    # Show model info
    info = registry[model_id]
    print("\nModel Details:")
    print(f"  Type: {info.get('model_type', 'unknown')}")
    print(f"  Timestamp: {info.get('timestamp', 'unknown')}")
    metrics = info.get('metrics', {})
    if metrics:
        print(f"  Accuracy: {metrics.get('accuracy', 0):.4f}")
        print(f"  ROC AUC: {metrics.get('roc_auc', 0):.4f}")
    
    return True

def add_model(model_id: str, model_dir: str, model_type: str = "lightgbm", 
              metrics: dict = None, is_active: bool = False):
    """Add a new model to the registry."""
    registry = load_registry()
    
    if model_id in registry:
        print(f"⚠️  Model '{model_id}' already exists. Use --force to overwrite.")
        return False
    
    model_info = {
        "model_type": model_type,
        "timestamp": datetime.now().isoformat(),
        "metrics": metrics or {},
        "model_dir": model_dir,
        "is_active": is_active
    }
    
    # If activating, deactivate others
    if is_active:
        for mid in registry:
            registry[mid]['is_active'] = False
    
    registry[model_id] = model_info
    save_registry(registry)
    print(f"✓ Added model: {model_id}")
    return True

def compare_models():
    """Compare metrics of all models."""
    registry = load_registry()
    
    if not registry:
        print("No models found in registry.")
        return
    
    print("\n" + "="*80)
    print("Model Comparison")
    print("="*80)
    
    # Sort by accuracy (or other metric)
    models_sorted = sorted(
        registry.items(),
        key=lambda x: x[1].get('metrics', {}).get('accuracy', 0),
        reverse=True
    )
    
    print(f"\n{'Model ID':<40} {'Active':<8} {'Accuracy':<10} {'ROC AUC':<10} {'Log Loss':<10}")
    print("-" * 80)
    
    for model_id, info in models_sorted:
        is_active = "✓" if info.get('is_active', False) else ""
        metrics = info.get('metrics', {})
        accuracy = metrics.get('accuracy', 0)
        roc_auc = metrics.get('roc_auc', 0)
        log_loss = metrics.get('log_loss', 0)
        
        print(f"{model_id:<40} {is_active:<8} {accuracy:<10.4f} {roc_auc:<10.4f} {log_loss:<10.4f}")
    
    print("="*80 + "\n")

def update_metrics(model_id: str, metrics: dict):
    """Update metrics for a model."""
    registry = load_registry()
    
    if model_id not in registry:
        print(f"❌ Model '{model_id}' not found in registry.")
        return False
    
    registry[model_id]['metrics'].update(metrics)
    save_registry(registry)
    print(f"✓ Updated metrics for {model_id}")
    return True

def main():
    parser = argparse.ArgumentParser(description="Manage ML models for NHL win probability prediction")
    parser.add_argument('command', choices=['list', 'activate', 'add', 'compare', 'update-metrics'],
                       help='Command to execute')
    parser.add_argument('--model-id', help='Model ID')
    parser.add_argument('--model-dir', help='Model directory path')
    parser.add_argument('--model-type', default='lightgbm', help='Model type')
    parser.add_argument('--metrics', help='Metrics JSON string or file path')
    parser.add_argument('--active', action='store_true', help='Set as active model')
    parser.add_argument('--force', action='store_true', help='Force overwrite')
    
    args = parser.parse_args()
    
    if args.command == 'list':
        list_models()
    
    elif args.command == 'activate':
        if not args.model_id:
            print("❌ --model-id required for activate command")
            sys.exit(1)
        activate_model(args.model_id)
    
    elif args.command == 'add':
        if not args.model_id or not args.model_dir:
            print("❌ --model-id and --model-dir required for add command")
            sys.exit(1)
        
        metrics = {}
        if args.metrics:
            if os.path.exists(args.metrics):
                with open(args.metrics, 'r') as f:
                    metrics = json.load(f)
            else:
                try:
                    metrics = json.loads(args.metrics)
                except json.JSONDecodeError:
                    print("❌ Invalid metrics JSON")
                    sys.exit(1)
        
        add_model(args.model_id, args.model_dir, args.model_type, metrics, args.active)
    
    elif args.command == 'compare':
        compare_models()
    
    elif args.command == 'update-metrics':
        if not args.model_id or not args.metrics:
            print("❌ --model-id and --metrics required for update-metrics command")
            sys.exit(1)
        
        if os.path.exists(args.metrics):
            with open(args.metrics, 'r') as f:
                metrics = json.load(f)
        else:
            try:
                metrics = json.loads(args.metrics)
            except json.JSONDecodeError:
                print("❌ Invalid metrics JSON")
                sys.exit(1)
        
        update_metrics(args.model_id, metrics)

if __name__ == "__main__":
    main()

