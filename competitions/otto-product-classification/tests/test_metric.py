"""Identities the metric must satisfy. Stdlib only — no new dev dependencies."""

import math

import pytest

from env.metric import (
    CLIP_EPS,
    MAX_ROW_LOSS,
    NUM_CLASSES,
    UNIFORM_LOGLOSS,
    multiclass_logloss,
    row_gate,
    row_loss,
)

UNIFORM = [1.0 / NUM_CLASSES] * NUM_CLASSES


def _onehot(i: int) -> list[float]:
    v = [0.0] * NUM_CLASSES
    v[i] = 1.0
    return v


def test_uniform_scores_exactly_ln_nine():
    # The integration assertion the whole competition is calibrated against.
    assert multiclass_logloss([UNIFORM], [0]) == UNIFORM_LOGLOSS == math.log(9)


def test_correct_onehot_scores_zero_within_clip():
    # 1.0 is clipped to 1 - eps, so the loss is ~1e-15, not exactly 0.
    assert multiclass_logloss([_onehot(3)], [3]) == pytest.approx(0.0, abs=1e-14)


def test_wrong_onehot_costs_the_maximum():
    assert multiclass_logloss([_onehot(0)], [5]) == pytest.approx(MAX_ROW_LOSS)


def test_max_row_loss_is_the_worst_a_valid_row_can_score():
    # This is why failures are charged MAX_ROW_LOSS rather than inf or ln(9): under
    # lower_is_better a failure must rank at or below every honest submission, and ln(9) would
    # rank a failure BETTER than a genuinely bad honest attempt.
    assert MAX_ROW_LOSS == -math.log(CLIP_EPS)
    assert MAX_ROW_LOSS > UNIFORM_LOGLOSS


def test_rescale_happens_before_clip():
    # Kaggle rescales rows to sum to 1 and only then clips. A row of all-equal values scores
    # ln(9) whatever its scale, which is only true in that order.
    scaled = [0.5 / NUM_CLASSES] * NUM_CLASSES  # sums to 0.5
    assert row_loss(scaled, 0) == pytest.approx(UNIFORM_LOGLOSS)


def test_only_the_true_class_contributes():
    a = [0.6, 0.4] + [0.0] * (NUM_CLASSES - 2)
    b = [0.6, 0.2, 0.2] + [0.0] * (NUM_CLASSES - 3)
    assert row_loss(a, 0) == pytest.approx(row_loss(b, 0))


@pytest.mark.parametrize(
    "row,gate",
    [
        (UNIFORM, None),
        ([1.0] + [0.0] * (NUM_CLASSES - 1), None),
        (UNIFORM[:-1], "wrong_width"),
        ([float("nan")] + UNIFORM[1:], "non_finite"),
        ([float("inf")] + UNIFORM[1:], "non_finite"),
        ([-0.5, 1.5] + UNIFORM[2:], "out_of_range"),
        ([0.0] * NUM_CLASSES, "row_sum"),
        ([v * 2 for v in UNIFORM], "row_sum"),
    ],
)
def test_row_gate(row, gate):
    assert row_gate(row) == gate


def test_bool_is_not_a_probability():
    assert row_gate([True] + [False] * (NUM_CLASSES - 1)) == "non_finite"


def test_invalid_rows_are_charged_not_skipped():
    score = multiclass_logloss([UNIFORM, [0.0] * NUM_CLASSES], [0, 0])
    assert score == pytest.approx((UNIFORM_LOGLOSS + MAX_ROW_LOSS) / 2)


def test_length_mismatch_is_a_referee_bug_not_a_score():
    with pytest.raises(ValueError):
        multiclass_logloss([UNIFORM, UNIFORM], [0])


def test_empty_input_raises():
    with pytest.raises(ValueError):
        multiclass_logloss([], [])


def test_score_is_order_independent():
    # math.fsum, not a running total: the same rows in any order give the same bits.
    rows = [[0.9] + [0.0125] * 8, UNIFORM, [0.2] * 4 + [0.05] * 4 + [0.0]]
    idx = [0, 4, 2]
    forward = multiclass_logloss(rows, idx)
    backward = multiclass_logloss(rows[::-1], idx[::-1])
    assert forward == backward
