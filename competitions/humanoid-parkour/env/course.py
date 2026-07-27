"""Procedural obstacle-course generation for Humanoid Parkour.

A course is a straight 20 m track along +x with box hurdles across it. All
randomness derives from a single course seed: the same (seed, difficulty)
always yields the same course. The referee derives per-instance course seeds
from the platform's per-round master SEED, so every submission in a round is
evaluated on exactly the same courses (see reference/evaluation-design.md,
"one seed per round").

This module is public by design: miners need the exact course distribution to
train against. Knowing the distribution does not reveal any specific round's
courses — those depend on the per-round SEED, which is injected only into the
referee sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

COURSE_LENGTH = 20.0  # metres from start (x=0) to finish line
TRACK_HALF_WIDTH = 2.0  # |y| beyond this is out of bounds (episode ends)

DIFFICULTIES = ("easy", "medium", "hard")

# n hurdles (inclusive range), hurdle height range (m), gap between hurdles (m).
_PARAMS = {
    "easy": dict(n=(3, 4), height=(0.05, 0.15), gap=(3.0, 4.5)),
    "medium": dict(n=(4, 5), height=(0.12, 0.25), gap=(2.5, 4.0)),
    "hard": dict(n=(5, 6), height=(0.20, 0.35), gap=(2.0, 3.5)),
}

_FIRST_HURDLE_MIN_X = 3.0  # room to accelerate before the first hurdle
_LAST_HURDLE_MAX_X = COURSE_LENGTH - 2.0  # room to finish after the last one

_HUMANOID_XML = Path(__file__).parent / "assets_humanoid.xml"


@dataclass(frozen=True)
class Hurdle:
    x: float  # centre of the hurdle along the track
    height: float
    depth: float  # extent along x


def generate_course(seed: int, difficulty: str) -> list[Hurdle]:
    """Deterministically generate one course. Same (seed, difficulty) -> same course."""
    params = _PARAMS[difficulty]
    rng = np.random.default_rng(seed)
    n = int(rng.integers(params["n"][0], params["n"][1] + 1))
    hurdles: list[Hurdle] = []
    x = _FIRST_HURDLE_MIN_X + float(rng.uniform(0.0, 1.0))
    for _ in range(n):
        if x > _LAST_HURDLE_MAX_X:
            break
        hurdles.append(
            Hurdle(
                x=round(x, 3),
                height=round(float(rng.uniform(*params["height"])), 3),
                depth=round(float(rng.uniform(0.10, 0.25)), 3),
            )
        )
        x += float(rng.uniform(*params["gap"]))
    return hurdles


def course_xml(hurdles: list[Hurdle]) -> str:
    """The humanoid MJCF with the course's hurdle geoms injected into the worldbody.

    The base model is the standard Gymnasium humanoid (vendored so scores can't
    drift with a gymnasium upgrade). Hurdles are static boxes spanning slightly
    more than the track width so they can't be corner-clipped at |y| ~ 2.
    """
    xml = _HUMANOID_XML.read_text()
    geoms = "".join(
        f'        <geom name="hurdle_{i}" type="box" '
        f'pos="{h.x} 0 {h.height / 2}" '
        f'size="{h.depth / 2} {TRACK_HALF_WIDTH + 0.5} {h.height / 2}" '
        f'condim="3" friction="1 .1 .1" rgba="0.25 0.35 0.8 1"/>\n'
        for i, h in enumerate(hurdles)
    )
    return xml.replace("    </worldbody>", geoms + "    </worldbody>")
