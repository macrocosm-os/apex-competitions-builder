"""humanoid_parkour gym_v1 REFEREE (the scorer sandbox, run at /app/referee.py).

Owns the physics: generates the round's courses from the platform-injected
master SEED, steps MuJoCo, streams observations to the player over /act, and
applies the termination + scoring gates. The player sandbox only ever sees
observation vectors — never the seed, the generator, or the course list.

raw_score = mean instance score over all courses (see env/scoring.py).
Per-course breakdowns go in metadata: hidden while the round is active,
revealed to miners when it completes.
"""

from __future__ import annotations

import time

import numpy as np

from apex_sdk.gym_v1 import GameResult, Referee, RefereeContext
from apex_sdk.gym_v1.client import PlayerClient, PlayerError

from env import DIFFICULTIES, ParkourSim, generate_course, instance_score
from env.sim import InvalidAction

# Sized per HANDOFF.md §4: N = 3 x 40 = 120 course instances, 900-step episode
# cap (13.5 s sim time). The round input (CONFIG_JSON) can override.
DEFAULT_COURSES_PER_DIFFICULTY = 40
DEFAULT_MAX_STEPS = 900
DEFAULT_DEADLINE_MS = 500


class ParkourReferee(Referee):
    def play_game(self, ctx: RefereeContext, players: list[PlayerClient]) -> GameResult:
        start = time.monotonic()
        cfg = ctx.config or {}
        per_difficulty = int(cfg.get("courses_per_difficulty", DEFAULT_COURSES_PER_DIFFICULTY))
        max_steps = int(cfg.get("max_steps_per_episode", DEFAULT_MAX_STEPS))
        deadline_ms = int(cfg.get("deadline_ms", DEFAULT_DEADLINE_MS))
        player = players[0]

        # All courses derive from the per-round master seed: every submission
        # in the round runs exactly these instances, so identical resubmissions
        # score identically (no seed-fishing).
        instances = [
            (difficulty, int(seed))
            for d_idx, difficulty in enumerate(DIFFICULTIES)
            for seed in np.random.SeedSequence([ctx.seed, d_idx]).generate_state(per_difficulty)
        ]

        courses = []
        total = 0.0
        for i, (difficulty, course_seed) in enumerate(instances):
            sim = ParkourSim(generate_course(course_seed, difficulty))
            obs = sim.reset(seed=course_seed)
            player.reset(match_id=f"{ctx.match_id}:{i}", player_index=0, seed=course_seed, config={})

            reason = None
            while reason is None:
                try:
                    action = player.act(observation=obs.tolist(), deadline_ms=deadline_ms)
                    result = sim.step(action, max_steps=max_steps)
                except PlayerError:
                    reason = "player_error"  # unreachable / timed out / HTTP error
                    break
                except (InvalidAction, TypeError):
                    reason = "invalid_action"  # NaN / wrong shape / non-numeric
                    break
                obs, reason = result.obs, result.terminal_reason

            score = instance_score(reason, sim.progress, sim.steps, max_steps)
            total += score
            courses.append(
                {
                    "difficulty": difficulty,
                    "terminal_reason": reason,
                    "progress": round(sim.progress, 4),
                    "steps": sim.steps,
                    "sim_time_s": round(sim.steps * 0.015, 2),
                    "score": round(score, 4),
                }
            )

        completed = sum(c["terminal_reason"] == "completed" for c in courses)
        raw = total / len(courses)
        return GameResult(
            raw_scores=[raw],
            winner=0 if raw > 0 else -1,
            terminal_reason="scored",
            steps=sum(c["steps"] for c in courses),
            metadata={
                "courses": courses,
                "num_courses": len(courses),
                "num_completed": completed,
                "eval_time_in_seconds": round(time.monotonic() - start, 1),
            },
        )


if __name__ == "__main__":
    ParkourReferee().run()
