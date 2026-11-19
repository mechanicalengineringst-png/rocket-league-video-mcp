"""Future-control value model V0: a small, inspectable logistic model of the next seconds (Round 13).

Trained by ``scripts/train_value_model.py`` on decision-time features (``state_features``) from the
public cohort (unknown rank). Two heads:
  next_touch_own   will our team make the next touch (within 3 s)?
  danger_5s        will the ball come within 2000 uu of our goal within 5 s?

Used for RANKING and COMPARING states (e.g. counterfactual action families, control timelines),
never shown to players as a percentage: the cohort is small, of unknown rank, and the numbers would
read as more precise than they are. Inference is numpy-only (no ML runtime dependency).
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from .state_features import frame_features, reach_times

MODEL_PATH = Path(__file__).resolve().parent / "models" / "future_control_v0.json"


class FutureControlModel:
    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.version = spec["version"]
        self.heads = spec["heads"]

    @classmethod
    @lru_cache(maxsize=1)
    def load(cls, path: str | None = None) -> "FutureControlModel | None":
        p = Path(path) if path else MODEL_PATH
        try:
            return cls(json.loads(p.read_text()))
        except (OSError, ValueError, KeyError):
            return None

    def _head(self, h: dict, f: dict[str, float]) -> float | None:
        z = h["intercept"]
        for name, w, mu, sd, med in zip(h["features"], h["coef"], h["mean"], h["std"], h["median"]):
            v = f.get(name, float("nan"))
            if v is None or (isinstance(v, float) and math.isnan(v)):
                v = med
            z += w * ((v - mu) / sd)
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def score_features(self, f: dict[str, float]) -> dict[str, float]:
        return {name: round(self._head(h, f), 4) for name, h in self.heads.items()}

    def score(self, frame: dict, team_of: dict[str, str], team: str, *, reach: dict | None = None) -> dict[str, float] | None:
        f = frame_features(frame, team_of, team, reach=reach if reach is not None else reach_times(frame))
        return None if f is None else self.score_features(f)
