"""Multiclass log loss — the single source of truth for otto_product_classification.

Shared by the referee and every tool so the numbers can never diverge (the env/scoring.py
pattern from humanoid-parkour). Stdlib only: no numpy anywhere in the eval path, so the
referee image needs no pip installs, there is no pinned version that could silently drift a
score, and this module is unit-testable in any Python 3.11+.

Kaggle's Otto formula:
    logloss = -(1/N) * sum_i sum_j y_ij * log(p_ij)
Kaggle rescales each row to sum to 1 BEFORE clipping ("the submitted probabilities for a
given data point are not required to sum to one, because they are rescaled prior to being
scored"), then clips to [eps, 1-eps] with eps = 1e-15. ORDER MATTERS — clipping first and
renormalizing second gives a different number. Only the true class contributes, so the whole
metric reduces to:
    -mean(log(clip(p_true / row_sum)))
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

CLASSES: tuple[str, ...] = tuple(f"Class_{i}" for i in range(1, 10))
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}
NUM_CLASSES = len(CLASSES)

CLIP_EPS = 1e-15  # Kaggle's value. Part of the metric's definition, NOT a round knob.
MAX_ROW_LOSS = -math.log(CLIP_EPS)  # 34.538776394910684
UNIFORM_LOGLOSS = math.log(NUM_CLASSES)  # 2.1972245773362196 — the do-nothing reference

# A row must sum to 1 within this tolerance to be accepted. Stricter than Kaggle (which
# renormalizes anything) so the published contract is unambiguous; renormalization still
# runs afterwards to absorb the remaining slack.
ROW_SUM_TOL = 1e-3
VALUE_TOL = 1e-9


def row_gate(values: Sequence[float]) -> str | None:
    """Return a gate name if this row is invalid, else None.

    Gate names are the only submission-visible failure vocabulary: a miner learns *which*
    contract they broke and how many rows broke it, never which rows were scored well.
    """
    if len(values) != NUM_CLASSES:
        return "wrong_width"
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return "non_finite"
    if any(v < -VALUE_TOL or v > 1.0 + VALUE_TOL for v in values):
        return "out_of_range"
    total = math.fsum(values)
    if not (1.0 - ROW_SUM_TOL <= total <= 1.0 + ROW_SUM_TOL):
        return "row_sum"
    return None


def row_loss(values: Sequence[float], true_index: int, eps: float = CLIP_EPS) -> float:
    """Kaggle log-loss contribution of one already-gated row."""
    total = math.fsum(values)
    if total <= 0.0:  # unreachable after row_gate; belt and braces
        return MAX_ROW_LOSS
    p = min(max(values[true_index] / total, eps), 1.0 - eps)
    return -math.log(p)


def multiclass_logloss(
    rows: Iterable[Sequence[float]],
    true_indices: Iterable[int],
    eps: float = CLIP_EPS,
) -> float:
    """Mean row loss over paired (row, true_index).

    Invalid rows are charged MAX_ROW_LOSS. math.fsum over the per-row losses makes the
    result independent of accumulation order — the same submission scores identically
    forever. Raises ValueError on a length mismatch: that is a referee bug, not a submission
    bug, and must NOT be swallowed into a score.
    """
    losses: list[float] = []
    for values, ti in zip(rows, true_indices, strict=True):
        losses.append(MAX_ROW_LOSS if row_gate(values) else row_loss(values, ti, eps))
    if not losses:
        raise ValueError("no rows to score")
    return math.fsum(losses) / len(losses)
