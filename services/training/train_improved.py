#!/usr/bin/env python3
"""
Train improved model based on analysis recommendations.
"""
import os
import sys
import argparse

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import load_training_data
from features import engineer_features
from model import WinProbabilityModel
from evaluate import evaluate_model
from registry import ModelRegistry
from utils import setup_logging, load_config


def train_improved_model(
    config_path: str,
    improvements: list = None,
    save_model: bool = True
):
    """
    Train an improved model based on recommendations.
    
    Args:
        config_path: Path to config file
        improvements: List of improvements to apply
        save_model: Whether to save the model
    """
    # Load configuration
    config = load_config(config_path)
    training_config = config['training']
    
    # Setup logging
    setup_logging(training_config.get('log_level', 'INFO'))
    
    print("="*80)
    print("Training Improved Model")
    print("="*80)
    
    if improvements:
        print("\nApplying improvements:")
        for i, imp in enumerate(improvements, 1):
            print(f"  {i}. {imp}")
    
    # Load data
    print("\nLoading training data...")
    train_data, test_data = load_training_data(
        train_start_date=training_config['train_start_date'],
        train_end_date=training_config['train_end_date'],
        test_start_date=training_config['test_start_date'],
        test_end_date=training_config['test_end_date'],
        database_url=os.environ.get('DATABASE_URL')
    )
    
    if train_data is None or train_data.empty:
        print("Error: No training data loaded")
        return None
    
    print(f"Loaded {len(train_data)} training samples, {len(test_data)} test samples")
    
    # Engineer features
    print("Engineering features...")
    X_train, y_train = engineer_features(train_data, training_config)
    X_test, y_test = engineer_features(test_data, training_config)
    
    # Apply improvements
    model_config = training_config.get('model', {})
    model_type = model_config.get('model_type', 'lightgbm')
    hyperparameters = model_config.get('hyperparameters', {})
    
    # Improvement 1: Add calibration if recommended
    if improvements and any('calibration' in imp.lower() or 'temperature' in imp.lower() for imp in improvements):
        print("\nApplying calibration improvements...")
        # LightGBM supports calibration via scale_pos_weight
        if model_type == 'lightgbm':
            # Adjust scale_pos_weight for better calibration
            pos_weight = y_train.sum() / (len(y_train) - y_train.sum())
            hyperparameters['scale_pos_weight'] = pos_weight
            print(f"  Set scale_pos_weight to {pos_weight:.3f}")
    
    # Improvement 2: Adjust hyperparameters for better generalization
    if improvements and any('hyperparameter' in imp.lower() or 'tuning' in imp.lower() for imp in improvements):
        print("\nApplying hyperparameter improvements...")
        # Increase regularization for better generalization
        if model_type == 'lightgbm':
            hyperparameters.setdefault('reg_alpha', 0.1)
            hyperparameters.setdefault('reg_lambda', 0.1)
            hyperparameters.setdefault('min_child_samples', 20)
            print("  Added regularization parameters")
    
    # Improvement 3: Ensemble methods
    if improvements and any('ensemble' in imp.lower() for imp in improvements):
        print("\nNote: Ensemble methods require multiple models. Training single improved model.")
    
    # Train model
    print(f"\nTraining {model_type} model...")
    model = WinProbabilityModel(
        model_type=model_type,
        **hyperparameters
    )
    
    # Split training data for validation
    from sklearn.model_selection import train_test_split
    X_train_split, X_val_split, y_train_split, y_val_split = train_test_split(
        X_train, y_train,
        test_size=0.2,
        random_state=42,
        stratify=y_train
    )
    
    model.train(X_train_split, y_train_split, X_val_split, y_val_split)
    
    # Evaluate
    print("Evaluating model...")
    evaluation_results = evaluate_model(model, X_test, y_test)
    
    print("\n" + "="*80)
    print("Evaluation Results")
    print("="*80)
    for metric, value in evaluation_results.items():
        print(f"  {metric:20s}: {value:.4f}")
    
    # Save model
    if save_model:
        from registry import ModelRegistry
        registry = ModelRegistry()
        
        # Generate model_id first
        model_id = registry._generate_model_id(model_type, training_config)
        model_filepath = f"models/{model_id}/model.pkl"
        
        model_id = registry.register_model(
            model=model,
            model_type=model_type,
            config=training_config,
            metrics=evaluation_results,
            feature_importance=model.get_feature_importance(),
            model_filepath=model_filepath
        )
        
        print(f"\nModel registered with ID: {model_id}")
        print(f"To use this model, set MODEL_ID={model_id}")
    
    return model


def main():
    parser = argparse.ArgumentParser(description="Train improved model")
    parser.add_argument("--config", default="config.yaml",
                       help="Config file path")
    parser.add_argument("--improvements", nargs="+",
                       help="List of improvements to apply")
    parser.add_argument("--save-model", action="store_true",
                       help="Save model to registry")
    parser.add_argument("--database-url",
                       default=os.environ.get("DATABASE_URL"),
                       help="Database URL")
    
    args = parser.parse_args()
    
    if args.database_url:
        os.environ['DATABASE_URL'] = args.database_url
    
    train_improved_model(
        config_path=args.config,
        improvements=args.improvements or [],
        save_model=args.save_model
    )


if __name__ == "__main__":
    main()

