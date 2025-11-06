"""Standings API routes."""
import httpx

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/v1", tags=["standings"])

NHL_API_BASE = "https://api-web.nhle.com/v1"


@router.get("/standings")
async def get_standings():
    """Get current NHL standings with full team information"""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.get(f"{NHL_API_BASE}/standings/now")
            if response.status_code == 200:
                data = response.json()
                
                standings = data.get("standings", [])
                standings_list = []
                
                for team_data in standings:
                    if isinstance(team_data, dict):
                        team_info = {
                            "abbreviation": team_data.get("teamAbbrev", {}).get("default", ""),
                            "name": team_data.get("teamName", {}).get("default", ""),
                            "place_name": team_data.get("placeName", {}).get("default", ""),
                            "common_name": team_data.get("commonName", {}).get("default", ""),
                            "wins": team_data.get("wins", 0),
                            "losses": team_data.get("losses", 0),
                            "ot_losses": team_data.get("otLosses", 0),
                            "points": team_data.get("points", 0),
                            "games_played": team_data.get("gamesPlayed", 0),
                            "goals_for": team_data.get("goalFor", 0),
                            "goals_against": team_data.get("goalAgainst", 0),
                            "logo": team_data.get("teamLogo", "")
                        }
                        
                        full_name = f"{team_info['place_name']} {team_info['common_name']}".strip()
                        if not full_name:
                            full_name = team_info['name']
                        team_info['full_name'] = full_name
                        
                        standings_list.append(team_info)
                
                standings_list.sort(key=lambda x: (x['points'], x['wins']), reverse=True)
                
                return {"standings": standings_list}
            else:
                raise HTTPException(status_code=response.status_code, detail=f"Standings API error {response.status_code}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching standings: {str(e)}")

