#!/usr/bin/env python3
"""Test goal distance calculation on real NHL game data - simplified version."""
import asyncio
import httpx
import math
import sys


def calculate_goal_distance(x_coord: float, y_coord: float, goal_x: float) -> int:
    """Calculate distance from shot location to goal using Euclidean distance."""
    return int(round(math.sqrt((x_coord - goal_x)**2 + y_coord**2)))


async def test_game(game_id: str):
    """Test goal distances for a specific game."""
    NHL_API_BASE = "https://api-web.nhle.com/v1"
    url = f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play"
    
    output_lines = []
    output_lines.append(f"Fetching game {game_id}...\n")
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                output_lines.append(f"Error: HTTP {response.status_code}\n")
                with open(f"/tmp/game_{game_id}_distances.txt", "w") as f:
                    f.writelines(output_lines)
                return
            game_data = response.json()
        except Exception as e:
            output_lines.append(f"Error fetching game: {e}\n")
            with open(f"/tmp/game_{game_id}_distances.txt", "w") as f:
                f.writelines(output_lines)
            return
    
    # Get team info
    home_team = game_data.get("homeTeam", {})
    away_team = game_data.get("awayTeam", {})
    home_team_id = home_team.get("id")
    away_team_id = away_team.get("id")
    home_team_name = home_team.get("commonName", {}).get("default", "Home")
    away_team_name = away_team.get("commonName", {}).get("default", "Away")
    
    output_lines.append(f"\nGame: {away_team_name} @ {home_team_name}\n")
    output_lines.append(f"Game ID: {game_id}\n")
    output_lines.append("="*70 + "\n")
    
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
                
                # Determine goal_x (matching main.py logic)
                if x_coord < 0:
                    goal_x = -89
                elif x_coord <= 200:
                    if home_defending_side == "right":
                        if team == "HOME":
                            goal_x = 0  # Home attacks left goal
                        else:
                            goal_x = 200  # Away attacks right goal
                    elif home_defending_side == "left":
                        if team == "HOME":
                            goal_x = 200  # Home attacks right goal
                        else:
                            goal_x = 0  # Away attacks left goal
                    else:
                        # Fallback: use coordinate position if defending side not available
                        if x_coord <= 100:
                            goal_x = 0
                        else:
                            goal_x = 200
                else:
                    # Coordinates outside expected range (> 200)
                    if x_coord < 100:
                        goal_x = 89
                    else:
                        goal_x = -89
                
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
        output_lines.append("No goals found with coordinate data\n")
        with open(f"/tmp/game_{game_id}_distances.txt", "w") as f:
            f.writelines(output_lines)
        return
    
    output_lines.append(f"\nFound {len(goals)} goals with coordinate data:\n\n")
    
    for i, goal in enumerate(goals, 1):
        output_lines.append(f"Goal #{i}:\n")
        output_lines.append(f"  Team: {goal['team']}\n")
        output_lines.append(f"  Time: Period {goal['period']}, {goal['time']}\n")
        output_lines.append(f"  Location: x={goal['x']:.1f}, y={goal['y']:.1f}\n")
        output_lines.append(f"  Goal position: x={goal['goal_x']:.1f}\n")
        output_lines.append(f"  Distance: {goal['distance']} feet\n")
        output_lines.append(f"  Shot type: {goal['shot_type']}\n")
        output_lines.append("\n")
    
    # Statistics
    distances = [g['distance'] for g in goals]
    output_lines.append("="*70 + "\n")
    output_lines.append("Distance Statistics:\n")
    output_lines.append(f"  Total goals: {len(goals)}\n")
    output_lines.append(f"  Average distance: {sum(distances) / len(distances):.1f} feet\n")
    output_lines.append(f"  Minimum distance: {min(distances)} feet\n")
    output_lines.append(f"  Maximum distance: {max(distances)} feet\n")
    output_lines.append("\n")
    
    # Check for wrap-arounds
    wrap_arounds = [g for g in goals if 'wrap' in g['shot_type'].lower() or (g['distance'] <= 10 and abs(g['y']) > 5)]
    if wrap_arounds:
        output_lines.append("Wrap-Around Goals:\n")
        for goal in wrap_arounds:
            output_lines.append(f"  {goal['team']} - {goal['distance']} feet (x={goal['x']:.1f}, y={goal['y']:.1f})\n")
        output_lines.append("\n")
    
    # Write to file and print
    output_text = "".join(output_lines)
    with open(f"/tmp/game_{game_id}_distances.txt", "w") as f:
        f.write(output_text)
    
    print(output_text, end="")


if __name__ == "__main__":
    game_id = sys.argv[1] if len(sys.argv) > 1 else "2025020209"
    asyncio.run(test_game(game_id))

