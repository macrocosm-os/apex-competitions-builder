"""Proposed `entrypoints.resolve` for energy_forecast (see ../PLATFORM_PROPOSAL.md).

Does NOT exist as a platform-invoked entrypoint yet -- apex.competition.v1 has
no lifecycle phase after round close. This is the reference implementation
the platform-side extension would call, `resolution_delay_days` after the
round that produced LOCKED_PREDICTIONS_FILE (the "pending_resolution"
metadata written by referee.py in "live" mode). Written now so the scoring
logic is ready the moment the extension lands, and so tools/simulate_two_phase.py
can exercise the full lock -> resolve loop locally today.

Expected inputs (paths via env vars, mirroring generate_round's shape):
    LOCKED_PREDICTIONS_FILE  JSON: the "locked_predictions" list from the
                             lock-phase round's result.json metadata.
    GROUND_TRUTH_FILE        JSON: {ba: [[timestamp, demand_mwh], ...], ...}
                             published by fetch_ground_truth.py for the
                             relevant date(s) -- content-hashed, produced
                             independently of any specific round/submission.
Output:
    /data/result.json  same GameResult shape as referee.py, this time with a
                        REAL raw_score, overwriting the round's placeholder.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from apex_sdk.gym_v1.referee import GameResult

from env.scoring import instance_skill_score

RESULT_PATH = Path("/data/result.json")


def _ground_truth_lookup(feed: dict) -> dict[str, dict[str, float]]:
    """ba -> {timestamp: demand_mwh}, for O(1) target assembly per instance."""
    return {ba: {ts: val for ts, val in rows} for ba, rows in feed.items()}


def resolve(locked_predictions: list[dict], ground_truth: dict) -> GameResult:
    truth_by_ba = _ground_truth_lookup(ground_truth)
    records = []
    for rec in locked_predictions:
        ba_truth = truth_by_ba.get(rec["ba"], {})
        target = [ba_truth.get(ts) for ts in rec["target_timestamps"]]
        if any(v is None for v in target):
            # Ground truth feed doesn't cover this instance's target yet --
            # a resolve run too early relative to resolution_delay_days.
            records.append(
                {"instance_id": rec["instance_id"], "ba": rec["ba"], "gate": "ground_truth_missing", "skill": 0.0}
            )
            continue
        skill, diag = instance_skill_score(rec["locked_prediction"], target, rec["history"])
        records.append({"instance_id": rec["instance_id"], "ba": rec["ba"], "skill": skill, **diag})

    raw = sum(r["skill"] for r in records) / len(records) if records else 0.0
    return GameResult(
        raw_scores=[raw],
        winner=0 if raw > 0 else -1,
        terminal_reason="resolved",
        steps=len(records),
        metadata={"instances": records, "num_instances": len(records)},
    )


if __name__ == "__main__":
    locked = json.loads(Path(os.environ["LOCKED_PREDICTIONS_FILE"]).read_text())
    truth = json.loads(Path(os.environ["GROUND_TRUTH_FILE"]).read_text())
    result = resolve(locked, truth)
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(asdict(result)))
