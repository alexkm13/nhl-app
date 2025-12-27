"""
A/B testing analysis and reporting tools.
"""

from typing import Dict, Optional
from datetime import datetime
import pandas as pd


class ABTestAnalyzer:
    """Analyze A/B test results."""

    def __init__(self, db_url: str):
        """
        Initialize analyzer.

        Args:
            db_url: Database URL
        """
        self.db_url = db_url

    def get_comparison_report(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        game_id: Optional[str] = None,
    ) -> Dict:
        """
        Generate comparison report between variants.

        Args:
            start_time: Start time for analysis
            end_time: End time for analysis
            game_id: Optional game ID filter

        Returns:
            Dictionary with comparison metrics
        """
        try:
            import psycopg

            with psycopg.connect(self.db_url) as conn:
                query = """
                    SELECT
                        variant_name,
                        model_id,
                        COUNT(*) as prediction_count,
                        AVG(prediction) as avg_prediction,
                        STDDEV(prediction) as stddev_prediction,
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY prediction) as median_prediction,
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

                with conn.cursor() as cur:
                    cur.execute(query, params)
                    results = cur.fetchall()

                    variants = {}
                    for row in results:
                        (
                            variant_name,
                            model_id,
                            count,
                            avg_pred,
                            stddev_pred,
                            median_pred,
                            min_pred,
                            max_pred,
                        ) = row
                        variants[variant_name] = {
                            "model_id": model_id,
                            "prediction_count": count,
                            "avg_prediction": float(avg_pred) if avg_pred else 0.0,
                            "stddev_prediction": float(stddev_pred)
                            if stddev_pred
                            else 0.0,
                            "median_prediction": float(median_pred)
                            if median_pred
                            else 0.0,
                            "min_prediction": float(min_pred) if min_pred else 0.0,
                            "max_prediction": float(max_pred) if max_pred else 0.0,
                        }

                    # Calculate comparison metrics if we have multiple variants
                    comparison = {}
                    variant_names = list(variants.keys())
                    if len(variant_names) >= 2:
                        # Compare first two variants
                        v1_name = variant_names[0]
                        v2_name = variant_names[1]
                        v1 = variants[v1_name]
                        v2 = variants[v2_name]

                        avg_diff = v1["avg_prediction"] - v2["avg_prediction"]
                        comparison = {
                            "variant_a": v1_name,
                            "variant_b": v2_name,
                            "avg_prediction_diff": avg_diff,
                            "avg_prediction_diff_pct": (
                                avg_diff / v2["avg_prediction"] * 100
                            )
                            if v2["avg_prediction"] > 0
                            else 0,
                            "sample_size_a": v1["prediction_count"],
                            "sample_size_b": v2["prediction_count"],
                        }

                    return {
                        "variants": variants,
                        "comparison": comparison,
                        "period": {
                            "start": start_time.isoformat() if start_time else None,
                            "end": end_time.isoformat() if end_time else None,
                        },
                    }
        except Exception as e:
            return {"error": str(e)}

    def get_time_series(
        self,
        start_time: datetime,
        end_time: datetime,
        interval_minutes: int = 60,
        game_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Get time series data for variants.

        Args:
            start_time: Start time
            end_time: End time
            interval_minutes: Time interval in minutes
            game_id: Optional game ID filter

        Returns:
            DataFrame with time series data
        """
        try:
            import psycopg

            with psycopg.connect(self.db_url) as conn:
                query = """
                    SELECT
                        DATE_TRUNC('minute', timestamp) as time_bucket,
                        variant_name,
                        COUNT(*) as prediction_count,
                        AVG(prediction) as avg_prediction
                    FROM ab_test_predictions
                    WHERE timestamp >= %s AND timestamp <= %s
                """
                params = [start_time, end_time]

                if game_id:
                    query += " AND game_id = %s"
                    params.append(game_id)

                query += """
                    GROUP BY time_bucket, variant_name
                    ORDER BY time_bucket, variant_name
                """

                with conn.cursor() as cur:
                    cur.execute(query, params)
                    results = cur.fetchall()

                    df = pd.DataFrame(
                        results,
                        columns=[
                            "time_bucket",
                            "variant_name",
                            "prediction_count",
                            "avg_prediction",
                        ],
                    )

                    return df
        except Exception as e:
            print(f"Error getting time series: {e}")
            return pd.DataFrame()


def print_ab_test_report(report: Dict):
    """Print a formatted A/B test report."""
    print("\n" + "=" * 80)
    print("A/B Test Report")
    print("=" * 80)

    if "error" in report:
        print(f"Error: {report['error']}")
        return

    print("\nVariant Metrics:")
    print("-" * 80)
    for variant_name, metrics in report.get("variants", {}).items():
        print(f"\n{variant_name} ({metrics['model_id']}):")
        print(f"  Predictions: {metrics['prediction_count']:,}")
        print(f"  Avg Prediction: {metrics['avg_prediction']:.4f}")
        print(f"  Std Dev: {metrics['stddev_prediction']:.4f}")
        print(f"  Median: {metrics['median_prediction']:.4f}")
        print(
            f"  Range: [{metrics['min_prediction']:.4f}, {metrics['max_prediction']:.4f}]"
        )

    comparison = report.get("comparison", {})
    if comparison:
        print("\n" + "-" * 80)
        print("Comparison:")
        print(f"  {comparison['variant_a']} vs {comparison['variant_b']}:")
        print(
            f"    Avg Prediction Difference: {comparison['avg_prediction_diff']:.4f} ({comparison['avg_prediction_diff_pct']:.2f}%)"
        )
        print(
            f"    Sample Sizes: {comparison['sample_size_a']:,} vs {comparison['sample_size_b']:,}"
        )

    period = report.get("period", {})
    if period.get("start") or period.get("end"):
        print("\n" + "-" * 80)
        print("Period:")
        if period.get("start"):
            print(f"  Start: {period['start']}")
        if period.get("end"):
            print(f"  End: {period['end']}")

    print("\n" + "=" * 80 + "\n")
