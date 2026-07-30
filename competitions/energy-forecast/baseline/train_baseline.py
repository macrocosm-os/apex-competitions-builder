"""Train the reference baseline and export it to the competition's ONNX contract.

This is both the official baseline (seeds the leaderboard; must beat the
seasonal-naive score of 0.0 end to end) and a starting recipe miners can beat.
Any training algorithm works — only the exported ONNX forecaster is submitted.
A closed-form ridge regression is enough to meaningfully beat seasonal-naive
(it can learn the average week-over-week drift the naive baseline ignores)
without adding a torch dependency to this reference recipe.

    python baseline/train_baseline.py --seed 0 --num-train-instances 4000 --out baseline.onnx

Verify with:  python tools/local_eval.py --onnx baseline.onnx --seed 0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env.data import sample_instances  # noqa: E402
from env.features import HISTORY_HOURS, HORIZON_HOURS, NUM_FEATURES, build_observation  # noqa: E402

OBS_DIM = HISTORY_HOURS * NUM_FEATURES
ACT_DIM = HORIZON_HOURS


def _training_arrays(seed: int, num_instances: int) -> tuple[np.ndarray, np.ndarray]:
    """Backtest instances only — target is known, used for fitting/dev, never live scoring."""
    instances = sample_instances(seed, num_instances, mode="backtest")
    X = np.stack([build_observation(inst.history, inst.history_timestamps) for inst in instances])
    scales = np.array([max(np.mean(inst.history), 1.0) for inst in instances])
    Y = np.stack([np.asarray(inst.target) for inst in instances]) / scales[:, None]
    return X.astype(np.float64), Y.astype(np.float64)


def fit_ridge(X: np.ndarray, Y: np.ndarray, alpha: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Closed-form ridge regression: W, b such that pred = X @ W + b."""
    X_aug = np.hstack([X, np.ones((X.shape[0], 1))])
    reg = alpha * np.eye(X_aug.shape[1])
    reg[-1, -1] = 0.0  # don't penalize the bias term
    coef = np.linalg.solve(X_aug.T @ X_aug + reg, X_aug.T @ Y)
    return coef[:-1].astype(np.float32), coef[-1].astype(np.float32)


def export_onnx(w: np.ndarray, b: np.ndarray, path: str) -> None:
    nodes = [
        helper.make_node("MatMul", ["obs", "w"], ["h"]),
        helper.make_node("Add", ["h", "b"], ["forecast"]),
    ]
    graph = helper.make_graph(
        nodes,
        "energy_forecast_baseline",
        inputs=[helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, OBS_DIM])],
        outputs=[helper.make_tensor_value_info("forecast", TensorProto.FLOAT, [1, ACT_DIM])],
        initializer=[
            helper.make_tensor("w", TensorProto.FLOAT, w.shape, w.ravel()),
            helper.make_tensor("b", TensorProto.FLOAT, b.shape, b),
        ],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    onnx.checker.check_model(model)
    onnx.save(model, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--num-train-instances", type=int, default=4000)
    parser.add_argument("--alpha", type=float, default=10.0)
    parser.add_argument("--out", default="baseline.onnx")
    args = parser.parse_args()

    X, Y = _training_arrays(args.seed, args.num_train_instances)
    w, b = fit_ridge(X, Y, alpha=args.alpha)
    export_onnx(w, b, args.out)
    print(f"exported {args.out} (obs [1,{OBS_DIM}] -> forecast [1,{ACT_DIM}], trained on {len(X)} instances)")


if __name__ == "__main__":
    main()
