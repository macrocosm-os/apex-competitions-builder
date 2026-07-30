"""Generate placeholder data/<ba>_history.csv files for LOCAL DEVELOPMENT ONLY.

Real history comes exclusively from resolver/fetch_ground_truth.py (real
EIA-930 data, requires EIA_API_KEY). This script exists so the referee,
baseline trainer, and local tools all have something to run against before
the daily refresh pipeline has ever run — synthetic diurnal + weekly +
seasonal demand curves with noise, per tracked BA, at a different amplitude
and phase per BA so the pool is non-trivial to memorize.

    python tools/generate_synthetic_history.py --days 400
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from env.data import BALANCING_AUTHORITIES, DATA_DIR  # noqa: E402


def _profile_for(seed: int) -> tuple[float, float, float, float, float]:
    """Deterministic (base_load, daily_amp, weekly_amp, seasonal_amp, noise_std)
    per BA, varied by a seeded draw so the pool isn't one repeated shape."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(15_000, 90_000)
    return (base, base * 0.18, base * 0.05, base * 0.22, base * 0.015)


def generate(hours: int, seed: int) -> tuple[list[str], list[float]]:
    rng = np.random.default_rng(seed)
    base, daily_amp, weekly_amp, seasonal_amp, noise_std = _profile_for(seed)
    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours)
    timestamps, values = [], []
    for h in range(hours):
        t = start + timedelta(hours=h)
        daily = daily_amp * np.sin(2 * np.pi * (t.hour - 6) / 24)  # peak mid-afternoon
        weekly = -weekly_amp if t.weekday() >= 5 else 0.0  # lower demand on weekends
        seasonal = seasonal_amp * np.sin(2 * np.pi * (t.timetuple().tm_yday - 200) / 365)  # summer peak
        noise = rng.normal(0, noise_std)
        values.append(max(base + daily + weekly + seasonal + noise, 0.0))
        timestamps.append(t.strftime("%Y-%m-%dT%H:00:00Z"))
    return timestamps, values


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for i, ba in enumerate(BALANCING_AUTHORITIES):
        timestamps, values = generate(args.days * 24, seed=args.seed + i)
        path = DATA_DIR / f"{ba}_history.csv"
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "demand_mwh"])
            writer.writerows(zip(timestamps, (round(v, 1) for v in values)))
        print(f"wrote {path} ({len(values)} hours)")
