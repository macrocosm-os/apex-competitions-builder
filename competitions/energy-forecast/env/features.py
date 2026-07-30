"""Calendar feature computation, shared by the referee (building observations)
and baseline training (so the baseline sees exactly what evaluation feeds).

No external data or network access needed: every feature is a deterministic
function of the timestamp alone.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

HISTORY_HOURS = 168  # 7 days of confirmed hourly demand
HORIZON_HOURS = 24  # next-day forecast
NUM_FEATURES = 6  # demand, hour-of-day (sin/cos), day-of-week (sin/cos), is_holiday

# US federal holidays are the only "external" fact folded in, and they're a
# fixed calendar rule, not looked up at runtime -- same every year, computable
# offline. Approximate with the fixed-date holidays; the few date-shifted ones
# (Thanksgiving, MLK Day, etc.) are intentionally omitted to keep this a pure
# function with no dependency on a holiday library or table lookup.
_FIXED_HOLIDAYS = {(1, 1), (7, 4), (12, 25)}


def _is_holiday(dt: datetime) -> bool:
    return (dt.month, dt.day) in _FIXED_HOLIDAYS


def calendar_features(timestamp: str) -> list[float]:
    """hour-of-day and day-of-week encoded as sin/cos pairs (cyclical, no boundary jump)."""
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    hour_frac = dt.hour / 24.0
    dow_frac = dt.weekday() / 7.0
    return [
        math.sin(2 * math.pi * hour_frac),
        math.cos(2 * math.pi * hour_frac),
        math.sin(2 * math.pi * dow_frac),
        math.cos(2 * math.pi * dow_frac),
        1.0 if _is_holiday(dt) else 0.0,
    ]


def build_observation(history: list[float], history_timestamps: list[str]) -> np.ndarray:
    """Flatten (demand, calendar features) per hour into the player's fixed input vector.

    Demand is normalized per-instance (divide by the window's own mean) so the
    model sees a scale-free load shape rather than raw MWh, which varies by
    two orders of magnitude across Balancing Authorities.
    """
    demand = np.asarray(history, dtype=np.float64)
    scale = max(float(demand.mean()), 1.0)
    normalized = demand / scale
    cal = np.array([calendar_features(ts) for ts in history_timestamps], dtype=np.float64)
    obs = np.concatenate([normalized[:, None], cal], axis=1)  # [HISTORY_HOURS, NUM_FEATURES]
    return obs.astype(np.float32).ravel()


def denormalize(prediction: np.ndarray, history: list[float]) -> np.ndarray:
    """Invert build_observation's scaling to get MWh back out of the model's output."""
    scale = max(float(np.mean(history)), 1.0)
    return np.asarray(prediction, dtype=np.float64) * scale
