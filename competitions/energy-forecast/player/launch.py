"""energy_forecast gym_v1 PLAYER server (the image's `entrypoints.evaluate.command`).

The platform writes the miner's ONNX forecaster to /app/submission.onnx; this
server loads it, validates the interface, and serves /health /reset /act.
No miner code runs in this sandbox -- the artifact is a pure ONNX graph, so
validation is structural, not screening.

Contract the submission must satisfy (also in the miner README):
    - exactly one input:  float32, shape [1, 1008] (168 hours x 6 features,
      flattened row-major -- see env/features.py::build_observation)
    - exactly one output: float32, shape [1, 24] (next 24 hourly demand
      values, in the SAME normalized units as the input -- see
      env/features.py::denormalize, which the referee applies)
"""

from __future__ import annotations

import argparse
import os
from typing import Any

import numpy as np
import onnxruntime as ort

from apex_sdk.gym_v1 import Player, serve

SUBMISSION_PATH = os.environ.get("SUBMISSION_PATH", "/app/submission.onnx")
HISTORY_HOURS = 168
NUM_FEATURES = 6
OBS_DIM = HISTORY_HOURS * NUM_FEATURES
ACT_DIM = 24


def _check_dims(shape: list, want_last: int, what: str) -> None:
    if len(shape) != 2 or shape[-1] != want_last:
        raise ValueError(f"{what} must have shape [batch, {want_last}], got {shape}")


def _load_session() -> ort.InferenceSession:
    opts = ort.SessionOptions()
    # Single-threaded for determinism: same model + same window must produce
    # the same forecast on every evaluation.
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    session = ort.InferenceSession(SUBMISSION_PATH, sess_options=opts, providers=["CPUExecutionProvider"])
    inputs, outputs = session.get_inputs(), session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError(f"model must have exactly 1 input and 1 output, got {len(inputs)}/{len(outputs)}")
    if inputs[0].type != "tensor(float)":
        raise ValueError(f"input must be float32, got {inputs[0].type}")
    _check_dims(inputs[0].shape, OBS_DIM, "input")
    _check_dims(outputs[0].shape, ACT_DIM, "output")
    return session


class ForecastPlayer(Player):
    def __init__(self) -> None:
        # Load + validate at startup: a non-conforming artifact never becomes
        # ready, so the referee sees a typed submission failure.
        self._session = _load_session()
        self._input_name = self._session.get_inputs()[0].name

    def reset(self, match_id: str, player_index: int, seed: int, config: dict[str, Any]) -> None:
        pass  # the model is a stateless feed-forward graph, no per-instance state

    def act(self, observation: Any, deadline_ms: int) -> Any:  # noqa: ARG002
        obs = np.asarray(observation, dtype=np.float32).reshape(1, OBS_DIM)
        (forecast,) = self._session.run(None, {self._input_name: obs})
        return np.asarray(forecast, dtype=np.float64).ravel().tolist()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    serve(ForecastPlayer(), port=args.port, readiness_path="/health")
