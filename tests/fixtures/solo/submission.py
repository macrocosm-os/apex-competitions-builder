"""A stand-in miner artifact, so CLI tests have a real file to pass to --submission."""

from __future__ import annotations


def sort_numbers(numbers: list[float]) -> list[float]:
    return sorted(numbers)
