#!/usr/bin/env python3
"""Test script for win probability history array and graph data."""
import asyncio
import httpx
import os
import sys

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

async def test_history(game_id: str):
    """Test the win probability history endpoint."""
    print(f"\n{'='*60}")
    print(f"Testing Win Probability History for Game: {game_id}")
    print(f"{'='*60}\n")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Test history endpoint
            print("1. Fetching history data...")
            response = await client.get(f"{API_BASE}/v1/games/{game_id}/winprob/history")
            
            if response.status_code != 200:
                print(f"   ❌ Error: {response.status_code} - {response.text}")
                return
            
            data = response.json()
            history_data = data.get('data', [])
            
            print("   ✓ Response received")
            print(f"   Game ID: {data.get('game_id', 'N/A')}")
            print(f"   Data points: {len(history_data)}")
            
            if not history_data:
                print("\n   ⚠️  No history data found!")
                print("   This could mean:")
                print("   - Predictions haven't been stored yet")
                print("   - Game hasn't started or model hasn't processed events")
                print("   - Database connection issue")
                return
            
            # Analyze data
            print("\n2. Data Analysis:")
            times = [p['ts'] for p in history_data]
            probs = [p['p_home_win'] for p in history_data]
            
            print(f"   Time range: {min(times):.0f}s to {max(times):.0f}s")
            print(f"   Duration: {max(times) - min(times):.0f} seconds ({((max(times) - min(times))/60):.1f} minutes)")
            print(f"   Probability range: {min(probs):.3f} to {max(probs):.3f}")
            print(f"   Average probability: {sum(probs)/len(probs):.3f}")
            
            # Show first few points
            print("\n3. First 5 data points:")
            for i, point in enumerate(history_data[:5], 1):
                minutes = int(point['ts'] // 60)
                seconds = int(point['ts'] % 60)
                print(f"   [{i}] {minutes:02d}:{seconds:02d} - Home Win Prob: {point['p_home_win']:.3f} ({point['p_home_win']*100:.1f}%)")
            
            # Show last few points
            print("\n4. Last 5 data points:")
            for i, point in enumerate(history_data[-5:], len(history_data)-4):
                minutes = int(point['ts'] // 60)
                seconds = int(point['ts'] % 60)
                print(f"   [{i}] {minutes:02d}:{seconds:02d} - Home Win Prob: {point['p_home_win']:.3f} ({point['p_home_win']*100:.1f}%)")
            
            # Check for gaps
            print("\n5. Data Quality Check:")
            gaps = []
            for i in range(len(history_data) - 1):
                gap = history_data[i+1]['ts'] - history_data[i]['ts']
                if gap > 300:  # More than 5 minutes
                    gaps.append((i, gap))
            
            if gaps:
                print(f"   ⚠️  Found {len(gaps)} large gaps (>5 min):")
                for idx, gap in gaps[:5]:
                    print(f"      Gap of {gap:.0f}s between points {idx} and {idx+1}")
            else:
                print("   ✓ No large gaps detected")
            
            # Check if data is suitable for graphing
            print("\n6. Graph Readiness:")
            if len(history_data) >= 10:
                print(f"   ✓ Sufficient data points ({len(history_data)} >= 10)")
            else:
                print(f"   ⚠️  Limited data points ({len(history_data)} < 10)")
                print("   Frontend will generate synthetic points from play-by-play")
            
            # Test current win probability
            print("\n7. Current Win Probability:")
            try:
                wp_response = await client.get(f"{API_BASE}/v1/games/{game_id}/winprob")
                if wp_response.status_code == 200:
                    wp_data = wp_response.json()
                    current_prob = wp_data.get('p_home_win', 0)
                    print(f"   Current: {current_prob:.3f} ({current_prob*100:.1f}%)")
                    
                    if history_data:
                        last_prob = history_data[-1]['p_home_win']
                        if abs(current_prob - last_prob) > 0.01:
                            print(f"   ⚠️  Current prob differs from last history point by {abs(current_prob - last_prob):.3f}")
                        else:
                            print("   ✓ Current prob matches last history point")
                else:
                    print(f"   ⚠️  Could not fetch current win probability: {wp_response.status_code}")
            except Exception as e:
                print(f"   ⚠️  Error fetching current win probability: {e}")
            
            print(f"\n{'='*60}")
            print("Test Complete!")
            print(f"{'='*60}\n")
            
        except httpx.RequestError as e:
            print(f"   ❌ Network error: {e}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()

async def list_recent_games():
    """List recent games to help choose a game ID."""
    print("\nFetching recent games...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{API_BASE}/v1/games")
            if response.status_code == 200:
                games = response.json().get('games', [])
                print(f"\nFound {len(games)} games:\n")
                for game in games[:10]:  # Show first 10
                    game_id = game.get('game_id', 'N/A')
                    home = game.get('home_team', 'N/A')
                    away = game.get('away_team', 'N/A')
                    state = game.get('game_state', 'N/A')
                    print(f"  {game_id}: {away} @ {home} ({state})")
                if len(games) > 10:
                    print(f"\n  ... and {len(games) - 10} more games")
            else:
                print(f"Error fetching games: {response.status_code}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        game_id = sys.argv[1]
        asyncio.run(test_history(game_id))
    else:
        print("Usage: python test_history.py <game_id>")
        print("\nExample: python test_history.py 2025020161")
        print("\nFetching recent games to help you choose...")
        asyncio.run(list_recent_games())

