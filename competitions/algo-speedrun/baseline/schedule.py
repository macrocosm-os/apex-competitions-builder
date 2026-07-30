"""Baseline schedule override: nanochat's own warmup/warmdown/momentum/weight-decay
schedule, mechanically extracted into pure functions.

Upstream (scripts/base_train.py @ 92d63d4, see PROVENANCE.md) defines these as three
closures inline in the training script, over `args` and `num_iterations` captured from
the enclosing scope. They cannot be imported or overridden as written. This file is a
literal, non-algorithmic transcription -- same formulas, same constants -- into a
standalone module, which is what makes the schedule an overridable hook at all. Nothing
about the schedule's behavior changes; only its packaging does.

A miner competing on the schedule (e.g. a different warmdown shape, a different momentum
curve) replaces this file's contents in EXTRA_FILES["schedule.py"], keeping the same
three function signatures.
"""

from __future__ import annotations

import math


def lr_multiplier(step: int, num_iterations: int, cfg: dict) -> float:
    """Linear warmup -> constant -> linear warmdown to `final_lr_frac` of peak."""
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
    """Warms up to 0.97 over the first 400 steps, warms down to 0.90 during warmdown."""
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
    """Cosine decay of the (already batch/horizon-scaled) weight decay to zero."""
    return weight_decay_scaled * 0.5 * (1 + math.cos(math.pi * step / num_iterations))
