"""hello_world gym_v1 REFEREE (the scorer sandbox, run by convention at /app/referee.py).

Isolated from the miner submission: it holds the scoring logic and drives the player over the
per-job network. For a solo eval NUM_PLAYERS=1; the platform reads raw_scores[0].

Scores the fraction of tasks the player sorts correctly.
"""

from __future__ import annotations

import time

from apex_sdk.gym_v1 import GameResult, Referee, RefereeContext
from apex_sdk.gym_v1.client import PlayerClient, PlayerError


class HelloReferee(Referee):
    def play_game(self, ctx: RefereeContext, players: list[PlayerClient]) -> GameResult:
        start = time.monotonic()
        tasks = (ctx.config or {}).get("tasks", [])
        player = players[0]
        correct = 0
        for task in tasks:
            expected = sorted(task["numbers"])
            try:
                got = player.act(observation=list(task["numbers"]), deadline_ms=1000)
            except PlayerError:
                got = None  # unreachable/timeout -> task scored wrong; platform doesn't intervene
            if got == expected:
                correct += 1
        raw = correct / len(tasks) if tasks else 0.0
        return GameResult(
            raw_scores=[raw],
            winner=0 if correct else -1,
            terminal_reason="scored",
            steps=len(tasks),
            metadata={
                "tasks": len(tasks),
                "correct": correct,
                "eval_time_in_seconds": time.monotonic() - start,
            },
        )


if __name__ == "__main__":
    HelloReferee().run()
