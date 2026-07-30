"""Default schedule used when a submission's EXTRA_FILES has no "schedule.py".

Verbatim copy of ../baseline/schedule.py (see that file's docstring for provenance) --
kept as a separate, referee-importable module because train_runner.py falls back to it
by `import schedule_defaults`, not by reading the baseline/ directory at eval time (the
referee image only ships what it needs; baseline/ exists for review and local dev).
"""

from __future__ import annotations

import math


def lr_multiplier(step: int, num_iterations: int, cfg: dict) -> float:
    warmup_iters = cfg["warmup_steps"]
    warmdown_iters = round(cfg["warmdown_ratio"] * num_iterations)
    if step < warmup_iters:
        return (step + 1) / warmup_iters
    elif step <= num_iterations - warmdown_iters:
        return 1.0
    else:
        progress = (num_iterations - step) / warmdown_iters
        return progress * 1.0 + (1 - progress) * cfg["final_lr_frac"]


def muon_momentum(step: int, num_iterations: int, cfg: dict) -> float:
    warmdown_iters = round(cfg["warmdown_ratio"] * num_iterations)
    warmdown_start = num_iterations - warmdown_iters
    if step < 400:
        frac = step / 400
        return (1 - frac) * 0.85 + frac * 0.97
    elif step >= warmdown_start:
        progress = (step - warmdown_start) / warmdown_iters
        return 0.97 * (1 - progress) + 0.90 * progress
    else:
        return 0.97


def weight_decay(step: int, num_iterations: int, cfg: dict, weight_decay_scaled: float) -> float:
    return weight_decay_scaled * 0.5 * (1 + math.cos(math.pi * step / num_iterations))
