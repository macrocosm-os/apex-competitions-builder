"""tabular_automl gym_v1 PLAYER server (the image's `entrypoints.evaluate.command`).

Contract for the miner's `submission.py` (target_path = /app/submission.py), all three
required:

    fit(train_X: list[list[float]], train_y: list | None, task_type: str, n_clusters: int | None) -> Any
        Train and return a model object. Runs inside reset() -- the referee times this
        call against `max_train_time_s` and forfeits on timeout (hard gate, not scored).
        `n_clusters` is only meaningful (non-None) when task_type == "clustering": it is a
        public problem-specification constant, not ground truth -- like n_classes=2 for the
        classification family, "how many groups to find" is given, not inferred.

    predict(model: Any, test_X: list[list[float]]) -> list
        Return one prediction per row of test_X. Runs inside act().

    complexity(model: Any) -> int
        A self-reported complexity number (e.g. total learned parameter count, or node
        count for a symbolic expression). Checked against `max_complexity` (hard gate).
        Lying here only hurts the miner: this is a declared limit, not a scored term --
        misreporting doesn't change raw_score, it only risks a gate failure if honest
        reporting would have passed and a false one is caught by spot review.

The model object never leaves this process: it is trained fresh every /reset (i.e. every
time this submission is evaluated against a round's SEED) and lives only in memory for
that one match. Nothing is serialized to disk, so there is no pickle/deserialization
attack surface at all -- Layer-1 AST screening additionally forbids importing
pickle/dill/marshal/shelve outright (see spec.yaml `screening`).
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from typing import Any

from apex_sdk.gym_v1 import Player, serve

SUBMISSION_PATH = Path("/app/submission.py")


def _load_submission():
    spec = importlib.util.spec_from_file_location("submission", SUBMISSION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TabularAutoMLPlayer(Player):
    def __init__(self) -> None:
        # Loading here (at startup) means a broken submission fails readiness -> the referee
        # forfeits it, exactly like a screening failure.
        self._submission = _load_submission()
        self._model: Any = None

    def reset(self, match_id: str, player_index: int, seed: int, config: dict[str, Any]) -> None:
        self._model = self._submission.fit(
            config["train_X"],
            config["train_y"],
            config["task_type"],
            config.get("n_clusters"),
        )

    def act(self, observation: Any, deadline_ms: int) -> Any:  # noqa: ARG002
        predictions = self._submission.predict(self._model, observation)
        complexity = self._submission.complexity(self._model)
        return {"predictions": list(predictions), "complexity": int(complexity)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    serve(TabularAutoMLPlayer(), port=args.port, readiness_path="/health")
