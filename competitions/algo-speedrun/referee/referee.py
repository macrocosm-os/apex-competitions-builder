"""algo_speedrun gym_v1 REFEREE (the scorer sandbox, run at /app/referee.py).

Generalizes research-harness's "referee owns the model" invariant to "referee owns the
trainer": the PLAYER never trains anything (see player/launch.py) -- it holds the
miner's screened submission.py and returns its raw text over a single gym_v1 /act call.
This referee then executes that submission's code *directly in its own process* (unlike
research-harness, where the harness runs inside the player sandbox and the referee only
ever sees HTTP actions) -- a deliberate, documented deviation, because GPU training has
to happen where the GPU is, and doctrine keeps GPU off the player (HANDOFF.md §2).

Because the miner's model/schedule/data-loader code runs inside this process, a bad
submission (shape error, NaN, unsupported op) must be attributed to the SUBMISSION, not
treated as a referee crash -- unlike the base Referee class's general doctrine ("let
unexpected exceptions propagate so the platform blames the referee"), the broad
try/except below around exec+train is intentional here. See HANDOFF.md §4.

A submission that hangs (an infinite loop, a pathological forward()) needs the same
attribution: without an internal deadline, it would run out the container's own
`timeout_s` and get killed by the platform, which -- per `Referee.run()`'s own doctrine --
reads as a referee crash (no result.json -> the platform scores 0 for everyone and blames
the referee, not the submission). `_run_with_deadline` below runs training on a daemon
thread with its own, much shorter deadline so a hang is caught and scored here, well
before the container timeout ever triggers.
"""

from __future__ import annotations

import importlib.util
import queue
import tempfile
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from apex_sdk.gym_v1 import GameResult, Referee, RefereeContext
from apex_sdk.gym_v1.client import PlayerClient, PlayerError

from screen import ScreenViolation, materialize_extra_files, screen_extra_files
from train_runner import run_proxy_training

# Mirrors input.schema.json's defaults -- CONFIG_JSON (ctx.config) only ever overrides
# a subset of these, per the round's input schema.
DEFAULT_CFG: dict[str, Any] = {
    "depth": 4,
    "max_seq_len": 512,
    "device_batch_size": 1,
    "total_batch_size": 512,
    "num_iterations": 20,
    "eval_tokens": 4096,
}

WORST_SCORE = 1e9  # spec.yaml: lower_is_better -- a large finite sentinel (not inf: keeps result.json standard JSON)

# Comfortably above what the tiny proxy scale needs (measured: low single-digit seconds
# on CPU for the default cfg) and comfortably below referee.timeout_s (1800s in
# spec.yaml), leaving margin for submission fetch + screening + platform overhead.
TRAIN_WALLCLOCK_BUDGET_S = 300.0


def _exec_submission(content: str) -> ModuleType:
    spec = importlib.util.spec_from_loader("submission", loader=None)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    exec(compile(content, "submission.py", "exec"), module.__dict__)
    return module


class _TrainingTimeout(RuntimeError):
    """Raised in the calling thread when the training thread doesn't finish in time.
    The training thread itself is left running (daemon=True) -- we just stop waiting and
    score the submission as failed; the process still exits cleanly once play_game
    returns, since a daemon thread never blocks interpreter shutdown."""


def _run_with_deadline(fn, args: tuple, deadline_s: float):
    """Run fn(*args) on a daemon thread and return its result, or raise
    _TrainingTimeout if it doesn't finish within deadline_s. Exceptions raised by fn are
    re-raised in the calling thread so existing failure handling still applies."""
    result_q: queue.Queue = queue.Queue(maxsize=1)

    def _target():
        try:
            result_q.put(("ok", fn(*args)))
        except BaseException as e:  # noqa: BLE001 -- must not swallow OOM/system errors either
            result_q.put(("error", e))

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=deadline_s)
    if thread.is_alive():
        raise _TrainingTimeout(f"training did not finish within {deadline_s}s")
    kind, payload = result_q.get_nowait()
    if kind == "error":
        raise payload
    return payload


class SpeedrunReferee(Referee):
    def play_game(self, ctx: RefereeContext, players: list[PlayerClient]) -> GameResult:
        cfg = {**DEFAULT_CFG, **(ctx.config or {})}
        player = players[0]

        try:
            player.reset(match_id=ctx.match_id, player_index=0, seed=ctx.seed, config={})
            action = player.act(observation={"op": "fetch_submission"}, deadline_ms=10_000)
        except PlayerError as e:
            return self._fail("player_unreachable", str(e))

        content = action.get("content") if isinstance(action, dict) else None
        if not content:
            return self._fail("empty_submission", "player returned no submission content")

        try:
            module = _exec_submission(content)
            extra_files: dict[str, str] = getattr(module, "EXTRA_FILES", {}) or {}
            screen_extra_files(extra_files)
        except ScreenViolation as e:
            return self._fail("screen_violation", str(e))
        except Exception as e:
            return self._fail("submission_load_failed", f"{type(e).__name__}: {e}")

        try:
            with tempfile.TemporaryDirectory() as scratch:
                scratch_path = Path(scratch)
                # materialize_extra_files validates every path stays inside scratch_path
                # before writing anything -- see screen.py's module docstring for the
                # arbitrary-file-write bug this replaced.
                materialize_extra_files(scratch_path, extra_files)
                overrides_dir = scratch_path if extra_files else None
                metrics = _run_with_deadline(
                    run_proxy_training, (overrides_dir, cfg, ctx.seed), TRAIN_WALLCLOCK_BUDGET_S
                )
        except ScreenViolation as e:
            return self._fail("screen_violation", str(e))
        except _TrainingTimeout as e:
            return self._fail("training_timeout", str(e))
        except Exception as e:
            # Attributed to the submission -- see module docstring for why this is a
            # deliberate broad catch, unlike the base Referee class's default doctrine.
            return self._fail("training_failed", f"{type(e).__name__}: {e}")

        return GameResult(
            raw_scores=[round(metrics["val_bpb"], 6)],
            winner=0,
            terminal_reason="scored",
            steps=cfg["num_iterations"],
            metadata=metrics,
        )

    def _fail(self, reason: str, detail: str) -> GameResult:
        self.trace({"terminal_reason": reason, "detail": detail})
        return GameResult(
            raw_scores=[WORST_SCORE],
            winner=-1,
            terminal_reason=reason,
            steps=0,
            metadata={"error": detail},
        )


if __name__ == "__main__":
    SpeedrunReferee().run()
