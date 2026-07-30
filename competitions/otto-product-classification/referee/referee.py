"""otto_product_classification gym_v1 REFEREE (the scorer sandbox, run at /app/referee.py).

Owns the ground truth: reads the platform-mounted, sha256-pinned private test labels, asks the
player for probabilities in batches of test ids, applies the validity gates, and computes
Kaggle multiclass log loss (env/metric.py). Lower is better.

The test set is FIXED. ctx.seed drives NOTHING — the evaluation is a pure function of
(submission bytes, /private/test_labels.csv, batch_size), so sigma_round is exactly 0 and
identical resubmissions score identically in every round, forever. Seed-fishing is therefore
structurally impossible. The seed is still passed to player.reset (protocol-shaped, and the
test ids are public anyway) and recorded in metadata for audit. If you came here looking for
the seed, its absence is the design, not an oversight.

FAILURE ATTRIBUTION — from apex_sdk.gym_v1.referee's module docstring:
    "Player HTTP error/timeout -> the referee decides (forfeit/retry/draw); raise/catch
     PlayerError in your play_game. The platform does not intervene.
     Referee crash / no result.json -> the platform scores 0 for all participants and
     attributes the failure to the REFEREE, not the submissions. So we DO NOT write a zeroed
     result on an unexpected crash: we let it propagate (no result.json)."
Accordingly:
    SUBMISSION failures -> return a GameResult with raw_scores=[MAX_ROW_LOSS] and a typed
                           terminal_reason. Always write a result.
    PLATFORM failures   -> raise (missing/hash-mismatched ground truth). Never write a result.

This referee assumes Layer-1 screening does not exist and re-checks every `screening` knob in
the spec itself. It must never trust the CSV.
"""

from __future__ import annotations

import math
import time
from collections import Counter

from apex_sdk.gym_v1 import GameResult, Referee, RefereeContext
from apex_sdk.gym_v1.client import PlayerClient, PlayerError

from env.labels import load_test_labels
from env.metric import MAX_ROW_LOSS, NUM_CLASSES, row_gate, row_loss

# Transport defaults; the round input (CONFIG_JSON) can override. Neither can change the score
# of a valid submission — see input.schema.json.
DEFAULT_BATCH_SIZE = 4096
DEFAULT_DEADLINE_MS = 5000


class OttoReferee(Referee):
    def play_game(self, ctx: RefereeContext, players: list[PlayerClient]) -> GameResult:
        start = time.monotonic()
        cfg = ctx.config or {}
        batch_size = max(1, int(cfg.get("batch_size", DEFAULT_BATCH_SIZE)))
        deadline_ms = int(cfg.get("deadline_ms", DEFAULT_DEADLINE_MS))
        player = players[0]

        # PLATFORM failure surface. A missing or hash-mismatched mount raises here, BEFORE any
        # player contact, so no result.json is written and the failure is attributed to the
        # referee. Never fetch, never fall back to a bundled copy, never score without truth.
        test_ids, true_index = load_test_labels()

        try:
            player.reset(
                match_id=ctx.match_id,
                player_index=0,
                seed=ctx.seed,
                config={"num_test_rows": len(test_ids), "num_classes": NUM_CLASSES},
            )
        except PlayerError as e:
            return self._failed("reset_failed", len(test_ids), ctx, start, str(e)[:200])

        losses: list[float] = []
        gates: Counter[str] = Counter()
        # Contiguous slices of the ascending test-id order: no shuffle, no sampling, no seed.
        for lo in range(0, len(test_ids), batch_size):
            ids = test_ids[lo : lo + batch_size]
            try:
                action = player.act(observation=ids, deadline_ms=deadline_ms)
            except PlayerError as e:
                return self._failed("player_error", len(test_ids), ctx, start, str(e)[:200])
            if not isinstance(action, list) or len(action) != len(ids):
                got = f"{type(action).__name__}" + (f" of {len(action)}" if isinstance(action, list) else "")
                return self._failed(
                    "bad_batch_shape", len(test_ids), ctx, start, f"expected {len(ids)} rows, got {got}"
                )

            for row, ti in zip(action, true_index[lo : lo + batch_size], strict=True):
                if row is None:
                    gate = "missing_row"
                elif isinstance(row, list):
                    gate = row_gate(row)
                else:
                    gate = "bad_row_type"
                if gate:
                    gates[gate] += 1
                    losses.append(MAX_ROW_LOSS)
                else:
                    losses.append(row_loss(row, ti))

        raw = math.fsum(losses) / len(losses)
        return GameResult(
            raw_scores=[raw],
            # Solo: the platform reads raw_scores[0]. 0 == a real score exists (parkour's
            # `0 if raw > 0` inverts meaninglessly when lower_is_better).
            winner=0,
            terminal_reason="scored",
            steps=len(losses),
            metadata={
                "logloss": round(raw, 6),
                "num_rows": len(losses),
                "num_invalid_rows": sum(gates.values()),
                "gates": dict(gates),
                "batch_size": batch_size,
                "seed": ctx.seed,  # audit only; drives nothing
                "eval_time_in_seconds": round(time.monotonic() - start, 2),
            },
            # NOTE: never put per-row losses in metadata. That is a per-row correctness
            # oracle — a partial answer key — and it is banned by the security checklist.
        )

    def _failed(self, reason: str, n: int, ctx: RefereeContext, start: float, detail: str = "") -> GameResult:
        """A SUBMISSION failure: worst finite score, typed reason, result written."""
        return GameResult(
            raw_scores=[MAX_ROW_LOSS],
            winner=-1,
            terminal_reason=reason,
            steps=0,
            metadata={
                "logloss": MAX_ROW_LOSS,
                "num_rows": 0,
                "failure": reason,
                "detail": detail,
                "num_test_rows": n,
                "seed": ctx.seed,
                "eval_time_in_seconds": round(time.monotonic() - start, 2),
            },
        )


if __name__ == "__main__":
    OttoReferee().run()
