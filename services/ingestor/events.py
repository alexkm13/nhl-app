from typing import Literal, Optional

from pydantic import BaseModel, Field

Team = Literal["HOME", "AWAY"]
Strength = Literal["EV", "PP", "PK"]
EventType = Literal["FACEOFF", "SHOT", "GOAL", "PENALTY", "BLOCK", "HIT"]

class GameEvent(BaseModel):
    game_id: str
    ts: float = Field(description="unix timestamp seconds")
    team: Team
    event_type: EventType
    strength: Strength = "EV"
    x: Optional[float] = None
    y: Optional[float] = None
    shot_quality: Optional[float] = None
