#!/usr/bin/env python3
"""Test goal distance calculation on real NHL game data."""
import asyncio
import httpx
import math
import json
from datetime import datetime


def calculate_goal_distance(x_coord: float, y_coord: float, goal_x: float) -> int:
    """Calculate distance from shot location to goal using Euclidean distance."""
    return int(round(math.sqrt((x_coord - goal_x)**2 + y_coord**2)))


async def fetch_game_data(game_id: str):
    """Fetch play-by-play data from NHL API."""
    NHL_API_BASE = "https://api-web.nhle.com/v1"
    url = f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error fetching game {game_id}: {response.status_code}")
            return None


def determine_goal_x(x_coord: float, team: str, home_defending_side: str, home_team_id: int, away_team_id: int, event_owner_id: int) -> float:
    """Determine which goal to measure to based on game state."""
    if x_coord < 0:
        # Negative coordinates: -100 to 100 system
        return -89
    elif x_coord <= 200:
        # 0-200 coordinate system (most common)
        if home_defending_side == "right":
            # Home defends right, away attacks right (x > 100 area)
            # Home attacks left (x < 100 area)
            if team == "HOME":
                return 0  # Home attacks left goal
            else:
                return 200  # Away attacks right goal
        elif home_defending_side == "left":
            # Home defends left, home attacks left (x < 100 area)
            # Away attacks right (x > 100 area)
            if team == "HOME":
                return 200  # Home attacks right goal
            else:
                return 0  # Away attacks left goal
        else:
            # Fallback: use coordinate position
            if x_coord <= 100:
                return 0
            else:
                return 200
    else:
        # Coordinates outside expected range (> 200)
        if x_coord < 100:
            return 89
        else:
            return -89


async def analyze_real_game_goals(game_id: str):
    """Analyze goals from a real NHL game and calculate distances."""
    print(f"Fetching game data for game {game_id}...")
    game_data = await fetch_game_data(game_id)
    
    if not game_data:
        print("Failed to fetch game data")
        return
    
    # Get team info
    home_team = game_data.get("homeTeam", {})
    away_team = game_data.get("awayTeam", {})
    home_team_id = home_team.get("id")
    away_team_id = away_team.get("id")
    home_team_name = home_team.get("commonName", {}).get("default", "Home")
    away_team_name = away_team.get("commonName", {}).get("default", "Away")
    
    print(f"\nGame: {away_team_name} @ {home_team_name}")
    print(f"Game ID: {game_id}")
    print("="*70)
    print()
    
    plays = game_data.get("plays", [])
    goals = []
    
    # Extract all goals
    for play in plays:
        type_code = str(play.get("typeCode", ""))
        if type_code == "505":  # Goal
            details = play.get("details", {})
            event_owner_id = details.get("eventOwnerTeamId")
            
            # Determine team
            if event_owner_id == home_team_id:
                team = "HOME"
                team_name = home_team_name
            elif event_owner_id == away_team_id:
                team = "AWAY"
                team_name = away_team_name
            else:
                continue
            
            # Get coordinates
            x_coord = details.get("xCoord")
            y_coord = details.get("yCoord")
            
            if x_coord is not None and y_coord is not None:
                # Get shot type
                shot_type = details.get("shotType", "")
                
                # Determine goal position
                home_defending_side = play.get("homeTeamDefendingSide", "")
                goal_x = determine_goal_x(x_coord, team, home_defending_side, home_team_id, away_team_id, event_owner_id)
                
                # Calculate distance
                distance = calculate_goal_distance(x_coord, y_coord, goal_x)
                
                # Get time
                time_in_period = play.get("timeInPeriod", "00:00")
                period = play.get("periodDescriptor", {}).get("number", 1)
                
                goals.append({
                    "team": team_name,
                    "period": period,
                    "time": time_in_period,
                    "x": x_coord,
                    "y": y_coord,
                    "goal_x": goal_x,
                    "distance": distance,
                    "shot_type": shot_type,
                })
    
    if not goals:
        print("No goals found with coordinate data")
        return
    
    print(f"Found {len(goals)} goals with coordinate data:")
    print("-"*70)
    print()
    
    for i, goal in enumerate(goals, 1):
        print(f"Goal #{i}:")
        print(f"  Team: {goal['team']}")
        print(f"  Time: Period {goal['period']}, {goal['time']}")
        print(f"  Location: x={goal['x']:.1f}, y={goal['y']:.1f}")
        print(f"  Goal position: x={goal['goal_x']:.1f}")
        print(f"  Distance: {goal['distance']} feet")
        print(f"  Shot type: {goal['shot_type']}")
        print()
    
    # Statistics
    distances = [g['distance'] for g in goals]
    print("="*70)
    print("Distance Statistics:")
    print(f"  Total goals: {len(goals)}")
    print(f"  Average distance: {sum(distances) / len(distances):.1f} feet")
    print(f"  Minimum distance: {min(distances)} feet")
    print(f"  Maximum distance: {max(distances)} feet")
    print()
    
    # Categorize by distance
    close_goals = [g for g in goals if g['distance'] <= 10]
    medium_goals = [g for g in goals if 10 < g['distance'] <= 30]
    long_goals = [g for g in goals if g['distance'] > 30]
    
    print("Distance Categories:")
    print(f"  Close range (≤10 feet): {len(close_goals)} goals")
    if close_goals:
        examples = ', '.join([f"{g['distance']}ft" for g in close_goals[:3]])
        print(f"    Examples: {examples}")
    print(f"  Medium range (11-30 feet): {len(medium_goals)} goals")
    if medium_goals:
        examples = ', '.join([f"{g['distance']}ft" for g in medium_goals[:3]])
        print(f"    Examples: {examples}")
    print(f"  Long range (>30 feet): {len(long_goals)} goals")
    if long_goals:
        examples = ', '.join([f"{g['distance']}ft" for g in long_goals[:3]])
        print(f"    Examples: {examples}")
    print()
    

async def main():
    """Main function to test with a recent game."""
    import sys
    
    # Check for command line argument
    if len(sys.argv) > 1:
        game_id = sys.argv[1]
        await analyze_real_game_goals(game_id)
        return
    
    # Try to find a recent game
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get("https://api-web.nhle.com/v1/schedule/now")
            if response.status_code == 200:
                schedule = response.json()
                weeks = schedule.get("gameWeek", [])
                if weeks:
                    games = weeks[0].get("games", [])
                    if games:
                        # Use the first completed or live game
                        for game in games:
                            game_id = str(game.get("id", ""))
                            if game_id:
                                await analyze_real_game_goals(game_id)
                                return
    except Exception as e:
        print(f"Error fetching schedule: {e}")
    
    # Fallback: use a known game ID
    print("No game ID provided. Using fallback game ID.")
    print("Usage: python3 test_real_game_distances.py <game_id>")
    print("Example: python3 test_real_game_distances.py 2024020589")
    
    # Try a fallback game ID (format: YYYYMMDDNN where NN is game number)
    fallback_game_id = "2024020589"  # Example game
    print(f"\nTrying fallback game ID: {fallback_game_id}")
    await analyze_real_game_goals(fallback_game_id)


if __name__ == "__main__":
    asyncio.run(main())

