"""
A/B testing framework for model comparisons.
"""
import os
import random
import json
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ModelVariant:
    """A model variant in an A/B test."""
    model_id: str
    name: str
    traffic_percentage: float
    enabled: bool = True


class ABTestRouter:
    """Router for A/B testing multiple models."""
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize A/B test router.
        
        Args:
            config: Configuration dict with variants and routing rules
        """
        self.config = config or {}
        self.variants: List[ModelVariant] = []
        self.load_config()
    
    def load_config(self):
        """Load configuration from environment or config dict."""
        # Load from environment variable if available
        ab_config = os.environ.get("AB_TEST_CONFIG")
        if ab_config:
            try:
                self.config = json.loads(ab_config)
            except json.JSONDecodeError:
                pass
        
        # Parse variants
        variants_config = self.config.get("variants", [])
        total_traffic = sum(v.get("traffic_percentage", 0) for v in variants_config)
        
        if total_traffic > 100:
            # Normalize if over 100%
            variants_config = [
                {**v, "traffic_percentage": v.get("traffic_percentage", 0) * 100 / total_traffic}
                for v in variants_config
            ]
        
        self.variants = [
            ModelVariant(
                model_id=v.get("model_id", "baseline-logit-v0"),
                name=v.get("name", v.get("model_id", "baseline")),
                traffic_percentage=v.get("traffic_percentage", 0),
                enabled=v.get("enabled", True)
            )
            for v in variants_config
            if v.get("enabled", True)
        ]
        
        # Sort by traffic percentage (descending) for routing
        self.variants.sort(key=lambda x: x.traffic_percentage, reverse=True)
    
    def select_variant(self, user_id: Optional[str] = None, game_id: Optional[str] = None) -> Optional[ModelVariant]:
        """
        Select a model variant based on traffic distribution.
        
        Uses consistent hashing to ensure same user/game gets same variant.
        
        Args:
            user_id: Optional user ID for consistent routing
            game_id: Optional game ID for consistent routing
        
        Returns:
            Selected ModelVariant or None if no variants enabled
        """
        if not self.variants:
            return None
        
        # Use consistent hashing for deterministic routing
        if user_id:
            hash_key = user_id
        elif game_id:
            hash_key = game_id
        else:
            # Random routing if no identifier
            hash_key = str(random.random())
        
        # Hash to 0-100 range
        hash_value = hash(hash_key) % 100
        if hash_value < 0:
            hash_value = -hash_value
        
        # Route based on cumulative percentages
        cumulative = 0.0
        for variant in self.variants:
            if not variant.enabled:
                continue
            cumulative += variant.traffic_percentage
            if hash_value < cumulative:
                return variant
        
        # Fallback to first enabled variant
        for variant in self.variants:
            if variant.enabled:
                return variant
        
        return None
    
    def get_all_variants(self) -> List[ModelVariant]:
        """Get all configured variants."""
        return self.variants
    
    def is_enabled(self) -> bool:
        """Check if A/B testing is enabled."""
        return len(self.variants) > 1 and any(v.enabled for v in self.variants)


class ABTestTracker:
    """Track predictions for A/B testing analysis."""
    
    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize A/B test tracker.
        
        Args:
            db_url: Database URL for storing predictions
        """
        self.db_url = db_url or os.environ.get("DATABASE_URL", "")
    
    def log_prediction(
        self,
        game_id: str,
        model_id: str,
        variant_name: str,
        prediction: float,
        features: Dict,
        timestamp: Optional[datetime] = None
    ):
        """
        Log a prediction for A/B testing analysis.
        
        Args:
            game_id: Game identifier
            model_id: Model ID used
            variant_name: Variant name (for grouping)
            prediction: Prediction value
            features: Features used for prediction
            timestamp: Timestamp of prediction
        """
        if not self.db_url:
            return
        
        try:
            import psycopg
            from datetime import datetime
            
            if timestamp is None:
                timestamp = datetime.utcnow()
            
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    # Create table if it doesn't exist
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS ab_test_predictions (
                            id SERIAL PRIMARY KEY,
                            game_id TEXT NOT NULL,
                            model_id TEXT NOT NULL,
                            variant_name TEXT NOT NULL,
                            prediction FLOAT NOT NULL,
                            features JSONB,
                            timestamp TIMESTAMPTZ NOT NULL,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        )
                    """)
                    
                    # Create index for analysis
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_ab_test_game_model 
                        ON ab_test_predictions(game_id, model_id, timestamp)
                    """)
                    
                    # Insert prediction
                    cur.execute("""
                        INSERT INTO ab_test_predictions 
                        (game_id, model_id, variant_name, prediction, features, timestamp)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        game_id,
                        model_id,
                        variant_name,
                        prediction,
                        json.dumps(features),
                        timestamp
                    ))
                    
                    conn.commit()
        except Exception as e:
            # Log error but don't fail prediction
            print(f"[ab_test] Error logging prediction: {e}")
    
    def get_metrics(
        self,
        game_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict:
        """
        Get A/B test metrics for comparison.
        
        Args:
            game_id: Optional game ID to filter
            start_time: Optional start time filter
            end_time: Optional end time filter
        
        Returns:
            Dictionary with metrics by variant
        """
        if not self.db_url:
            return {}
        
        try:
            import psycopg
            
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT 
                            variant_name,
                            model_id,
                            COUNT(*) as prediction_count,
                            AVG(prediction) as avg_prediction,
                            STDDEV(prediction) as stddev_prediction,
                            MIN(prediction) as min_prediction,
                            MAX(prediction) as max_prediction
                        FROM ab_test_predictions
                        WHERE 1=1
                    """
                    params = []
                    
                    if game_id:
                        query += " AND game_id = %s"
                        params.append(game_id)
                    
                    if start_time:
                        query += " AND timestamp >= %s"
                        params.append(start_time)
                    
                    if end_time:
                        query += " AND timestamp <= %s"
                        params.append(end_time)
                    
                    query += """
                        GROUP BY variant_name, model_id
                        ORDER BY variant_name
                    """
                    
                    cur.execute(query, params)
                    results = cur.fetchall()
                    
                    metrics = {}
                    for row in results:
                        variant_name, model_id, count, avg_pred, stddev_pred, min_pred, max_pred = row
                        metrics[variant_name] = {
                            "model_id": model_id,
                            "prediction_count": count,
                            "avg_prediction": float(avg_pred) if avg_pred else 0.0,
                            "stddev_prediction": float(stddev_pred) if stddev_pred else 0.0,
                            "min_prediction": float(min_pred) if min_pred else 0.0,
                            "max_prediction": float(max_pred) if max_pred else 0.0,
                        }
                    
                    return metrics
        except Exception as e:
            print(f"[ab_test] Error getting metrics: {e}")
            return {}


def create_ab_test_router(config: Optional[Dict] = None) -> ABTestRouter:
    """
    Create an A/B test router from configuration.
    
    Args:
        config: Optional configuration dict. If None, loads from environment.
    
    Returns:
        ABTestRouter instance
    """
    return ABTestRouter(config)


def create_ab_test_tracker(db_url: Optional[str] = None) -> ABTestTracker:
    """
    Create an A/B test tracker.
    
    Args:
        db_url: Optional database URL. If None, uses DATABASE_URL env var.
    
    Returns:
        ABTestTracker instance
    """
    return ABTestTracker(db_url)

