"""Historical + live grid-demand data access.

Two data sources feed this module, both pinned/content-hashed rather than
fetched live from inside any sandbox (sandboxes get no internet, ever):

- `data/<ba>_history.csv` — hourly confirmed demand, refreshed once a day by
  `resolver/fetch_ground_truth.py` (run outside any Apex sandbox, e.g. GitHub
  Actions) and baked into the referee image at the next build.
- `data/<ba>_pending.json` — per-round locked predictions awaiting real-world
  ground truth, written at lock time and consumed by `resolver/resolve.py`
  once EIA publishes the corresponding actuals. See `resolver/README` in
  PLATFORM_PROPOSAL.md for the full lock -> resolve lifecycle this assumes.

Column format (`data/<ba>_history.csv`): `timestamp,demand_mwh`, hourly,
UTC ISO-8601, strictly increasing, no gaps (rows are interpolated at fetch
time if EIA reports a missing hour — see `resolver/fetch_ground_truth.py`).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from env.features import HISTORY_HOURS, HORIZON_HOURS

# US Balancing Authorities spanning different climates/sizes/timezones --
# diverse enough for a stratified pool, and (in "live" mode, see
# sample_instances below) large enough that N per round isn't capped at a
# handful of instances. Codes match EIA-930's `respondent` field; verify the
# full roster against https://www.eia.gov/electricity/gridmonitor/about
# before launch -- this list is a representative starting set, not final.
BALANCING_AUTHORITIES = [
    "CISO",
    "ERCO",
    "PJM",
    "MISO",
    "SWPP",
    "NYIS",
    "ISNE",
    "SOCO",
    "TVA",
    "DUK",
    "FPL",
    "PACE",
    "PSCO",
    "BPAT",
    "AZPS",
    "SRP",
    "PNM",
    "NEVP",
    "PGE",
    "IPCO",
]

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Instance:
    """One forecasting task: history is what the player sees; target is what scores it."""

    instance_id: str  # f"{ba}:{lock_timestamp}" — stable key across lock -> resolve
    ba: str
    history_timestamps: list[str]
    history: list[float]
    lock_timestamp: str
    target_timestamps: list[str]
    # None in "live" mode: the outcome hasn't happened yet at lock time.
    # Populated in "backtest" mode (dev/sizing) and by resolve.py once real.
    target: list[float] | None


def load_series(ba: str) -> tuple[list[str], list[float]]:
    """Load the full pinned hourly series for one BA. Raises if the file is missing."""
    path = DATA_DIR / f"{ba}_history.csv"
    timestamps: list[str] = []
    values: list[float] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            timestamps.append(row["timestamp"])
            values.append(float(row["demand_mwh"]))
    return timestamps, values


def _next_hourly_timestamps(last_timestamp: str, n: int) -> list[str]:
    """The n hours immediately after last_timestamp -- computed, not sliced,
    so it works even when those rows don't exist in the series yet (live mode:
    the target period genuinely hasn't happened, so there's nothing to slice)."""
    start = datetime.fromisoformat(last_timestamp.replace("Z", "+00:00"))
    return [(start + timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:00:00Z") for i in range(n)]


def _make_instance(ba: str, timestamps: list[str], values: list[float], start: int) -> Instance:
    hist_end = start + HISTORY_HOURS
    target_end = hist_end + HORIZON_HOURS
    lock_timestamp = timestamps[hist_end - 1]
    return Instance(
        instance_id=f"{ba}:{lock_timestamp}",
        ba=ba,
        history_timestamps=timestamps[start:hist_end],
        history=values[start:hist_end],
        lock_timestamp=lock_timestamp,
        target_timestamps=_next_hourly_timestamps(lock_timestamp, HORIZON_HOURS),
        target=values[hist_end:target_end] if target_end <= len(values) else None,
    )


def sample_instances(seed: int, n: int, mode: str = "backtest", holdout_hours: int = 0) -> list[Instance]:
    """Deterministically sample n task instances from the per-round master seed.

    mode="backtest": windows drawn uniformly from the pinned historical pool,
    target already known — used for local dev, baseline training, and
    sigma_round sizing (evaluation-design.md). Every submission in a round
    sees the exact same instances -> no seed-fishing.

    mode="live": one instance per tracked BA, history ending at the most
    recent confirmed hour, target left as None (genuinely hasn't happened
    yet). This is what a production round evaluates; scoring happens later
    in resolve.py once resolver/fetch_ground_truth.py publishes the outcome.
    `holdout_hours` locks history that many hours before the series' true
    end instead of at its true end -- tools/simulate_two_phase.py uses this
    to rehearse the full lock -> resolve loop locally, treating the pinned
    series' own tail as the "future" outcome, without needing genuinely
    future data. Production always uses holdout_hours=0.
    """
    rng = np.random.default_rng(np.random.SeedSequence(seed))
    instances: list[Instance] = []

    if mode == "live":
        for ba in BALANCING_AUTHORITIES:
            timestamps, values = load_series(ba)
            start = len(values) - HISTORY_HOURS - holdout_hours
            if start < 0:
                raise ValueError(f"not enough confirmed history for {ba}")
            instances.append(_make_instance(ba, timestamps, values, start))
        return instances

    per_ba = max(1, n // len(BALANCING_AUTHORITIES))
    for ba in BALANCING_AUTHORITIES:
        timestamps, values = load_series(ba)
        last_valid_start = len(values) - HISTORY_HOURS - HORIZON_HOURS
        if last_valid_start < 0:
            raise ValueError(f"pinned history too short for {ba}: {len(values)} hours")
        starts = rng.integers(0, last_valid_start + 1, size=per_ba)
        instances.extend(_make_instance(ba, timestamps, values, int(s)) for s in starts)
    return instances[:n] if n else instances
