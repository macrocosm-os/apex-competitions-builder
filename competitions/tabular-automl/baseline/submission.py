"""Baseline submission for tabular_automl: one linear/simple model per task family.

This is what seeds the leaderboard (`defaults.baseline_raw_score` == 1.0, since it's
literally the referee's own reference model) and is the integration test for the full
loop. A real miner should beat this by finding a better-fitting or more compact model
per task type -- see README.md for the contract `fit` / `predict` / `complexity` must
satisfy.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression, LogisticRegression


def fit(train_X: list[list[float]], train_y: list | None, task_type: str, n_clusters: int | None = None) -> Any:
    X = np.asarray(train_X)
    if task_type in ("regression", "timeseries"):
        return ("regression", LinearRegression().fit(X, np.asarray(train_y)))
    if task_type == "classification":
        return ("classification", LogisticRegression(max_iter=1000).fit(X, np.asarray(train_y)))
    if task_type == "clustering":
        # n_clusters is a public problem-specification knob (see README.md), not something to
        # guess -- exactly like n_classes=2 isn't guessed for the classification family.
        return ("clustering", KMeans(n_clusters=n_clusters, n_init=4, random_state=0).fit(X))
    raise ValueError(f"unknown task_type {task_type}")


def predict(model: Any, test_X: list[list[float]]) -> list:
    kind, estimator = model
    X = np.asarray(test_X)
    if kind == "classification":
        return estimator.predict_proba(X)[:, 1].tolist()
    return estimator.predict(X).tolist()


def complexity(model: Any) -> int:
    _, estimator = model
    if hasattr(estimator, "coef_"):
        return int(np.asarray(estimator.coef_).size + np.asarray(estimator.intercept_).size)
    if hasattr(estimator, "cluster_centers_"):
        return int(estimator.cluster_centers_.size)
    return 1
