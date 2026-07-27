"""Gymnasium wrapper for miner-side training (PPO or anything else).

This is NOT used by the referee — it exists so miners can train against the
exact physics, observations, and termination gates used in evaluation. Each
reset samples a fresh random course, so policies must generalize across the
course distribution rather than memorize a layout (each evaluation round uses
unseen courses drawn from a fresh master seed).

The shaped reward is a reasonable default for PPO, not the competition metric:
the leaderboard scores completion and speed only (see scoring.py). Reshape it
however you like — only the submitted policy matters.

Requires `gymnasium` (not needed by the referee or player images).
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np

from .course import DIFFICULTIES, generate_course
from .scoring import instance_score
from .sim import ACT_DIM, CTRL_RANGE, DEFAULT_MAX_STEPS, OBS_DIM, ParkourSim


class HumanoidParkourEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, difficulty: str | None = None, max_steps: int = DEFAULT_MAX_STEPS):
        self.difficulty = difficulty  # None -> sample uniformly per episode
        self.max_steps = max_steps
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (OBS_DIM,), np.float32)
        self.action_space = gym.spaces.Box(-CTRL_RANGE, CTRL_RANGE, (ACT_DIM,), np.float32)
        self.sim: ParkourSim | None = None

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        difficulty = self.difficulty or DIFFICULTIES[int(self.np_random.integers(len(DIFFICULTIES)))]
        course_seed = int(self.np_random.integers(2**31))
        self.sim = ParkourSim(generate_course(course_seed, difficulty))
        obs = self.sim.reset(seed=course_seed)
        self._prev_x = float(self.sim.data.qpos[0])
        return obs, {"difficulty": difficulty, "course_seed": course_seed}

    def step(self, action):
        result = self.sim.step(action, max_steps=self.max_steps)
        x = float(self.sim.data.qpos[0])

        # Shaped training reward (Gymnasium-Humanoid-like scales): forward
        # velocity + alive bonus - control cost, plus the true instance score
        # on termination. dt per control step is 0.015 s (frame skip 5 x 3 ms).
        velocity = (x - self._prev_x) / 0.015
        reward = 1.25 * velocity + 1.0 - 0.1 * float(np.sum(np.square(action)))
        self._prev_x = x

        reason = result.terminal_reason
        terminated = reason is not None and reason != "timeout"
        truncated = reason == "timeout"
        info = {"progress": self.sim.progress}
        if reason is not None:
            score = instance_score(reason, self.sim.progress, self.sim.steps, self.max_steps)
            reward += 10.0 * score if reason == "completed" else 0.0
            info |= {"terminal_reason": reason, "instance_score": score}
        return result.obs, reward, terminated, truncated, info
