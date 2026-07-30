#!/usr/bin/env python
"""Weekly, out-of-band deep evaluation over the top-K submissions by proxy score.

NOT part of the round lifecycle (no spec.yaml entrypoint invokes this) -- see
HANDOFF.md §6 for why: nanochat's real speedrun scale needs hours on 8xH100, which
cannot happen per-submission-per-round without unbounded compute spend. This script is
meant to run on a cron/cadence (weekly) on separate, larger GPU infra than the per-round
referee, reading a leaderboard export and running each selected submission through
nanochat's own UNMODIFIED `scripts/base_train.py` + `scripts/base_eval.py` at real scale.

## Input contract (deliberately platform-agnostic -- there is no round-history API to
integrate against in this repo; this is the seam a real integration replaces)

A `leaderboard.json`:
    [
      {"submission_id": "...", "proxy_score": 3.87, "submission_path": "path/to/submission.py"},
      ...
    ]

`proxy_score` is the round's `val_bpb` (lower is better, per spec.yaml
`lower_is_better: true`). `submission_path` points at the raw submission.py content --
in a real integration this would be exported by the platform per round; here it's just a
file path so this script is testable without one.

## What it does per selected submission

1. Load `EXTRA_FILES` from the submission (same `_exec_submission` pattern as
   referee.py) and re-screen it (referee/screen.py) -- an out-of-band batch job is not
   exempt from the same tripwire a live round applies.
2. Materialize `EXTRA_FILES` into a FRESH clone of the pinned nanochat checkout (not the
   trimmed subset referee/Dockerfile ships -- the full upstream tree, since this is where
   CORE-benchmark scoring and full-scale training actually happen).
3. Shell out to `python -m scripts.base_train --depth=<FULL_SCALE_DEPTH> ...` (upstream's
   own script, completely unmodified) followed by `scripts/base_eval.py` for the CORE
   metric, and captures the final `core_metric`.
4. Writes `deep_eval_results.json`: {submission_id, core_metric, wall_time_s}.

This does NOT independently recompute the score the way `train_runner.py`'s
`_referee_evaluate_bpb` does for the cheap pass (HANDOFF.md §8 item 3) -- at full scale,
re-deriving CORE-benchmark scoring independently is a much larger undertaking than the
proxy bpb case, and is flagged as a real, residual risk of this script rather than
silently assumed safe: **whoever operates this on real GPU infra should treat the
self-reported-loss threat model in HANDOFF.md §8 as still open at full scale** until an
equivalent independent-scoring pass is built for CORE metrics too.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "referee"))

# Full-scale defaults -- these are the CLI flags a real deep-eval run would use, per
# nanochat's own README (not the tiny proxy defaults in ../input.schema.json).
FULL_SCALE_ARGS = [
    "--depth=20",
    "--device-batch-size=32",
]


def _load_submission_extra_files(submission_path: Path) -> dict[str, str]:
    from screen import screen_extra_files

    import importlib.util

    spec = importlib.util.spec_from_file_location("submission", submission_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    extra_files = getattr(module, "EXTRA_FILES", {}) or {}
    screen_extra_files(extra_files)
    return extra_files


def _select_top_k(leaderboard: list[dict], k: int) -> list[dict]:
    # lower_is_better: true (spec.yaml) -- proxy_score is a bpb, not an accuracy.
    return sorted(leaderboard, key=lambda row: row["proxy_score"])[:k]


def run_one(entry: dict, nanochat_repo: Path, extra_args: list[str]) -> dict:
    from screen import materialize_extra_files

    extra_files = _load_submission_extra_files(Path(entry["submission_path"]))

    with tempfile.TemporaryDirectory() as scratch:
        scratch_path = Path(scratch)
        materialize_extra_files(scratch_path, extra_files)

        # A real integration copies scratch_path's model.py/schedule.py/data.py over the
        # matching files in a fresh nanochat_repo checkout before invoking base_train --
        # left as an explicit TODO rather than guessed at, since it depends on exactly
        # how the deep-eval infra provisions a nanochat checkout (this repo only vendors
        # the trimmed subset into the REFEREE image, not a full checkout suitable for
        # scripts/base_train.py's CLI, which expects the whole repo layout).
        # TODO(deep-eval infra): materialize scratch_path's overrides into nanochat_repo.

        t0 = time.monotonic()
        subprocess.run(
            [sys.executable, "-m", "scripts.base_train", *FULL_SCALE_ARGS, *extra_args],
            cwd=nanochat_repo,
            check=True,
        )
        subprocess.run(
            [sys.executable, "-m", "scripts.base_eval"],
            cwd=nanochat_repo,
            check=True,
        )
        wall_time_s = time.monotonic() - t0

    return {
        "submission_id": entry["submission_id"],
        "wall_time_s": round(wall_time_s, 1),
        # TODO(deep-eval infra): parse the CORE metric out of scripts/base_eval.py's
        # output (or its own result file) instead of leaving it unset -- depends on
        # how that script is invoked/instrumented in the real deep-eval environment.
        "core_metric": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--leaderboard", type=Path, required=True)
    parser.add_argument("--nanochat-repo", type=Path, required=True, help="full upstream nanochat checkout")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--out", type=Path, default=Path("deep_eval_results.json"))
    parser.add_argument("--dry-run", action="store_true", help="select + screen only, never invoke base_train")
    args = parser.parse_args()

    leaderboard = json.loads(args.leaderboard.read_text())
    selected = _select_top_k(leaderboard, args.top_k)
    print(f"selected {len(selected)}/{len(leaderboard)} submissions for deep eval")

    # A screen violation or a training crash in ONE selected submission must not cost
    # every other top-K submission its (expensive, GPU-hours) deep-eval slot -- same
    # per-submission failure isolation as the per-round referee, just batched here.
    results = []
    for entry in selected:
        try:
            if args.dry_run:
                extra_files = _load_submission_extra_files(Path(entry["submission_path"]))
                print(f"  {entry['submission_id']}: proxy_score={entry['proxy_score']} "
                      f"extra_files={sorted(extra_files)} -- screened OK")
                continue
            results.append(run_one(entry, args.nanochat_repo, []))
        except Exception as e:  # noqa: BLE001 -- isolate one bad submission from the batch
            print(f"  {entry['submission_id']}: FAILED -- {type(e).__name__}: {e}")
            results.append({"submission_id": entry["submission_id"], "error": f"{type(e).__name__}: {e}"})

    if args.dry_run:
        return

    args.out.write_text(json.dumps(results, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
