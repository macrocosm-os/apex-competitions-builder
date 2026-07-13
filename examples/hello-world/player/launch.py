"""hello_world gym_v1 PLAYER server (the image's `entrypoints.evaluate.command`).

A solo eval is a 1-player duel: the miner submission runs here, isolated behind the gym_v1
HTTP API, and the referee sandbox drives + scores it. The submission never shares a sandbox
with the scorer.

Contract:
  - The platform writes the miner submission to target_path (/app/submission.py).
  - This server exposes /health, /reset, /act (via the SDK). The referee calls /act once per
    task with the numbers to sort as the observation; the action is the sorted list.
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


class HelloPlayer(Player):
    def __init__(self) -> None:
        # Loading here (at startup) means a broken submission fails readiness -> the referee
        # forfeits it, exactly like a screening failure.
        self._submission = _load_submission()

    def reset(self, match_id: str, player_index: int, seed: int, config: dict[str, Any]) -> None:
        pass  # stateless competition

    def act(self, observation: Any, deadline_ms: int) -> Any:  # noqa: ARG002
        # observation is the list of numbers to sort; the action is the sorted list.
        return self._submission.sort_numbers(list(observation))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    serve(HelloPlayer(), port=args.port, readiness_path="/health")
