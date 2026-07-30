"""End-to-end tests for referee/referee.py against REAL nanochat code, driven through a
fake PlayerClient rather than real HTTP (no network needed, but everything downstream of
the player boundary -- exec, screen, materialize, train, score -- is genuine). Skips
itself if torch/nanochat aren't importable; see conftest.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("nanochat")

import apex_sdk.gym_v1.referee as sdk_referee_mod  # noqa: E402
import nanochat.dataloader as dl_mod  # noqa: E402
import nanochat.tokenizer as tok_mod  # noqa: E402

VOCAB = 1024
ROUND_CFG = {
    "depth": 2, "max_seq_len": 32, "device_batch_size": 1,
    "total_batch_size": 32, "num_iterations": 3, "eval_tokens": 64,
}


class _FakeTokenizer:
    def get_vocab_size(self):
        return VOCAB

    def get_bos_token_id(self):
        return 0


def _fake_loader(tokenizer, B, T, split, device="cpu", resume_state_dict=None):
    while True:
        yield (
            torch.randint(0, VOCAB, (B, T), device=device),
            torch.randint(0, VOCAB, (B, T), device=device),
            {},
        )


class _FakePlayer:
    def __init__(self, content: str):
        self.content = content

    def reset(self, **kw):
        pass

    def act(self, observation, deadline_ms):
        return {"content": self.content}


class _FakeCtx:
    match_id = "m1"
    seed = 0
    config = ROUND_CFG


@pytest.fixture(autouse=True)
def _patch_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(tok_mod, "get_tokenizer", lambda: _FakeTokenizer())
    monkeypatch.setattr(tok_mod, "get_token_bytes", lambda device="cpu": torch.randint(1, 5, (VOCAB,), device=device))
    monkeypatch.setattr(dl_mod, "tokenizing_distributed_data_loader_with_state_bos_bestfit", _fake_loader)
    # Referee.trace() writes to a hardcoded /data path that only exists inside the real
    # sandbox; redirect it so tests don't need root or a real /data mount.
    monkeypatch.setattr(sdk_referee_mod, "TRACE_PATH", tmp_path / "trace.jsonl")
    monkeypatch.setattr(sdk_referee_mod, "RESULT_PATH", tmp_path / "result.json")

    import importlib

    import referee
    import train_runner

    importlib.reload(train_runner)
    importlib.reload(referee)
    yield
    importlib.reload(train_runner)
    importlib.reload(referee)


def _referee():
    import referee

    return referee.SpeedrunReferee()


def test_normal_submission_scores():
    ref = _referee()
    result = ref.play_game(_FakeCtx(), [_FakePlayer("EXTRA_FILES = {}")])
    assert result.terminal_reason == "scored"
    assert 0.0 < result.raw_scores[0] < 100.0


def test_hanging_submission_is_attributed_to_the_submission_not_a_referee_crash():
    """HANDOFF.md §8 item 4: without the watchdog, this would run out timeout_s and be
    read by the platform as a referee crash (0 for everyone, referee blamed)."""
    import referee

    referee.TRAIN_WALLCLOCK_BUDGET_S = 2.0
    ref = _referee()
    hang_schedule = (
        "import time\n"
        "def lr_multiplier(step, n, cfg):\n"
        "    time.sleep(999)\n"
        "    return 1.0\n"
        "def muon_momentum(step, n, cfg):\n    return 0.9\n"
        "def weight_decay(step, n, cfg, s):\n    return s\n"
    )
    submission = f"EXTRA_FILES = {{'schedule.py': {hang_schedule!r}}}"
    result = ref.play_game(_FakeCtx(), [_FakePlayer(submission)])
    assert result.terminal_reason == "training_timeout"
    assert result.raw_scores[0] == pytest.approx(1e9)  # WORST_SCORE, not 0 / crash


@pytest.mark.parametrize(
    "evil_path",
    ["/etc/pwned.py", "../../etc/pwned.py"],
)
def test_path_traversal_via_extra_files_is_blocked_before_any_write(evil_path, tmp_path):
    ref = _referee()
    submission = f"EXTRA_FILES = {{{evil_path!r}: 'x = 1'}}"
    result = ref.play_game(_FakeCtx(), [_FakePlayer(submission)])
    assert result.terminal_reason == "screen_violation"
    assert not Path("/etc/pwned.py").exists()


def test_forbidden_import_in_extra_files_is_blocked():
    ref = _referee()
    submission = "EXTRA_FILES = {'model.py': 'import socket\\n'}"
    result = ref.play_game(_FakeCtx(), [_FakePlayer(submission)])
    assert result.terminal_reason == "screen_violation"


def test_empty_submission_content_fails_cleanly():
    ref = _referee()
    result = ref.play_game(_FakeCtx(), [_FakePlayer("")])
    assert result.terminal_reason == "empty_submission"


def test_unparseable_submission_fails_cleanly():
    ref = _referee()
    result = ref.play_game(_FakeCtx(), [_FakePlayer("this is not python (")])
    assert result.terminal_reason == "submission_load_failed"
