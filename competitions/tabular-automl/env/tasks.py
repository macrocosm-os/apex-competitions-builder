"""Deterministic per-round dataset generation + reference (baseline) models + loss.

Everything here is derived ONLY from the platform's per-round SEED (plus the
non-secret sizing knobs in the round input / CONFIG_JSON) -- no external data,
no network. Given the same SEED, calling `build_round` twice yields byte-identical
data, so identical resubmissions score identically within a round (no seed-fishing).

Task type rotates deterministically with the seed across FOUR families. The loss for
every family is defined so that LOWER IS ALWAYS BETTER, letting the referee normalize
against a reference model with one formula regardless of task type (see referee.py).
"Loss" here is never the family's native metric name (e.g. we never say "accuracy") --
it's always transformed into a lower-is-better number in a comparable range so
raw_score is meaningful across rotating task types.

v0.1.0 SCOPE NOTE: the original brief asked for six families (regression,
classification, timeseries, clustering, anomaly_detection, symbolic_regression).
Two are deliberately deferred, not silently shipped broken -- both were caught by
actually running the sizing procedure (see HANDOFF.md Sec 4 and tools_sizing_check.py),
not by inspection:

  - anomaly_detection: as specced, train_y hands the submission real anomaly labels,
    which makes it rare-class classification, not anomaly detection, and made a
    supervised submission beat the (deliberately unsupervised, label-blind)
    IsolationForest reference by ~4-5x -- an artifact of the mismatched reference,
    not real task difficulty. Needs a genuinely unsupervised/semi-supervised design
    (e.g. withhold train_y, score against a held-out labeled test split only) before
    it can rejoin the rotation.
  - symbolic_regression: sklearn's make_regression target is LINEAR in the informative
    features by construction, so a plain LinearRegression reference already achieves
    ~zero loss -- there is no nonlinear structure for a submission to discover, which
    defeats the entire point ("find the compact formula") from the original brief.
    Needs a real nonlinear-formula generator (e.g. random expression trees over
    {+,-,*,/,sin,exp} a la a symbolic-regression benchmark) before it can rejoin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.datasets import make_blobs, make_classification, make_regression
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import adjusted_rand_score, log_loss, mean_squared_error

TASK_TYPES = [
    "regression",
    "classification",
    "timeseries",
    "clustering",
]

N_CLUSTERS = 3  # fixed and public for the clustering task family -- see build_round


@dataclass
class Round:
    task_type: str
    train_X: np.ndarray
    train_y: np.ndarray | None  # None for clustering (unsupervised)
    test_X: np.ndarray
    test_y: np.ndarray  # ground truth for scoring; never sent to the player


def _n_features(rng: np.random.Generator) -> int:
    return int(rng.integers(3, 12))


def task_type_for_round(round_seed: int) -> str:
    """The round's task family is a pure function of the platform's per-round SEED."""
    return TASK_TYPES[round_seed % len(TASK_TYPES)]


def instance_seed(round_seed: int, instance_index: int) -> int:
    """Derive one of N independent instance seeds for a round -- see referee.py: a single
    dataset draw per round is exactly the under-sized-evaluation mistake this repo's own
    evaluation-design guidance warns about, so each round averages raw_score over
    `n_instances` independent draws of the SAME task family instead of just one."""
    return (round_seed * 1_000_003 + instance_index) % (2**32 - 1)


def build_round(seed: int, n_train: int, n_test: int, task_type: str | None = None) -> Round:
    """The ONE source of truth for what one instance's data looks like. Deterministic in `seed`.

    `task_type` is normally left to be derived from `seed` (one round == one task family), but
    can be pinned explicitly so multiple instances of the same round share a task family while
    drawing independent data (see instance_seed above).
    """
    task_type = task_type or task_type_for_round(seed)
    rng = np.random.default_rng(seed)
    n_total = n_train + n_test
    n_features = _n_features(rng)

    if task_type == "regression":
        n_informative = max(1, n_features // 2)
        X, y = make_regression(
            n_samples=n_total,
            n_features=n_features,
            n_informative=n_informative,
            noise=1.0,
            random_state=seed,
        )
    elif task_type == "classification":
        n_informative = max(2, n_features // 2)
        X, y = make_classification(
            n_samples=n_total,
            n_features=n_features,
            n_informative=n_informative,
            n_redundant=0,
            n_classes=2,
            n_clusters_per_class=1,
            random_state=seed,
        )
    elif task_type == "timeseries":
        # A short multi-feature series with a lagged-linear target; framed as tabular
        # regression over a sliding window (features = window, target = next value).
        base = rng.normal(size=(n_total + n_features, n_features)).cumsum(axis=0)
        weights = rng.normal(size=n_features)
        series = base @ weights + rng.normal(scale=0.5, size=n_total + n_features)
        X = np.stack([series[i : i + n_features] for i in range(n_total)])
        y = series[n_features : n_features + n_total]
    elif task_type == "clustering":
        # n_clusters is FIXED (not randomized) and public, exactly like n_classes=2 is fixed
        # for classification -- "how many groups to find" is a problem specification, not
        # ground truth. Randomizing it while only the reference model knew the true count
        # (via test_y) was an apples-to-oranges comparison that the sizing check caught: it
        # was the dominant source of cross-round score variance, not real task difficulty.
        X, y = make_blobs(n_samples=n_total, n_features=n_features, centers=N_CLUSTERS, random_state=seed)
    else:  # pragma: no cover - exhaustive TASK_TYPES
        raise ValueError(f"unknown task_type {task_type}")

    train_X, test_X = X[:n_train], X[n_train : n_train + n_test]
    if task_type == "clustering":
        train_y, test_y = None, y[n_train : n_train + n_test]
    else:
        train_y, test_y = y[:n_train], y[n_train : n_train + n_test]

    return Round(task_type=task_type, train_X=train_X, train_y=train_y, test_X=test_X, test_y=test_y)


def reference_prediction(round_: Round) -> Any:
    """A deliberately simple, fast, always-available baseline model per task type.

    Used only to compute `reference_loss` for score normalization -- never shown to miners.
    """
    if round_.task_type in ("regression", "timeseries"):
        model = LinearRegression().fit(round_.train_X, round_.train_y)
        return model.predict(round_.test_X)
    if round_.task_type == "classification":
        model = LogisticRegression(max_iter=1000).fit(round_.train_X, round_.train_y)
        return model.predict_proba(round_.test_X)[:, 1]
    if round_.task_type == "clustering":
        # N_CLUSTERS is fixed and public (see build_round) -- using anything derived from
        # round_.test_y here would leak ground truth into the "reference" the submission is
        # scored against, silently privileging it over an honest submission.
        model = KMeans(n_clusters=N_CLUSTERS, n_init=4, random_state=0).fit(round_.train_X)
        return model.predict(round_.test_X)
    raise ValueError(f"unknown task_type {round_.task_type}")  # pragma: no cover


def loss(task_type: str, y_true: np.ndarray, y_pred: Any) -> float:
    """Lower-is-better loss, comparable in scale across task types. See module docstring."""
    y_pred = np.asarray(y_pred, dtype=float)
    if task_type in ("regression", "timeseries"):
        return float(mean_squared_error(y_true, y_pred))
    if task_type == "classification":
        y_pred = np.clip(y_pred, 1e-6, 1 - 1e-6)
        return float(log_loss(y_true, y_pred, labels=[0, 1]))
    if task_type == "clustering":
        # Adjusted Rand Index: label-invariant agreement between predicted and true cluster
        # assignments (permutation of cluster ids doesn't matter, unlike raw label equality).
        # ARI in [-1,1], 1 == perfect match, ~0 == random labeling -> loss in [0,2].
        ari = adjusted_rand_score(y_true, y_pred.astype(int))
        return float(1.0 - ari)
    raise ValueError(f"unknown task_type {task_type}")  # pragma: no cover
