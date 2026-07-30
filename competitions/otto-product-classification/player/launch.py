"""otto_product_classification gym_v1 PLAYER server (the image's evaluate command).

The platform writes the miner's submission to /app/submission.csv; this server parses and
structurally validates it at startup, then answers /act with the probability rows for the ids
the referee asks for. There is no miner code in this sandbox — the artifact is a CSV, the most
constrained artifact type there is, so validation is structural rather than screening.

Contract (also in README.md):
    header exactly: id,Class_1,Class_2,...,Class_9
    one row per test id, 9 finite probabilities in [0,1] summing to 1 +/- 1e-3
A submission that violates the FILE-level contract fails startup, the process exits, readiness
never succeeds, and the platform files a typed failure against the submission — exactly like
humanoid_parkour's ONNX loader rejecting a malformed graph.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from apex_sdk.gym_v1 import Player, serve

from env.submission_io import SubmissionError, read_submission

# Overridable so miners (and tools/local_eval.py) can serve a local file; in the sandbox the
# platform always writes to the spec's target_path.
SUBMISSION_PATH = os.environ.get("SUBMISSION_PATH", "/app/submission.csv")


class OttoPlayer(Player):
    def __init__(self, path: str = SUBMISSION_PATH) -> None:
        # Parse + structurally validate here so a broken CSV can never become ready.
        # ~18.5k rows: ~0.2 s, ~8 MB resident. If a future test set were 10x larger, a flat
        # array("d") plus an id->offset dict would cut this to ~1.5 MB; not needed at this size.
        self._rows = read_submission(path)

    # is_ready() keeps the SDK default (True): loading is synchronous in __init__, so there is
    # no warm-up to report and a background-load + polling readiness would be pure ceremony.

    def reset(self, match_id: str, player_index: int, seed: int, config: dict[str, Any]) -> None:
        # The referee tells us how many rows it expects. Fail fast and loudly on a mismatch:
        # the unhandled exception becomes HTTP 500 -> PlayerError in the referee ->
        # terminal_reason "reset_failed". A typed submission failure the miner can act on.
        n = (config or {}).get("num_test_rows")
        if n is not None and len(self._rows) != n:
            raise ValueError(f"submission has {len(self._rows)} rows, expected {n}")

    def act(self, observation: Any, deadline_ms: int) -> Any:  # noqa: ARG002
        # observation is the batch's list of test ids; return one row per id, in order.
        #
        # An unknown id yields None, which the referee gates as "missing_row" (MAX_ROW_LOSS).
        # We deliberately do NOT substitute a uniform row: that would earn ln(9) = 2.197 for
        # rows the miner never predicted, which is better than many honest guesses. Silent
        # generosity is a metric hole.
        #
        # deadline_ms is ignored: this is a dict lookup, and the dominant cost is the SDK's
        # JSON serialization (~20 ms for a 4096-row batch). The referee's HTTP timeout is the
        # enforcement point.
        return [self._rows.get(int(i)) for i in observation]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        player = OttoPlayer()
    except SubmissionError as e:
        # Typed, miner-actionable, and fatal: exit non-zero so readiness never succeeds.
        print(f"submission rejected [{e.gate}]: {e.detail}", file=sys.stderr)
        raise SystemExit(1) from None
    serve(player, port=args.port, readiness_path="/health")
