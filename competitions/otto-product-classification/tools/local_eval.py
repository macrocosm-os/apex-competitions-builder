"""Run the full player+referee loop locally against a submission CSV — no Docker.

Starts player/launch.py as a subprocess serving the CSV, then drives it with the real
OttoReferee over HTTP, exactly like a platform evaluation (minus the sandboxing — test that
separately with the built images).

    python tools/local_eval.py --submission baseline/submission.csv

The one asymmetry vs the sandbox: there is no /private mount locally, so we point
env.labels.TEST_LABELS_PATH at a local file. Digest verification is applied whenever
env/labels.py has a real pin (i.e. not the initial placeholder), so once the competition is
wired up a stale local labels file fails here too.

Also importable: measure_precision.py reuses evaluate_once().
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

COMP_DIR = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(COMP_DIR), str(COMP_DIR / "referee")]

from apex_sdk.gym_v1.client import PlayerClient  # noqa: E402
from apex_sdk.gym_v1.referee import GameResult, RefereeContext  # noqa: E402

DEFAULT_LABELS = COMP_DIR / "private" / "test_labels.csv"


def evaluate_once(
    submission_path: str | Path,
    labels_path: str | Path = DEFAULT_LABELS,
    batch_size: int = 4096,
    deadline_ms: int = 5000,
    seed: int = 0,
    port: int = 8323,
) -> GameResult:
    labels_path = Path(labels_path)
    if not labels_path.is_file():
        raise SystemExit(f"✗ labels not found: {labels_path}\n  run `python tools/prepare_data.py` first.")

    # The referee runs in THIS process, so it reads the label path from our environment.
    os.environ["TEST_LABELS_PATH"] = str(labels_path)
    import env.labels as labels_mod  # imported after the env var is set

    labels_mod.TEST_LABELS_PATH = str(labels_path)
    if set(labels_mod.TEST_LABELS_SHA256) == {"0"}:
        # Placeholder pin: the competition is not wired up yet, so verification would always
        # fail. Skip it here and say so, rather than silently accepting any labels file.
        labels_mod.EXPECTED_TEST_ROWS = 0
        _patch_verify_off(labels_mod)
        print("⚠ env/labels.py has a placeholder sha256 — skipping digest verification.")

    from referee import OttoReferee  # noqa: PLC0415  (needs sys.path set above)

    server = subprocess.Popen(
        [sys.executable, str(COMP_DIR / "player" / "launch.py"), "--port", str(port)],
        env=os.environ
        | {
            "SUBMISSION_PATH": str(submission_path),
            # In the sandbox the player runs as /app/launch.py with /app on sys.path, so
            # `import env` resolves for free. Locally the script's dir is player/, so the
            # competition root has to be put on the path explicitly.
            "PYTHONPATH": os.pathsep.join(filter(None, [str(COMP_DIR), os.environ.get("PYTHONPATH", "")])),
        },
    )
    try:
        client = PlayerClient(f"http://127.0.0.1:{port}")
        _wait_or_die(client, server)
        ctx = RefereeContext(
            match_id=f"local-{seed}",
            seed=seed,
            config={"batch_size": batch_size, "deadline_ms": deadline_ms},
            player_urls=[client.base_url],
            num_players=1,
        )
        return OttoReferee().play_game(ctx, [client])
    finally:
        server.terminate()
        server.wait()


def _wait_or_die(client: PlayerClient, server: subprocess.Popen, timeout_s: float = 30.0) -> None:
    """Wait for readiness, but fail fast if the player process has already exited.

    PlayerClient.wait_until_ready only polls HTTP, so a player that dies on startup (the
    normal outcome for a rejected submission) costs the full timeout before reporting a
    misleading "not ready" error. On the platform that distinction does not matter — both are
    a submission failure — but locally it is the difference between a 1-second and a
    30-second edit/run loop.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if client.health():
            return
        rc = server.poll()
        if rc is not None:
            raise SystemExit(f"✗ player exited with code {rc} before becoming ready (see its stderr above).")
        time.sleep(0.1)
    raise SystemExit(f"✗ player not ready within {timeout_s}s")


def _patch_verify_off(labels_mod) -> None:
    """Default load_test_labels(verify=...) to False for local runs with an unpinned digest."""
    original = labels_mod.load_test_labels

    def unverified(path=None, verify=False):  # noqa: ARG001
        return original(path, verify=False)

    labels_mod.load_test_labels = unverified


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submission", required=True, help="path to a submission CSV")
    ap.add_argument("--labels", default=str(DEFAULT_LABELS), help="path to the private test labels")
    ap.add_argument("--batch-size", type=int, default=4096)
    ap.add_argument("--deadline-ms", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=0, help="recorded in metadata; drives nothing")
    args = ap.parse_args()
    result = evaluate_once(args.submission, args.labels, args.batch_size, args.deadline_ms, args.seed)
    print(json.dumps(result.__dict__, indent=2))
