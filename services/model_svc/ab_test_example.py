"""
Example script for creating and managing A/B tests.
"""
from ab_test import ABTestManager
from datetime import datetime, timedelta


def create_example_test():
    """Create an example A/B test comparing baseline vs trained model."""
    manager = ABTestManager()
    
    # Create test with 50/50 split
    test_id = manager.create_test(
        name="Baseline vs LightGBM Comparison",
        description="Compare baseline logistic model against trained LightGBM model",
        variants=[
            {
                'model_id': 'baseline-logit-v0',
                'name': 'baseline',
                'traffic_percentage': 0.5,
                'enabled': True
            },
            {
                'model_id': 'lightgbm_20251104_115151_e21578a7',
                'name': 'lightgbm_v1',
                'traffic_percentage': 0.5,
                'enabled': True
            }
        ],
        start_date=datetime.utcnow().isoformat(),
        end_date=(datetime.utcnow() + timedelta(days=7)).isoformat()
    )
    
    print(f"Created A/B test: {test_id}")
    return test_id


def create_gradual_rollout_test():
    """Create a gradual rollout test (10% to new model, 90% to current)."""
    manager = ABTestManager()
    
    test_id = manager.create_test(
        name="Gradual Rollout - LightGBM v1",
        description="Gradual rollout of new LightGBM model",
        variants=[
            {
                'model_id': 'lightgbm_20251104_025931_df39f25b',
                'name': 'lightgbm_v0',
                'traffic_percentage': 0.9,
                'enabled': True
            },
            {
                'model_id': 'lightgbm_20251104_115151_e21578a7',
                'name': 'lightgbm_v1',
                'traffic_percentage': 0.1,
                'enabled': True
            }
        ],
        start_date=datetime.utcnow().isoformat(),
        end_date=(datetime.utcnow() + timedelta(days=14)).isoformat()
    )
    
    print(f"Created gradual rollout test: {test_id}")
    return test_id


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'rollout':
        create_gradual_rollout_test()
    else:
        create_example_test()

