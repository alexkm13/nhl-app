"""Pydantic models for API responses."""

from pydantic import BaseModel


class WinProb(BaseModel):
    """Win probability response model."""

    game_id: str
    p_home_win: float
    model_id: str
    ts: float
