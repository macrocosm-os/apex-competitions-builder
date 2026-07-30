"""algo_speedrun gym_v1 PLAYER server (the image's `entrypoints.evaluate.command`).

Unlike a typical competition's player, this one never executes the miner's code: it
only holds the screened `submission.py` the platform wrote to SUBMISSION_PATH and
returns its raw text to the referee over a single `/act` call. All training happens in
the referee (see referee/referee.py's module docstring for why). This keeps the player
sandbox exactly as tiny/inert as every other competition's -- 1 CPU, no GPU, no torch,
no nanochat -- even though the thing it's carrying is training-loop code.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from apex_sdk.gym_v1 import Player, serve

SUBMISSION_PATH = os.environ.get("SUBMISSION_PATH", "/app/submission.py")


class SubmissionCarrierPlayer(Player):
    def __init__(self, path: str = SUBMISSION_PATH) -> None:
        self.path = Path(path)

    def is_ready(self) -> bool:
        return self.path.is_file()

    def reset(self, match_id: str, player_index: int, seed: int, config: dict[str, Any]) -> None:
        pass  # nothing to reset -- the submission is static content, not a running strategy

    def act(self, observation: Any, deadline_ms: int) -> Any:
        if not isinstance(observation, dict) or observation.get("op") != "fetch_submission":
            raise ValueError(f"unrecognized observation: {observation!r}")
        return {"content": self.path.read_text()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--submission", default=SUBMISSION_PATH)
    args = parser.parse_args()
    serve(SubmissionCarrierPlayer(args.submission), port=args.port)


if __name__ == "__main__":
    main()
