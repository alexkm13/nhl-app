import math

def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))

class BaselineModel:
    """A tiny baseline: P(home win) from score_diff and recency.
    Not a real model; just to make the pipeline live.
    """
    def __init__(self):
        # Tunable coefficients for demo
        self.b0 = 0.0
        self.b_score_diff = 1.2   # each goal swings log-odds
        self.b_recent = 0.15      # more weight as time goes on

    def predict(self, home_score: int, away_score: int, seconds_elapsed: float) -> float:
        score_diff = home_score - away_score
        t = min(seconds_elapsed / (20*60), 1.0)  # normalize 0..1 for 20-min demo
        z = self.b0 + self.b_score_diff * score_diff + self.b_recent * (2*t - 1)
        return sigmoid(z)
