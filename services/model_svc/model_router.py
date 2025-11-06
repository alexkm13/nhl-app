"""
Model Router for A/B Testing - routes predictions to different model variants.
"""
import os
import time
from typing import Dict, Optional, Tuple
from model_loader import ModelLoader, load_production_model
from ab_test import ABTestManager, ABTestMetrics


class ModelRouter:
    """Routes predictions to different models based on A/B test configuration."""
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize model router.
        
        Args:
            redis_url: Redis URL for metrics tracking
        """
        self.ab_test_manager = ABTestManager()
        self.ab_metrics = ABTestMetrics(redis_url)
        self.model_cache: Dict[str, ModelLoader] = {}
        self.default_model: Optional[ModelLoader] = None
    
    def _load_model(self, model_id: str) -> ModelLoader:
        """Load a model, using cache if available."""
        if model_id in self.model_cache:
            return self.model_cache[model_id]
        
        loader = load_production_model(model_id)
        if loader.model is not None:
            self.model_cache[model_id] = loader
        
        return loader
    
    def get_model_for_prediction(self, game_id: str) -> Tuple[ModelLoader, str, Optional[str]]:
        """
        Get the model to use for a prediction based on A/B testing.
        
        Args:
            game_id: Game ID for consistent routing
        
        Returns:
            Tuple of (model_loader, variant_name, test_id)
        """
        # Check for active A/B test
        active_test = self.ab_test_manager.get_active_test()
        
        if active_test:
            # Select variant based on game_id (consistent hashing)
            model_id, variant_name = self.ab_test_manager.select_variant(game_id, active_test)
            
            if model_id:
                model_loader = self._load_model(model_id)
                if model_loader.model is not None:
                    return model_loader, variant_name, active_test.test_id
        
        # No active test or variant selection failed - use default
        if self.default_model is None:
            self.default_model = load_production_model()
        
        return self.default_model, "default", None
    
    def record_prediction(
        self,
        test_id: Optional[str],
        variant_name: str,
        model_id: str,
        game_id: str,
        prediction: float,
        latency_ms: float
    ):
        """Record prediction metrics."""
        if test_id:
            self.ab_metrics.record_prediction(
                test_id, variant_name, model_id, game_id, prediction, latency_ms
            )
    
    def get_test_metrics(self, test_id: str) -> Dict:
        """Get metrics for all variants in a test."""
        test = self.ab_test_manager.get_test(test_id)
        if not test:
            return {}
        
        metrics = {}
        for variant in test.variants:
            variant_metrics = self.ab_metrics.get_metrics(test_id, variant.name)
            metrics[variant.name] = {
                'model_id': variant.model_id,
                'traffic_percentage': variant.traffic_percentage,
                **variant_metrics
            }
        
        return metrics


# Global router instance
_router: Optional[ModelRouter] = None


def get_router() -> ModelRouter:
    """Get or create global model router."""
    global _router
    if _router is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _router = ModelRouter(redis_url)
    return _router

