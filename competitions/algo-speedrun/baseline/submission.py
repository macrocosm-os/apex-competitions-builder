"""Baseline submission: zero training-loop changes.

`EXTRA_FILES` is the miner's override surface -- an optional map of {relative_path:
file_contents} that the referee AST-screens and materializes into its scratch nanochat
checkout before importing (see referee/referee.py, referee/screen.py). Recognized keys:

    "model.py"     GPTConfig + GPT-compatible class (architecture AND optimizer --
                    setup_optimizer is a GPT method in upstream nanochat, so the two
                    travel together; see HANDOFF.md §1)
    "schedule.py"   lr_multiplier(step, num_iterations, cfg) -> float
                    muon_momentum(step, num_iterations, cfg) -> float
                    weight_decay(step, num_iterations, cfg, weight_decay_scaled) -> float
    "data.py"       data_iterator(tokenizer, B, T, split, device, resume_state_dict=None)
                    -> yields (inputs, targets, state_dict)

Any key omitted falls back to referee/train_runner.py's built-in default, which is a
verbatim copy of nanochat's own logic for that piece (see baseline/model.py,
baseline/schedule.py, baseline/data.py -- those files exist so the defaults are
reviewable in this repo, not so a submission has to restate them). An empty EXTRA_FILES,
as here, is therefore "change nothing" -- the measured baseline_raw_score in spec.yaml.

Use tools/pack_submission.py to build a real submission.py from a directory containing
whichever of model.py / schedule.py / data.py you actually changed.
"""

from __future__ import annotations

EXTRA_FILES: dict[str, str] = {}
