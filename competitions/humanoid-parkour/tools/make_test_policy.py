"""Build a random-weight MLP policy as ONNX — for smoke-testing the eval loop
only (it will stumble and fall, scoring near zero). No torch required.

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
from env.sim import ACT_DIM, CTRL_RANGE, OBS_DIM  # noqa: E402

HIDDEN = 64


def make_policy(path: str, seed: int) -> None:
    rng = np.random.default_rng(seed)
    w1 = rng.normal(0, 0.2, (OBS_DIM, HIDDEN)).astype(np.float32)
    b1 = np.zeros(HIDDEN, dtype=np.float32)
    w2 = rng.normal(0, 0.2, (HIDDEN, ACT_DIM)).astype(np.float32)
    b2 = np.zeros(ACT_DIM, dtype=np.float32)

    nodes = [
        helper.make_node("MatMul", ["obs", "w1"], ["h1"]),
        helper.make_node("Add", ["h1", "b1"], ["h1b"]),
        helper.make_node("Tanh", ["h1b"], ["h1a"]),
        helper.make_node("MatMul", ["h1a", "w2"], ["h2"]),
        helper.make_node("Add", ["h2", "b2"], ["h2b"]),
        helper.make_node("Tanh", ["h2b"], ["squashed"]),
        helper.make_node("Mul", ["squashed", "ctrl_range"], ["action"]),
    ]
    graph = helper.make_graph(
        nodes,
        "test_policy",
        inputs=[helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, OBS_DIM])],
        outputs=[helper.make_tensor_value_info("action", TensorProto.FLOAT, [1, ACT_DIM])],
        initializer=[
            helper.make_tensor("w1", TensorProto.FLOAT, w1.shape, w1.ravel()),
            helper.make_tensor("b1", TensorProto.FLOAT, b1.shape, b1),
            helper.make_tensor("w2", TensorProto.FLOAT, w2.shape, w2.ravel()),
            helper.make_tensor("b2", TensorProto.FLOAT, b2.shape, b2),
            helper.make_tensor("ctrl_range", TensorProto.FLOAT, [1], [CTRL_RANGE]),
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
