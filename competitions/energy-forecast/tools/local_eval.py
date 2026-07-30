"""Run the full player+referee loop locally against an ONNX forecaster — no Docker.

Starts player/launch.py as a subprocess serving the model, then drives it
with the real ForecastReferee over HTTP, exactly like a platform evaluation
(minus the sandboxing — test that separately with the built images).

    python tools/local_eval.py --onnx my_model.onnx --seed 42 --mode backtest

Also importable: measure_variance.py and simulate_two_phase.py reuse evaluate_once().
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
from referee import ForecastReferee  # noqa: E402


def evaluate_once(
    onnx_path: str,
    master_seed: int,
    num_instances: int = 60,
    deadline_ms: int = 2000,
    mode: str = "backtest",
    holdout_hours: int = 0,
    port: int = 8322,
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
                "num_instances": num_instances,
                "deadline_ms": deadline_ms,
                "mode": mode,
                "holdout_hours": holdout_hours,
            },
            player_urls=[client.base_url],
            num_players=1,
        )
        return ForecastReferee().play_game(ctx, [client])
    finally:
        server.terminate()
        server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--num-instances", type=int, default=60)
    parser.add_argument("--deadline-ms", type=int, default=2000)
    parser.add_argument("--mode", choices=["backtest", "live"], default="backtest")
    parser.add_argument("--holdout-hours", type=int, default=0)
    args = parser.parse_args()
    result = evaluate_once(args.onnx, args.seed, args.num_instances, args.deadline_ms, args.mode, args.holdout_hours)
    print(json.dumps(result.__dict__, indent=2))
