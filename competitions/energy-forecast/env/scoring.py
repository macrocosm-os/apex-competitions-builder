"""Forecast scoring: skill vs. a seasonal-naive baseline, plus anti-Goodhart gates.

raw_score for one instance = 1 - MAE(model) / MAE(seasonal_naive), so:
  - 0.0  means "no better than yesterday's same-hour value"
  - >0   genuine forecasting skill
  - <0   worse than the trivial baseline (still scoreable, just bad)
A round's raw_score is the mean over all instances (env/data.py samples them).
"""

from __future__ import annotations

import numpy as np

# Clip per-instance skill so one anomalous grid event (a heat-wave demand
# spike, an outage) can't blow up or dominate the round mean either direction.
SKILL_CLIP = 3.0

# A prediction whose range is this small relative to the input history's own
# variability is judged degenerate (flat-lining near the mean trivially beats
# noisy instances without doing any real forecasting).
MIN_OUTPUT_STD_RATIO = 0.05


def seasonal_naive(history: list[float]) -> np.ndarray:
    """Yesterday's same 24 hours -- the last HORIZON_HOURS of the input window."""
    return np.asarray(history[-24:], dtype=np.float64)


def instance_skill_score(prediction: np.ndarray, target: list[float], history: list[float]) -> tuple[float, dict]:
    """Score one instance. Returns (score, diagnostics) -- diagnostics go in metadata."""
    pred = np.asarray(prediction, dtype=np.float64)
    truth = np.asarray(target, dtype=np.float64)

    if pred.shape != truth.shape or not np.all(np.isfinite(pred)):
        return 0.0, {"gate": "invalid_output", "shape": list(pred.shape)}

    hist_std = float(np.std(history))
    if hist_std > 0 and float(np.std(pred)) < MIN_OUTPUT_STD_RATIO * hist_std:
        return 0.0, {"gate": "degenerate_flat_output", "pred_std": float(np.std(pred))}

    naive = seasonal_naive(history)
    mae_model = float(np.mean(np.abs(pred - truth)))
    mae_naive = float(np.mean(np.abs(naive - truth)))

    if mae_naive == 0.0:
        skill = 0.0 if mae_model == 0.0 else -SKILL_CLIP
    else:
        skill = 1.0 - mae_model / mae_naive

    skill = float(np.clip(skill, -SKILL_CLIP, SKILL_CLIP))
    return skill, {
        "gate": None,
        "mae_model": round(mae_model, 3),
        "mae_naive": round(mae_naive, 3),
        "skill": round(skill, 4),
    }
