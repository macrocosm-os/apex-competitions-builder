"""Exercise the proposed lock -> resolve lifecycle locally, end to end.

`apex-dev run` doesn't execute the referee loop at all yet, and the platform
has no delayed-scoring primitive today (see PLATFORM_PROPOSAL.md) — this
script is the local stand-in so the whole design can be validated before
either lands:

1. Run the player against a "live"-mode round (target genuinely held out of
   the referee's own backtest pool, standing in for "hasn't happened yet").
   Capture the resulting locked-predictions metadata, exactly as referee.py
   would persist it in production.
2. Feed a ground-truth file for that exact target (built from the SAME pinned
   history — i.e. the "future" period the live round pretended not to know)
   into resolve.py's resolve() function.
3. Print the final score and confirm it matches what env/scoring.py would
   compute directly, i.e. resolve.py and referee.py never disagree.

    python tools/simulate_two_phase.py --onnx baseline/baseline.onnx --seed 0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "resolver"))

from env.data import BALANCING_AUTHORITIES, load_series  # noqa: E402
from env.features import HORIZON_HOURS  # noqa: E402
from local_eval import evaluate_once  # noqa: E402
from resolve import resolve  # noqa: E402


def _held_out_ground_truth() -> dict:
    """Build a ground-truth feed covering the last HORIZON_HOURS of each BA's
    pinned series — the same period a "live" round's most recent window
    targets, standing in for fetch_ground_truth.py's daily publish."""
    feed = {}
    for ba in BALANCING_AUTHORITIES:
        timestamps, values = load_series(ba)
        tail_start = len(values) - HORIZON_HOURS
        feed[ba] = list(zip(timestamps[tail_start:], values[tail_start:]))
    return feed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    print("--- lock phase (referee.py, mode=live, holdout_hours=HORIZON_HOURS) ---")
    # holdout_hours=HORIZON_HOURS locks history HORIZON_HOURS before the
    # series' true end, so the pinned series' own tail stands in for the
    # held-out target -- reproduces the live shape without needing genuinely
    # future data. Production always uses holdout_hours=0.
    lock_result = evaluate_once(args.onnx, args.seed, mode="live", holdout_hours=HORIZON_HOURS)
    locked_predictions = lock_result.metadata["locked_predictions"]
    print(f"locked {len(locked_predictions)} predictions, terminal_reason={lock_result.terminal_reason}")

    print("\n--- resolve phase (resolve.py) ---")
    ground_truth = _held_out_ground_truth()
    final_result = resolve(locked_predictions, ground_truth)
    print(json.dumps(final_result.__dict__, indent=2))
