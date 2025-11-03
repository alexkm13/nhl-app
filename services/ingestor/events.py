from typing import Literal, Optional

from pydantic import BaseModel, Field

Team = Literal["HOME", "AWAY"]
Strength = Literal["EV", "PP", "PK", "EN", "ENPP", "ENPK", "SH"]
EventType = Literal["FACEOFF", "SHOT", "GOAL", "PENALTY", "BLOCK", "HIT"]

class GameEvent(BaseModel):
    game_id: str
    ts: float = Field(description="unix timestamp seconds")
    team: Team
    event_type: EventType
    strength: Strength = "EV"
    empty_net: bool = False
    player_id: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    shot_quality: Optional[float] = None
