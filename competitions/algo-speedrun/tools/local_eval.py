#!/usr/bin/env python
"""Run one proxy training pass locally against a submission.py -- no Docker, no HTTP,
no gym_v1 plumbing. For iterating on a submission or measuring baseline_raw_score.

Requires the same dependencies referee/Dockerfile installs (torch, pyarrow, numpy,
requests, filelock, kernels, psutil, rustbpe, tiktoken) plus a real nanochat checkout on
PYTHONPATH with a trained tokenizer and at least one pretraining data shard already
present -- this exercises the real training loop, so it needs the real prerequisites
nanochat itself documents. There is no offline stub here the way research-harness's
stub_model.py is: a fake tokenizer/dataset would make the measured val_bpb meaningless,
and val_bpb is the only thing this competition scores. This exact setup is what produced
the measured `baseline_raw_score` in ../baseline/PROVENANCE.md and what
../referee/Dockerfile bakes into the referee image at build time.

Usage:
    pip install torch pyarrow numpy requests filelock kernels psutil rustbpe tiktoken
    export PYTHONPATH=/path/to/nanochat-checkout:$PYTHONPATH
    export NANOCHAT_BASE_DIR=/tmp/nanochat_cache  # or wherever you downloaded/trained into
    python -m nanochat.dataset -n 1                        # downloads 2 real shards, ~184MB
    python -m scripts.tok_train --max-chars 5000000        # trains a real tokenizer, <1s
    python tools/local_eval.py --submission ../baseline/submission.py \\
        --input ../fixtures/input.json --seed 0
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "referee"))


def _load_submission(path: Path):
    spec = importlib.util.spec_from_file_location("submission", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--input", type=Path, default=Path(__file__).parent.parent / "fixtures" / "input.json")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    from screen import screen_extra_files
    from train_runner import run_proxy_training

    cfg = json.loads(args.input.read_text())
    module = _load_submission(args.submission)
    extra_files = getattr(module, "EXTRA_FILES", {}) or {}
    screen_extra_files(extra_files)

    with tempfile.TemporaryDirectory() as scratch:
        scratch_path = Path(scratch)
        for rel_path, source in extra_files.items():
            dest = scratch_path / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(source)
        overrides_dir = scratch_path if extra_files else None
        metrics = run_proxy_training(overrides_dir, cfg, seed=args.seed, device_type=args.device)

    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
