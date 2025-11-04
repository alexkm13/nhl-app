#!/usr/bin/env python3
"""
Improve model based on A/B test results and prediction analysis.
"""
import os
import sys
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import psycopg


def get_prediction_errors(db_url: str, days: int = 7) -> pd.DataFrame:
    """
    Get prediction errors by comparing predictions to actual outcomes.
    
    Args:
        db_url: Database URL
        days: Number of days to analyze
    
    Returns:
        DataFrame with prediction errors
    """
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Get predictions and actual game outcomes
                # First, get game start times to calculate seconds elapsed
                query = """
                    WITH game_starts AS (
                        SELECT game_id, MIN(ts) as game_start
                        FROM features
                        WHERE ts >= NOW() - INTERVAL '%s days'
                        GROUP BY game_id
                    )
                    SELECT 
                        p.game_id,
                        p.model_id,
                        p.ts,
                        p.p_home_win,
                        f.home_score,
                        f.away_score,
                        f.ts as game_ts,
                        EXTRACT(EPOCH FROM (f.ts - gs.game_start)) as seconds_elapsed
                    FROM predictions p
                    JOIN features f ON p.game_id = f.game_id 
                        AND p.ts = f.ts
                    JOIN game_starts gs ON p.game_id = gs.game_id
                    WHERE p.ts >= NOW() - INTERVAL '%s days'
                    ORDER BY p.ts DESC
                """
                
                df = pd.read_sql_query(query, conn, params=[days])
                
                if df.empty:
                    return pd.DataFrame()
                
                # Calculate actual outcomes (final score)
                # Get final scores for each game
                final_scores_query = """
                    SELECT 
                        game_id,
                        MAX(ts) as final_ts,
                        MAX(home_score) as final_home_score,
                        MAX(away_score) as final_away_score
                    FROM features
                    WHERE ts >= NOW() - INTERVAL '%s days'
                    GROUP BY game_id
                """
                
                final_scores = pd.read_sql_query(final_scores_query, conn, params=[days])
                
                # Merge with predictions
                df = df.merge(
                    final_scores,
                    on='game_id',
                    how='left',
                    suffixes=('', '_final')
                )
                
                # Calculate actual win probability at prediction time
                # Actual win = 1 if home wins, 0 if away wins
                df['actual_home_win'] = (df['final_home_score'] > df['final_away_score']).astype(int)
                
                # Calculate prediction error
                df['prediction_error'] = df['p_home_win'] - df['actual_home_win']
                df['abs_error'] = df['prediction_error'].abs()
                
                # Calculate Brier score (squared error)
                df['brier_score'] = (df['prediction_error'] ** 2)
                
                # Calculate log loss (avoid log(0))
                df['log_loss'] = -(
                    df['actual_home_win'] * np.log(df['p_home_win'].clip(0.001, 0.999)) +
                    (1 - df['actual_home_win']) * np.log((1 - df['p_home_win']).clip(0.001, 0.999))
                )
                
                return df
    except Exception as e:
        print(f"Error getting prediction errors: {e}")
        return pd.DataFrame()


def analyze_error_patterns(df: pd.DataFrame) -> Dict:
    """
    Analyze error patterns to identify improvement opportunities.
    
    Args:
        df: DataFrame with prediction errors
    
    Returns:
        Dictionary with analysis results
    """
    if df.empty:
        return {"error": "No data available"}
    
    analysis = {}
    
    # Overall metrics
    analysis['overall'] = {
        'mean_abs_error': float(df['abs_error'].mean()),
        'mean_brier_score': float(df['brier_score'].mean()),
        'mean_log_loss': float(df['log_loss'].mean()),
        'total_predictions': len(df),
    }
    
    # Error by score differential
    df['score_diff'] = df['home_score'] - df['away_score']
    df['score_diff_bin'] = pd.cut(df['score_diff'], bins=[-10, -2, -1, 0, 1, 2, 10], 
                                   labels=['Large Away Lead', 'Away Lead', 'Tied', 'Home Lead', 'Large Home Lead'])
    
    error_by_score_diff = df.groupby('score_diff_bin').agg({
        'abs_error': 'mean',
        'brier_score': 'mean',
        'p_home_win': 'mean',
        'actual_home_win': 'mean'
    }).to_dict()
    
    analysis['by_score_differential'] = {
        'mean_abs_error': error_by_score_diff['abs_error'],
        'mean_brier_score': error_by_score_diff['brier_score'],
        'predicted_win_prob': error_by_score_diff['p_home_win'],
        'actual_win_rate': error_by_score_diff['actual_home_win'],
    }
    
    # Error by game time (seconds elapsed)
    df['time_bin'] = pd.cut(df['ts'], bins=[0, 600, 1200, 1800, 2400, 3600],
                            labels=['0-10min', '10-20min', '20-30min', '30-40min', '40-60min'])
    
    error_by_time = df.groupby('time_bin').agg({
        'abs_error': 'mean',
        'brier_score': 'mean',
    }).to_dict()
    
    analysis['by_game_time'] = {
        'mean_abs_error': error_by_time['abs_error'],
        'mean_brier_score': error_by_time['brier_score'],
    }
    
    # Error by prediction confidence
    df['confidence_bin'] = pd.cut(df['p_home_win'], bins=[0, 0.2, 0.4, 0.6, 0.8, 1.0],
                                    labels=['Very Low', 'Low', 'Medium', 'High', 'Very High'])
    
    error_by_confidence = df.groupby('confidence_bin').agg({
        'abs_error': 'mean',
        'brier_score': 'mean',
        'prediction_error': 'mean',
    }).to_dict()
    
    analysis['by_confidence'] = {
        'mean_abs_error': error_by_confidence['abs_error'],
        'mean_brier_score': error_by_confidence['brier_score'],
        'mean_error': error_by_confidence['prediction_error'],
    }
    
    # Calibration analysis
    # Group predictions into bins and compare to actual outcomes
    df['prob_bin'] = pd.cut(df['p_home_win'], bins=10)
    calibration = df.groupby('prob_bin').agg({
        'p_home_win': 'mean',
        'actual_home_win': 'mean',
        'abs_error': 'mean',
    })
    
    analysis['calibration'] = {
        'predicted_probs': calibration['p_home_win'].tolist(),
        'actual_rates': calibration['actual_home_win'].tolist(),
        'mean_abs_error': calibration['abs_error'].tolist(),
    }
    
    # Identify worst predictions
    worst_predictions = df.nlargest(20, 'abs_error')[
        ['game_id', 'ts', 'p_home_win', 'actual_home_win', 'abs_error', 
         'home_score', 'away_score', 'score_diff', 'model_id']
    ].to_dict('records')
    
    analysis['worst_predictions'] = worst_predictions
    
    return analysis


def generate_improvement_recommendations(analysis: Dict) -> List[str]:
    """
    Generate recommendations for model improvement based on analysis.
    
    Args:
        analysis: Analysis results from analyze_error_patterns
    
    Returns:
        List of improvement recommendations
    """
    recommendations = []
    
    if 'error' in analysis:
        return ["No data available for analysis"]
    
    # Check calibration
    if 'calibration' in analysis:
        cal = analysis['calibration']
        predicted_probs = cal.get('predicted_probs', [])
        actual_rates = cal.get('actual_rates', [])
        
        if predicted_probs and actual_rates:
            # Check for systematic over/under prediction
            overconfident = sum(1 for p, a in zip(predicted_probs, actual_rates) 
                              if p is not None and a is not None and abs(p - a) > 0.1)
            if overconfident > len(predicted_probs) * 0.3:
                recommendations.append(
                    "Model appears overconfident - predictions are too extreme. "
                    "Consider adding temperature scaling or Platt scaling for calibration."
                )
    
    # Check error by score differential
    if 'by_score_differential' in analysis:
        score_diff = analysis['by_score_differential']
        errors = score_diff.get('mean_abs_error', {})
        
        # Find score differentials with highest error
        if errors:
            max_error_key = max(errors.keys(), key=lambda k: errors.get(k, 0) if errors.get(k) is not None else 0)
            max_error = errors.get(max_error_key, 0)
            
            if max_error and max_error > analysis['overall']['mean_abs_error'] * 1.2:
                recommendations.append(
                    f"High error for {max_error_key} - model struggles with this score differential. "
                    f"Consider adding features specific to this game state."
                )
    
    # Check error by game time
    if 'by_game_time' in analysis:
        time_error = analysis['by_game_time'].get('mean_abs_error', {})
        if time_error:
            max_time_error_key = max(time_error.keys(), 
                                   key=lambda k: time_error.get(k, 0) if time_error.get(k) is not None else 0)
            max_time_error = time_error.get(max_time_error_key, 0)
            
            if max_time_error and max_time_error > analysis['overall']['mean_abs_error'] * 1.2:
                recommendations.append(
                    f"High error during {max_time_error_key} - model may need time-specific features. "
                    f"Consider adding features for game phase or momentum."
                )
    
    # Check error by confidence
    if 'by_confidence' in analysis:
        conf_error = analysis['by_confidence'].get('mean_abs_error', {})
        if conf_error:
            # Check if high confidence predictions have high error
            high_conf_error = conf_error.get('Very High', 0)
            if high_conf_error and high_conf_error > analysis['overall']['mean_abs_error'] * 1.1:
                recommendations.append(
                    "High confidence predictions have elevated error - model may be overconfident. "
                    "Consider calibration techniques or reducing confidence thresholds."
                )
    
    # Overall recommendations
    overall = analysis.get('overall', {})
    mean_brier = overall.get('mean_brier_score', 0)
    
    if mean_brier > 0.25:
        recommendations.append(
            f"High Brier score ({mean_brier:.3f}) indicates poor calibration. "
            "Consider recalibration or ensemble methods."
        )
    
    mean_abs_error = overall.get('mean_abs_error', 0)
    if mean_abs_error > 0.3:
        recommendations.append(
            f"High mean absolute error ({mean_abs_error:.3f}) suggests model may benefit from: "
            "1) More training data, 2) Feature engineering, 3) Hyperparameter tuning, 4) Ensemble methods"
        )
    
    return recommendations


def print_analysis_report(analysis: Dict, recommendations: List[str]):
    """Print formatted analysis report."""
    print("\n" + "="*80)
    print("Model Performance Analysis")
    print("="*80)
    
    if 'error' in analysis:
        print(f"\nError: {analysis['error']}")
        return
    
    overall = analysis.get('overall', {})
    print(f"\nOverall Metrics:")
    print(f"  Total Predictions: {overall.get('total_predictions', 0):,}")
    print(f"  Mean Absolute Error: {overall.get('mean_abs_error', 0):.4f}")
    print(f"  Mean Brier Score: {overall.get('mean_brier_score', 0):.4f}")
    print(f"  Mean Log Loss: {overall.get('mean_log_loss', 0):.4f}")
    
    if 'by_score_differential' in analysis:
        print(f"\nError by Score Differential:")
        score_diff = analysis['by_score_differential']
        errors = score_diff.get('mean_abs_error', {})
        for key, error in errors.items():
            if error is not None:
                print(f"  {key}: {error:.4f}")
    
    if 'by_game_time' in analysis:
        print(f"\nError by Game Time:")
        time_error = analysis['by_game_time'].get('mean_abs_error', {})
        for key, error in time_error.items():
            if error is not None:
                print(f"  {key}: {error:.4f}")
    
    if 'calibration' in analysis:
        print(f"\nCalibration Analysis:")
        cal = analysis['calibration']
        predicted_probs = cal.get('predicted_probs', [])
        actual_rates = cal.get('actual_rates', [])
        for i, (pred, actual) in enumerate(zip(predicted_probs, actual_rates)):
            if pred is not None and actual is not None:
                print(f"  Bin {i+1}: Predicted {pred:.3f}, Actual {actual:.3f}, Diff {abs(pred-actual):.3f}")
    
    print(f"\n" + "="*80)
    print("Improvement Recommendations:")
    print("="*80)
    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec}")
    
    print("\n" + "="*80 + "\n")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Analyze model performance and generate improvements")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL"),
                       help="Database URL")
    parser.add_argument("--days", type=int, default=7,
                       help="Number of days to analyze")
    parser.add_argument("--output", help="Output file for analysis JSON")
    
    args = parser.parse_args()
    
    if not args.db_url:
        print("Error: DATABASE_URL not provided")
        sys.exit(1)
    
    print(f"Analyzing model performance for last {args.days} days...")
    
    # Get prediction errors
    df = get_prediction_errors(args.db_url, args.days)
    
    if df.empty:
        print("No prediction data found. Run some predictions first.")
        sys.exit(1)
    
    # Analyze error patterns
    analysis = analyze_error_patterns(df)
    
    # Generate recommendations
    recommendations = generate_improvement_recommendations(analysis)
    
    # Print report
    print_analysis_report(analysis, recommendations)
    
    # Save to file if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump({
                'analysis': analysis,
                'recommendations': recommendations
            }, f, indent=2, default=str)
        print(f"Analysis saved to {args.output}")


if __name__ == "__main__":
    main()

