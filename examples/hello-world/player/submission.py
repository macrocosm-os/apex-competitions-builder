"""Reference submission for hello_world.

A miner's `submission.py` must expose `sort_numbers(numbers)` returning the list sorted
ascending. This reference implementation is what a baseline miner would submit; the
platform writes the miner's version to `target_path` (/app/submission.py) at eval time.
"""

from __future__ import annotations


def sort_numbers(numbers: list[float]) -> list[float]:
    return sorted(numbers)
