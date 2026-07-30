"""research_harness gym_v1 PLAYER server (the image's `entrypoints.evaluate.command`).

The platform writes the miner's harness to /app/submission.py; this server imports it,
checks the contract, and serves /health /reset /act. There is nothing else in this
sandbox — no corpus, no model weights, no scoring logic, no seed. The harness's only
capabilities are the actions it returns, which the referee interprets.

The submission must define a class named `Harness`:

    class Harness:
        def start_question(self, config: dict) -> None:
            '''Called once per question. `config` carries the question text, the world's
            provenance rules, the remaining shared token pool, and the step/context caps.'''

        def act(self, observation: dict) -> dict:
            '''Called once per step. Return ONE action:
                 {"tool": "search", "query": str, "k": int}
                 {"tool": "add"|"drop", "doc_ids": [str]}
                 {"tool": "ask", "instruction": str, "system": str?, "max_output_tokens": int?}
                 {"tool": "answer", "text": str, "citations": [str]}   # "UNKNOWN" abstains
            '''

The instance is created ONCE per episode and reused across every question, so a harness
can carry state — which is deliberate: the shared token pool makes allocating effort
across questions part of the job, and that needs memory.

A submission that cannot be imported, lacks `Harness`, or lacks either method fails
readiness — a typed failure attributed to the submission, exactly like a screening
rejection.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import traceback
from typing import Any

from apex_sdk.gym_v1 import Player, serve

# Overridable so miners (and tools/local_eval.py) can serve a local file; in the sandbox
# the platform always writes to the spec's target_path.
SUBMISSION_PATH = os.environ.get("SUBMISSION_PATH", "/app/submission.py")

REQUIRED_METHODS = ("start_question", "act")


def _load_harness(path: str) -> Any:
    spec = importlib.util.spec_from_file_location("submission", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load a Python module from {path}")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so a submission that imports itself (or uses dataclasses,
    # which look the module up by name) does not fail on an absent sys.modules entry.
    sys.modules["submission"] = module
    spec.loader.exec_module(module)

    cls = getattr(module, "Harness", None)
    if cls is None:
        raise ValueError("submission.py must define a class named `Harness`")
    missing = [m for m in REQUIRED_METHODS if not callable(getattr(cls, m, None))]
    if missing:
        raise ValueError(f"`Harness` is missing required method(s): {', '.join(missing)}")
    return cls()


class HarnessPlayer(Player):
    def __init__(self, path: str = SUBMISSION_PATH) -> None:
        # Import at startup so a broken submission fails readiness instead of failing
        # mid-round and being mistaken for a bad strategy.
        self.harness: Any | None = None
        self.load_error: str | None = None
        try:
            self.harness = _load_harness(path)
        except Exception:
            self.load_error = traceback.format_exc(limit=6)
            print(f"submission failed to load:\n{self.load_error}", file=sys.stderr)

    def is_ready(self) -> bool:
        return self.harness is not None

    def reset(self, match_id: str, player_index: int, seed: int, config: dict[str, Any]) -> None:
        if self.harness is None:
            raise RuntimeError(f"submission never loaded: {self.load_error}")
        self.harness.start_question(config)

    def act(self, observation: Any, deadline_ms: int) -> Any:
        if self.harness is None:
            raise RuntimeError(f"submission never loaded: {self.load_error}")
        return self.harness.act(observation)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--submission", default=SUBMISSION_PATH)
    args = parser.parse_args()
    serve(HarnessPlayer(args.submission), port=args.port)


if __name__ == "__main__":
    main()
