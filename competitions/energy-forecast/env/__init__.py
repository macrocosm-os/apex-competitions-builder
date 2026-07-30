"""Shared domain logic for energy-forecast: data access, features, scoring.

Imported by both the referee and local dev tools so the numbers a miner sees
locally can never diverge from what the referee actually scores.
"""

from env.data import BALANCING_AUTHORITIES, Instance, sample_instances
from env.features import HISTORY_HOURS, HORIZON_HOURS, NUM_FEATURES, build_observation
from env.scoring import instance_skill_score

__all__ = [
    "BALANCING_AUTHORITIES",
    "Instance",
    "sample_instances",
    "HISTORY_HOURS",
    "HORIZON_HOURS",
    "NUM_FEATURES",
    "build_observation",
    "instance_skill_score",
]
