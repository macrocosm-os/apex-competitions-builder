"""Tests for referee/train_runner.py against REAL nanochat code (not mocks) -- per
HANDOFF.md's standard of actually running things, not just reasoning about them. Skips
itself if torch/nanochat aren't importable (see conftest.py's docstring for how to set
that up locally; referee/Dockerfile installs the same deps at image build time).

Tokenizer and dataloader are monkeypatched (a real trained tokenizer + real pretraining
data shard are real infra, not unit-test fixtures -- see baseline/PROVENANCE.md), but
GPT/GPTConfig/setup_optimizer/evaluate scoring are the genuine nanochat classes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("nanochat")

import nanochat.dataloader as dl_mod  # noqa: E402
import nanochat.tokenizer as tok_mod  # noqa: E402

VOCAB = 1024
CFG = {
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
        x = torch.randint(0, VOCAB, (B, T), device=device)
        y = torch.randint(0, VOCAB, (B, T), device=device)
        yield x, y, {"split": split}


@pytest.fixture(autouse=True)
def _patch_tokenizer_and_dataloader(monkeypatch):
    monkeypatch.setattr(tok_mod, "get_tokenizer", lambda: _FakeTokenizer())
    monkeypatch.setattr(tok_mod, "get_token_bytes", lambda device="cpu": torch.randint(1, 5, (VOCAB,), device=device))
    monkeypatch.setattr(dl_mod, "tokenizing_distributed_data_loader_with_state_bos_bestfit", _fake_loader)
    # train_runner imports these by name inside functions, so re-import to pick up the
    # patched module attributes rather than a stale cached reference.
    import importlib

    import train_runner

    importlib.reload(train_runner)
    yield
    importlib.reload(train_runner)


def test_default_path_runs_and_scores():
    from train_runner import run_proxy_training

    metrics = run_proxy_training(None, CFG, seed=0, device_type="cpu")
    assert metrics["tokens_trained"] == CFG["total_batch_size"] * CFG["num_iterations"]
    assert 0.0 < metrics["val_bpb"] < 100.0  # a real, finite bpb, not degenerate


def test_schedule_override_path_runs():
    from train_runner import run_proxy_training

    with tempfile.TemporaryDirectory() as d:
        Path(d, "schedule.py").write_text(
            "def lr_multiplier(step, n, cfg):\n    return 0.5\n"
            "def muon_momentum(step, n, cfg):\n    return 0.9\n"
            "def weight_decay(step, n, cfg, s):\n    return s\n"
        )
        metrics = run_proxy_training(Path(d), CFG, seed=0, device_type="cpu")
    assert 0.0 < metrics["val_bpb"] < 100.0


class TestValSplitCannotBeCheated:
    """HANDOFF.md §8 item 2: a malicious data.py that special-cases split=='val' to
    return degenerate batches must be completely ignored."""

    def test_val_override_attempt_is_ignored(self):
        from train_runner import run_proxy_training

        honest = run_proxy_training(None, CFG, seed=0, device_type="cpu")

        with tempfile.TemporaryDirectory() as d:
            Path(d, "data.py").write_text(
                "import torch\n"
                "def data_iterator(tokenizer, B, T, split, device='cpu', resume_state_dict=None):\n"
                "    if split == 'val':\n"
                "        while True:\n"
                "            z = torch.zeros((B, T), dtype=torch.long, device=device)\n"
                "            yield z, z, {}\n"
                "    else:\n"
                "        while True:\n"
                f"            yield torch.randint(0, {VOCAB}, (B, T), device=device), "
                f"torch.randint(0, {VOCAB}, (B, T), device=device), {{}}\n"
            )
            cheated = run_proxy_training(Path(d), CFG, seed=0, device_type="cpu")

        # Same seed, same architecture, same (ignored) val override -> identical score.
        # If the val-split override were honored, this would be near-zero instead.
        assert cheated["val_bpb"] == pytest.approx(honest["val_bpb"])


class TestModelCannotFakeItsOwnScore:
    """HANDOFF.md §8 item 3: a model that lies about its own loss must not affect the
    independently-computed val_bpb."""

    def test_disconnected_fake_loss_crashes_cleanly_not_silently(self):
        from train_runner import run_proxy_training

        with tempfile.TemporaryDirectory() as d:
            Path(d, "model.py").write_text(
                "import torch\n"
                "from nanochat.gpt import GPT as _GPT, GPTConfig\n"
                "class GPT(_GPT):\n"
                "    def forward(self, idx, targets=None, kv_cache=None, loss_reduction='mean'):\n"
                "        if targets is not None:\n"
                "            return torch.tensor(0.0001, requires_grad=True)\n"
                "        return super().forward(idx, targets=None)\n"
            )
            with pytest.raises(Exception):  # no valid gradients -- optimizer step fails
                run_proxy_training(Path(d), CFG, seed=0, device_type="cpu")

    def test_graph_connected_fake_training_loss_does_not_lower_val_bpb(self):
        from train_runner import run_proxy_training

        with tempfile.TemporaryDirectory() as d:
            Path(d, "model.py").write_text(
                "import torch\n"
                "from nanochat.gpt import GPT as _GPT, GPTConfig\n"
                "class GPT(_GPT):\n"
                "    def forward(self, idx, targets=None, kv_cache=None, loss_reduction='mean'):\n"
                "        if targets is not None:\n"
                "            real = super().forward(idx, targets=targets, kv_cache=kv_cache, loss_reduction=loss_reduction)\n"
                "            return real * 0.0 + 0.0001\n"
                "        return super().forward(idx, targets=None)\n"
            )
            metrics = run_proxy_training(Path(d), CFG, seed=0, device_type="cpu")
        # A real, finite bpb reflecting actual (here: untrained, since gradients were
        # zeroed) predictive quality -- NOT an artificially tiny number near the fake
        # 0.0001 training loss the model tried to report.
        assert metrics["val_bpb"] > 1.0
