#!/usr/bin/env python3
"""Run game distance test and save results to file."""
import asyncio
import httpx
import math
import sys

def calculate_goal_distance(x_coord: float, y_coord: float, goal_x: float) -> int:
    return int(round(math.sqrt((x_coord - goal_x)**2 + y_coord**2)))

async def test_game(game_id: str):
    output_lines = []
    
    NHL_API_BASE = "https://api-web.nhle.com/v1"
    url = f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play"
    
    output_lines.append(f"Fetching game {game_id}...\n")
    print(f"Fetching game {game_id}...", flush=True)
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url)
            if response.status_code != 200:
                error_msg = f"Error: HTTP {response.status_code}\n"
                output_lines.append(error_msg)
                print(error_msg, flush=True)
                return output_lines
            game_data = response.json()
        except Exception as e:
            error_msg = f"Error fetching game: {e}\n"
            output_lines.append(error_msg)
            print(error_msg, flush=True)
            import traceback
            traceback.print_exc()
            return output_lines
    
    home_team = game_data.get("homeTeam", {})
    away_team = game_data.get("awayTeam", {})
    home_team_id = home_team.get("id")
    away_team_id = away_team.get("id")
    home_team_name = home_team.get("commonName", {}).get("default", "Home")
    away_team_name = away_team.get("commonName", {}).get("default", "Away")
    
    game_info = f"\nGame: {away_team_name} @ {home_team_name}\nGame ID: {game_id}\n{'='*70}\n"
    output_lines.append(game_info)
    print(game_info, flush=True)
    
    plays = game_data.get("plays", [])
    goals = []
    
    # Cache period 1 baseline for goal positions (arena-specific)
    period1_baseline = None
    
    for play in plays:
        type_code = str(play.get("typeCode", ""))
        if type_code == "505":
            details = play.get("details", {})
            event_owner_id = details.get("eventOwnerTeamId")
            
            if event_owner_id == home_team_id:
                team = "HOME"
                team_name = home_team_name
            elif event_owner_id == away_team_id:
                team = "AWAY"
                team_name = away_team_name
            else:
                continue
            
            x_coord = details.get("xCoord")
            y_coord = details.get("yCoord")
            
            if x_coord is not None and y_coord is not None:
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
                
                distance = calculate_goal_distance(x_coord, y_coord, goal_x)
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
        msg = "No goals found with coordinate data\n"
        output_lines.append(msg)
        print(msg, flush=True)
        return output_lines
    
    header = f"\nFound {len(goals)} goals with coordinate data:\n\n"
    output_lines.append(header)
    print(header, flush=True)
    
    for i, goal in enumerate(goals, 1):
        goal_info = f"Goal #{i}:\n"
        goal_info += f"  Team: {goal['team']}\n"
        goal_info += f"  Time: Period {goal['period']}, {goal['time']}\n"
        goal_info += f"  Location: x={goal['x']:.1f}, y={goal['y']:.1f}\n"
        goal_info += f"  Goal position: x={goal['goal_x']:.1f}\n"
        goal_info += f"  Distance: {goal['distance']} feet\n"
        goal_info += f"  Shot type: {goal['shot_type']}\n\n"
        output_lines.append(goal_info)
        print(goal_info, flush=True)
    
    distances = [g['distance'] for g in goals]
    stats = "="*70 + "\n"
    stats += "Distance Statistics:\n"
    stats += f"  Total goals: {len(goals)}\n"
    stats += f"  Average distance: {sum(distances) / len(distances):.1f} feet\n"
    stats += f"  Minimum distance: {min(distances)} feet\n"
    stats += f"  Maximum distance: {max(distances)} feet\n\n"
    output_lines.append(stats)
    print(stats, flush=True)
    
    
    # Write to file
    with open(f"game_{game_id}_results.txt", "w") as f:
        f.writelines(output_lines)
    
    return output_lines

if __name__ == "__main__":
    game_id = sys.argv[1] if len(sys.argv) > 1 else "2025020209"
    results = asyncio.run(test_game(game_id))
    print("\nResults saved to game_{}_results.txt".format(game_id), flush=True)

