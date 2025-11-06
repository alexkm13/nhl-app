from typing import Literal, Optional

from pydantic import BaseModel


class GameState(BaseModel):
    game_id: str
    ts: float
    home_score: int = 0
    away_score: int = 0
    strength: Literal["EV", "PP", "PK", "EN", "ENPP", "ENPK", "SH"] = "EV"
    empty_net: bool = False
    last_event: str = "FACEOFF"
    last_player_id: Optional[int] = None

    def goal(self, team: str):
        if team == "HOME":
            self.home_score += 1
        else:
            self.away_score += 1
