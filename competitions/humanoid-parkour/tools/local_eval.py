"""Run the full player+referee loop locally against an ONNX policy — no Docker.

Starts player/launch.py as a subprocess serving the policy, then drives it
with the real ParkourReferee over HTTP, exactly like a platform evaluation
(minus the sandboxing — test that separately with the built images).

    python tools/local_eval.py --onnx my_policy.onnx --seed 42

Also importable: measure_variance.py reuses evaluate_once().
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

COMP_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(COMP_DIR), str(COMP_DIR / "referee")]

from apex_sdk.gym_v1.client import PlayerClient  # noqa: E402
from apex_sdk.gym_v1.referee import GameResult, RefereeContext  # noqa: E402
from referee import ParkourReferee  # noqa: E402


def evaluate_once(
    onnx_path: str,
    master_seed: int,
    courses_per_difficulty: int = 8,
    max_steps: int = 1200,
    deadline_ms: int = 500,
    port: int = 8321,
) -> GameResult:
    server = subprocess.Popen(
        [sys.executable, str(COMP_DIR / "player" / "launch.py"), "--port", str(port)],
        env=os.environ | {"SUBMISSION_PATH": str(onnx_path)},
    )
    try:
        client = PlayerClient(f"http://127.0.0.1:{port}")
        client.wait_until_ready(timeout_s=30)
        ctx = RefereeContext(
            match_id=f"local-{master_seed}",
            seed=master_seed,
            config={
                "courses_per_difficulty": courses_per_difficulty,
                "max_steps_per_episode": max_steps,
                "deadline_ms": deadline_ms,
            },
            player_urls=[client.base_url],
            num_players=1,
        )
        return ParkourReferee().play_game(ctx, [client])
    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--courses-per-difficulty", type=int, default=8)
    parser.add_argument("--max-steps", type=int, default=1200)
    parser.add_argument("--deadline-ms", type=int, default=500)
    args = parser.parse_args()
    result = evaluate_once(args.onnx, args.seed, args.courses_per_difficulty, args.max_steps, args.deadline_ms)
    print(json.dumps(result.__dict__, indent=2))
