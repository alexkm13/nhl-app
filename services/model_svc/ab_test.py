"""
A/B Testing Framework for Model Variants.
"""

import json
import os
import hashlib
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class Variant:
    """Model variant configuration."""

    model_id: str
    name: str
    traffic_percentage: float  # 0.0 to 1.0
    enabled: bool = True


@dataclass
class ABTest:
    """A/B test configuration."""

    test_id: str
    name: str
    description: str
    variants: List[Variant]
    start_date: str
    end_date: Optional[str] = None
    enabled: bool = True
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "test_id": self.test_id,
            "name": self.name,
            "description": self.description,
            "variants": [asdict(v) for v in self.variants],
            "start_date": self.start_date,
            "end_date": self.end_date,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ABTest":
        """Create from dictionary."""
        variants = [Variant(**v) for v in data.get("variants", [])]
        return cls(
            test_id=data["test_id"],
            name=data["name"],
            description=data.get("description", ""),
            variants=variants,
            start_date=data["start_date"],
            end_date=data.get("end_date"),
            enabled=data.get("enabled", True),
            created_at=data.get("created_at", ""),
        )


class ABTestManager:
    """Manages A/B test configurations and routing."""

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize A/B test manager.

        Args:
            config_path: Path to A/B test configuration file (default: in-memory)
        """
        self.config_path = config_path or os.path.join(
            os.path.dirname(__file__), "ab_tests.json"
        )
        self.tests: Dict[str, ABTest] = {}
        self._load_tests()

    def _load_tests(self):
        """Load A/B tests from file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                    self.tests = {
                        test_id: ABTest.from_dict(test_data)
                        for test_id, test_data in data.items()
                    }
            except Exception as e:
                print(f"[ab_test] Error loading tests: {e}")
                self.tests = {}
        else:
            self.tests = {}

    def _save_tests(self):
        """Save A/B tests to file."""
        try:
            data = {test_id: test.to_dict() for test_id, test in self.tests.items()}
            with open(self.config_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[ab_test] Error saving tests: {e}")

    def create_test(
        self,
        name: str,
        description: str,
        variants: List[Dict],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """
        Create a new A/B test.

        Args:
            name: Test name
            description: Test description
            variants: List of variant configs [{'model_id': '...', 'name': '...', 'traffic_percentage': 0.5}]
            start_date: Start date (ISO format, default: now)
            end_date: End date (ISO format, optional)

        Returns:
            Test ID
        """
        test_id = f"test_{int(time.time())}"

        variant_objs = [
            Variant(
                model_id=v["model_id"],
                name=v["name"],
                traffic_percentage=v["traffic_percentage"],
                enabled=v.get("enabled", True),
            )
            for v in variants
        ]

        # Validate traffic percentages sum to 1.0
        total_traffic = sum(v.traffic_percentage for v in variant_objs if v.enabled)
        if abs(total_traffic - 1.0) > 0.01:
            raise ValueError(
                f"Traffic percentages must sum to 1.0, got {total_traffic}"
            )

        test = ABTest(
            test_id=test_id,
            name=name,
            description=description,
            variants=variant_objs,
            start_date=start_date or datetime.utcnow().isoformat(),
            end_date=end_date,
            enabled=True,
        )

        self.tests[test_id] = test
        self._save_tests()

        return test_id

    def get_active_test(self) -> Optional[ABTest]:
        """Get the currently active A/B test."""
        now = datetime.utcnow()
        for test in self.tests.values():
            if not test.enabled:
                continue

            start = datetime.fromisoformat(test.start_date.replace("Z", "+00:00"))
            if start > now:
                continue

            if test.end_date:
                end = datetime.fromisoformat(test.end_date.replace("Z", "+00:00"))
                if end < now:
                    continue

            return test

        return None

    def select_variant(
        self, game_id: str, test: Optional[ABTest] = None
    ) -> Tuple[str, str]:
        """
        Select a model variant for a game using consistent hashing.

        Args:
            game_id: Game ID (used for consistent routing)
            test: Optional A/B test (default: get active test)

        Returns:
            Tuple of (model_id, variant_name)
        """
        if test is None:
            test = self.get_active_test()

        if test is None:
            # No active test, return default model
            return None, "default"

        # Use consistent hashing based on game_id
        # This ensures the same game always uses the same variant
        hash_value = int(
            hashlib.md5(f"{test.test_id}:{game_id}".encode()).hexdigest(), 16
        )
        hash_percentage = (hash_value % 10000) / 10000.0

        # Find which variant this hash falls into
        cumulative = 0.0
        for variant in test.variants:
            if not variant.enabled:
                continue

            cumulative += variant.traffic_percentage
            if hash_percentage < cumulative:
                return variant.model_id, variant.name

        # Fallback to last enabled variant
        enabled_variants = [v for v in test.variants if v.enabled]
        if enabled_variants:
            last = enabled_variants[-1]
            return last.model_id, last.name

        return None, "default"

    def get_test(self, test_id: str) -> Optional[ABTest]:
        """Get test by ID."""
        return self.tests.get(test_id)

    def list_tests(self) -> List[Dict]:
        """List all tests."""
        return [test.to_dict() for test in self.tests.values()]

    def update_test(self, test_id: str, **kwargs) -> bool:
        """Update test configuration."""
        if test_id not in self.tests:
            return False

        test = self.tests[test_id]

        if "enabled" in kwargs:
            test.enabled = kwargs["enabled"]
        if "end_date" in kwargs:
            test.end_date = kwargs["end_date"]
        if "variants" in kwargs:
            test.variants = [Variant(**v) for v in kwargs["variants"]]

        self._save_tests()
        return True

    def delete_test(self, test_id: str) -> bool:
        """Delete a test."""
        if test_id in self.tests:
            del self.tests[test_id]
            self._save_tests()
            return True
        return False


class ABTestMetrics:
    """Tracks metrics for A/B test variants."""

    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize metrics tracker.

        Args:
            redis_url: Redis URL for storing metrics (optional)
        """
        self.redis_url = redis_url
        self.redis = None
        if redis_url:
            try:
                from redis import Redis

                self.redis = Redis.from_url(redis_url, decode_responses=True)
            except ImportError:
                print("[ab_test] Redis not available, using in-memory metrics")

    def record_prediction(
        self,
        test_id: str,
        variant_name: str,
        model_id: str,
        game_id: str,
        prediction: float,
        latency_ms: float,
    ):
        """Record a prediction for metrics."""
        if self.redis:
            # Use Redis for distributed metrics
            key = f"ab_test:{test_id}:{variant_name}:predictions"
            self.redis.incr(key)

            # Store latency
            latency_key = f"ab_test:{test_id}:{variant_name}:latency"
            self.redis.lpush(latency_key, latency_ms)
            self.redis.ltrim(latency_key, 0, 1000)  # Keep last 1000

            # Store prediction for later analysis
            pred_key = f"ab_test:{test_id}:{variant_name}:pred:{game_id}"
            self.redis.setex(pred_key, 86400 * 7, str(prediction))  # 7 days TTL

    def record_outcome(
        self,
        test_id: str,
        variant_name: str,
        game_id: str,
        outcome: bool,  # True if home team won
    ):
        """Record game outcome for accuracy calculation."""
        if self.redis:
            key = f"ab_test:{test_id}:{variant_name}:outcomes"
            self.redis.hset(key, game_id, "1" if outcome else "0")

    def get_metrics(self, test_id: str, variant_name: str) -> Dict:
        """Get metrics for a variant."""
        if not self.redis:
            return {}

        predictions_key = f"ab_test:{test_id}:{variant_name}:predictions"
        latency_key = f"ab_test:{test_id}:{variant_name}:latency"

        predictions_count = int(self.redis.get(predictions_key) or 0)

        # Calculate average latency
        latencies = self.redis.lrange(latency_key, 0, -1)
        avg_latency = 0.0
        if latencies:
            avg_latency = sum(float(lat) for lat in latencies) / len(latencies)

        return {
            "predictions": predictions_count,
            "avg_latency_ms": round(avg_latency, 2),
            "p50_latency_ms": self._percentile([float(lat) for lat in latencies], 50)
            if latencies
            else 0,
            "p95_latency_ms": self._percentile([float(lat) for lat in latencies], 95)
            if latencies
            else 0,
            "p99_latency_ms": self._percentile([float(lat) for lat in latencies], 99)
            if latencies
            else 0,
        }

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
