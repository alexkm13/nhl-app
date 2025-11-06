#!/usr/bin/env python3
"""
Command-line tool for analyzing A/B test results.
"""
import os
import sys
import argparse
from datetime import datetime, timedelta
from ab_test_analyzer import ABTestAnalyzer, print_ab_test_report


def main():
    parser = argparse.ArgumentParser(description="Analyze A/B test results")
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL"),
        help="Database URL (default: DATABASE_URL env var)"
    )
    parser.add_argument(
        "--start-time",
        type=str,
        help="Start time (ISO format or 'N days ago')"
    )
    parser.add_argument(
        "--end-time",
        type=str,
        help="End time (ISO format, default: now)"
    )
    parser.add_argument(
        "--game-id",
        help="Filter by specific game ID"
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Number of days to analyze (default: 7)"
    )
    
    args = parser.parse_args()
    
    if not args.db_url:
        print("Error: DATABASE_URL not provided")
        sys.exit(1)
    
    # Parse time arguments
    end_time = datetime.utcnow()
    if args.end_time:
        try:
            end_time = datetime.fromisoformat(args.end_time.replace('Z', '+00:00'))
        except ValueError:
            print(f"Error: Invalid end_time format: {args.end_time}")
            sys.exit(1)
    
    start_time = None
    if args.start_time:
        try:
            if args.start_time.endswith(" days ago"):
                days = int(args.start_time.split()[0])
                start_time = end_time - timedelta(days=days)
            else:
                start_time = datetime.fromisoformat(args.start_time.replace('Z', '+00:00'))
        except ValueError:
            print(f"Error: Invalid start_time format: {args.start_time}")
            sys.exit(1)
    elif args.days:
        start_time = end_time - timedelta(days=args.days)
    else:
        # Default to last 7 days
        start_time = end_time - timedelta(days=7)
    
    # Create analyzer
    analyzer = ABTestAnalyzer(args.db_url)
    
    # Get report
    print(f"\nAnalyzing A/B test results...")
    print(f"Period: {start_time.isoformat()} to {end_time.isoformat()}")
    if args.game_id:
        print(f"Game ID: {args.game_id}")
    
    report = analyzer.get_comparison_report(
        start_time=start_time,
        end_time=end_time,
        game_id=args.game_id
    )
    
    # Print report
    print_ab_test_report(report)


if __name__ == "__main__":
    main()

