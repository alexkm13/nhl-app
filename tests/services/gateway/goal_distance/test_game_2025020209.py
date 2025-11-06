#!/usr/bin/env python3
"""Test goal distance for game 2025020209 - synchronous version."""
import json
import math
import urllib.request
import urllib.parse

def calculate_goal_distance(x_coord: float, y_coord: float, goal_x: float) -> int:
    """Calculate distance from shot location to goal using Euclidean distance."""
    return int(round(math.sqrt((x_coord - goal_x)**2 + y_coord**2)))

def test_game(game_id):
    """Test goal distances for a specific game."""
    url = f"https://api-web.nhle.com/v1/gamecenter/{game_id}/play-by-play"
    
    print(f"Fetching game {game_id}...")
    
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            if response.status != 200:
                print(f"Error: HTTP {response.status}")
                return
            game_data = json.loads(response.read())
    except Exception as e:
        print(f"Error fetching game: {e}")
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
    
    plays = game_data.get("plays", [])
    goals = []
    
    # Cache period 1 baseline for goal positions (arena-specific)
    period1_baseline = None
    
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
                # NHL coordinate system: goals are at 89 feet and -89 feet
                # Different arenas have home teams starting on different sides
                # We cache the period 1 baseline to determine correct goal positions
                # Teams switch sides between periods (alternate each period)
                
                period = play.get("periodDescriptor", {}).get("number", 1)
                home_defending_side = play.get("homeTeamDefendingSide", "")
                
                # Establish period 1 baseline when processing first period 1 play
                if period == 1 and period1_baseline is None:
                    if home_defending_side == "right":
                        # Period 1: Home defends right, attacks left → home goal at -89
                        period1_baseline = {
                            "home_goal_x": -89,
                            "away_goal_x": 89
                        }
                    elif home_defending_side == "left":
                        # Period 1: Home defends left, attacks right → home goal at 89
                        period1_baseline = {
                            "home_goal_x": 89,
                            "away_goal_x": -89
                        }
                    else:
                        # Fallback: assume home starts on left (goal at 89)
                        period1_baseline = {
                            "home_goal_x": 89,
                            "away_goal_x": -89
                        }
                
                # If we still don't have a baseline (shouldn't happen, but handle it)
                if period1_baseline is None:
                    # Use current period's defending side to infer
                    if home_defending_side == "right":
                        period1_baseline = {
                            "home_goal_x": -89,
                            "away_goal_x": 89
                        }
                    else:
                        period1_baseline = {
                            "home_goal_x": 89,
                            "away_goal_x": -89
                        }
                
                # Determine goal positions based on period and period 1 baseline
                is_odd_period = (period % 2 == 1)
                
                if is_odd_period:
                    # Odd periods (1, 3, 5...): Use period 1 baseline
                    home_goal_x = period1_baseline["home_goal_x"]
                    away_goal_x = period1_baseline["away_goal_x"]
                else:
                    # Even periods (2, 4, 6...): Opposite of period 1 baseline
                    home_goal_x = period1_baseline["away_goal_x"]  # Home goal is where away was in period 1
                    away_goal_x = period1_baseline["home_goal_x"]  # Away goal is where home was in period 1
                
                # Determine which goal the scoring team is attacking
                if team == "HOME":
                    # Home team is attacking the away goal
                    goal_x = away_goal_x
                else:
                    # Away team is attacking the home goal
                    goal_x = home_goal_x
                
                # Calculate distance
                distance = calculate_goal_distance(x_coord, y_coord, goal_x)
                
                # Get time
                time_in_period = play.get("timeInPeriod", "00:00")
                period = play.get("periodDescriptor", {}).get("number", 1)
                
                goals.append({
                    "team": team_name,
                    "period": period,
                    "time": time_in_period,
                    "x": float(x_coord),
                    "y": float(y_coord),
                    "goal_x": goal_x,
                    "distance": distance,
                    "shot_type": shot_type,
                })
    
    if not goals:
        print("No goals found with coordinate data")
        return
    
    print(f"\nFound {len(goals)} goals with coordinate data:\n")
    
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
    

if __name__ == "__main__":
    test_game("2025020209")

