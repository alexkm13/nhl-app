from pydantic import BaseModel, Field
from typing import Literal

class GameState(BaseModel):
    game_id: str
    ts: float
    home_score: int = 0
    away_score: int = 0
    strength: Literal["EV", "PP", "PK"] = "EV"
    last_event: str = "FACEOFF"

    def goal(self, team: str):
        if team == "HOME":
            self.home_score += 1
        else:
            self.away_score += 1
