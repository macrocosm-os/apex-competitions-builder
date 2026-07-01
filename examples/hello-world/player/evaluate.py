"""hello_world solo eval entrypoint (the image's `entrypoints.evaluate.command`).

Contract (SoloRunner):
  - The platform has written the miner's submission to target_path (/app/submission.py).
  - The round input (validated against input.schema.json) is available at /data/input.json.
  - This script must write /data/result.json with:
        {"raw_score": float, "eval_time_in_seconds": float, "metadata": {...}}

The score is the fraction of tasks the submission sorts correctly.
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

SUBMISSION_PATH = Path("/app/submission.py")
INPUT_PATH = Path("/data/input.json")
RESULT_PATH = Path("/data/result.json")


def _load_submission():
    spec = importlib.util.spec_from_file_location("submission", SUBMISSION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> None:
    start = time.monotonic()
    submission = _load_submission()
    tasks = json.loads(INPUT_PATH.read_text())["tasks"]

    correct = 0
    for task in tasks:
        expected = sorted(task["numbers"])
        try:
            got = submission.sort_numbers(list(task["numbers"]))
        except Exception:
            got = None
        if got == expected:
            correct += 1

    raw_score = correct / len(tasks)
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(
            {
                "raw_score": raw_score,
                "eval_time_in_seconds": time.monotonic() - start,
                "metadata": {"tasks": len(tasks), "correct": correct},
            }
        )
    )


if __name__ == "__main__":
    main()
