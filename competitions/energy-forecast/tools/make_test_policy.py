"""Build a random-weight linear forecaster as ONNX — for smoke-testing the eval
loop only (it will score badly, near or below 0.0). No sklearn/torch required.

    python tools/make_test_policy.py --out test_policy.onnx --seed 0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from env.features import HISTORY_HOURS, HORIZON_HOURS, NUM_FEATURES  # noqa: E402

OBS_DIM = HISTORY_HOURS * NUM_FEATURES
ACT_DIM = HORIZON_HOURS


def make_policy(path: str, seed: int) -> None:
    rng = np.random.default_rng(seed)
    w = rng.normal(0, 0.05, (OBS_DIM, ACT_DIM)).astype(np.float32)
    b = np.zeros(ACT_DIM, dtype=np.float32)

    nodes = [
        helper.make_node("MatMul", ["obs", "w"], ["h"]),
        helper.make_node("Add", ["h", "b"], ["forecast"]),
    ]
    graph = helper.make_graph(
        nodes,
        "test_policy",
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
    print(f"wrote {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="test_policy.onnx")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    make_policy(args.out, args.seed)
