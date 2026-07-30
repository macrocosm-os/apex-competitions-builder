"""Baseline model override: NO change from upstream nanochat.

Re-exports nanochat's own GPT/GPTConfig unmodified from the vendored, pinned checkout
(see PROVENANCE.md for the exact commit). This is the "did not touch the architecture or
optimizer" baseline that measures the pure effect of the schedule/data overrides -- and,
scored on its own, the effect of submitting nothing at all.

A miner who wants to compete on architecture or optimizer construction (setup_optimizer
is a GPT method in nanochat, so the two travel together -- see HANDOFF.md §1) replaces
this file's contents in their submission's EXTRA_FILES["model.py"] with their own
GPT-compatible class: same constructor signature, same forward(idx, targets=None) -> loss,
same init_weights()/setup_optimizer(...)/num_scaling_params()/estimate_flops() methods.
"""

from __future__ import annotations

from nanochat.gpt import GPT, GPTConfig

__all__ = ["GPT", "GPTConfig"]
