"""MuJoCo simulation of one Humanoid Parkour episode.

Deterministic by construction: same (course, seed, action sequence) -> same
trajectory. The referee owns the physics; the player only ever sees the
observation vector and returns an action vector.

Observation (float32, OBS_DIM = 56):
    [0]      torso y (stay within |y| <= TRACK_HALF_WIDTH)
    [1]      distance to finish line (COURSE_LENGTH - torso x)
    [2:24]   qpos[2:] (torso z, orientation quaternion, joint angles)
    [24:47]  qvel
    [47:56]  next 3 hurdles ahead, (dx, height, depth) each; (50, 0, 0) padding

Action (float32, ACT_DIM = 17): joint torques, clipped to the actuator
ctrlrange [-0.4, 0.4].

Termination gates (each maps to a terminal_reason the miner sees post-round):
    completed       torso x past the finish line
    fell            torso z < 1.0, or any non-foot robot geom touching the floor
    out_of_bounds   |torso y| > TRACK_HALF_WIDTH (no running around the hurdles)
    physics_glitch  NaN/Inf state or |qvel| > 100 (glitch-surfing scores 0)
    timeout         max_steps control steps elapsed
"""

from __future__ import annotations

from dataclasses import dataclass

import mujoco
import numpy as np

from .course import COURSE_LENGTH, TRACK_HALF_WIDTH, Hurdle, course_xml

OBS_DIM = 56
ACT_DIM = 17
K_HURDLES = 3  # hurdles visible ahead in the observation
FRAME_SKIP = 5  # 5 x 0.003 s = 15 ms per control step (~66 Hz)
DEFAULT_MAX_STEPS = 1200  # 18 s of sim time
MIN_TORSO_Z = 1.0
CTRL_RANGE = 0.4
QVEL_GLITCH_LIMIT = 100.0
RESET_NOISE = 0.01
_PAD_HURDLE = (50.0, 0.0, 0.0)


class InvalidAction(ValueError):
    """The action was not a finite ACT_DIM vector."""


@dataclass(frozen=True)
class StepResult:
    obs: np.ndarray
    terminal_reason: str | None  # None while the episode is still running


class ParkourSim:
    def __init__(self, hurdles: list[Hurdle]):
        self.hurdles = sorted(hurdles, key=lambda h: h.x)
        self.model = mujoco.MjModel.from_xml_string(course_xml(self.hurdles))
        self.data = mujoco.MjData(self.model)
        self._floor = self.model.geom("floor").id
        self._feet = {self.model.geom("left_foot").id, self.model.geom("right_foot").id}
        self.steps = 0
        self.max_x = 0.0

    def reset(self, seed: int) -> np.ndarray:
        mujoco.mj_resetData(self.model, self.data)
        rng = np.random.default_rng(seed)
        self.data.qpos[:] += rng.uniform(-RESET_NOISE, RESET_NOISE, self.model.nq)
        self.data.qvel[:] += rng.uniform(-RESET_NOISE, RESET_NOISE, self.model.nv)
        mujoco.mj_forward(self.model, self.data)
        self.steps = 0
        self.max_x = 0.0
        return self._obs()

    def step(self, action, max_steps: int = DEFAULT_MAX_STEPS) -> StepResult:
        a = np.asarray(action, dtype=np.float64).ravel()
        if a.shape != (ACT_DIM,) or not np.all(np.isfinite(a)):
            raise InvalidAction(f"action must be {ACT_DIM} finite floats, got shape {a.shape}")
        self.data.ctrl[:] = np.clip(a, -CTRL_RANGE, CTRL_RANGE)
        for _ in range(FRAME_SKIP):
            mujoco.mj_step(self.model, self.data)
        self.steps += 1
        self.max_x = max(self.max_x, float(self.data.qpos[0]))
        return StepResult(obs=self._obs(), terminal_reason=self._terminal(max_steps))

    @property
    def progress(self) -> float:
        """Fraction of the course covered, in [0, 1]."""
        return float(np.clip(self.max_x / COURSE_LENGTH, 0.0, 1.0))

    def _terminal(self, max_steps: int) -> str | None:
        qpos, qvel = self.data.qpos, self.data.qvel
        if not (np.all(np.isfinite(qpos)) and np.all(np.isfinite(qvel))):
            return "physics_glitch"
        if np.max(np.abs(qvel)) > QVEL_GLITCH_LIMIT:
            return "physics_glitch"
        if qpos[0] >= COURSE_LENGTH:
            return "completed"
        if qpos[2] < MIN_TORSO_Z or self._nonfoot_floor_contact():
            return "fell"
        if abs(qpos[1]) > TRACK_HALF_WIDTH:
            return "out_of_bounds"
        if self.steps >= max_steps:
            return "timeout"
        return None

    def _nonfoot_floor_contact(self) -> bool:
        """True when a robot geom other than a foot touches the floor (legs-only gate)."""
        for i in range(self.data.ncon):
            g1, g2 = self.data.contact[i].geom1, self.data.contact[i].geom2
            if self._floor in (g1, g2):
                other = g2 if g1 == self._floor else g1
                if other not in self._feet:
                    return True
        return False

    def _obs(self) -> np.ndarray:
        x, y = float(self.data.qpos[0]), float(self.data.qpos[1])
        ahead = [h for h in self.hurdles if h.x + h.depth / 2 > x][:K_HURDLES]
        feats = [(h.x - x, h.height, h.depth) for h in ahead]
        feats += [_PAD_HURDLE] * (K_HURDLES - len(feats))
        return np.concatenate(
            [
                [y, COURSE_LENGTH - x],
                self.data.qpos[2:],
                self.data.qvel,
                np.asarray(feats).ravel(),
            ]
        ).astype(np.float32)
