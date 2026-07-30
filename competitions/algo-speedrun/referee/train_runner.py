"""The proxy training pass -- adapted from upstream nanochat's `scripts/base_train.py`
(pinned commit `92d63d4e8bb4df75c3b71618f31ddde2378b2bcd`, see baseline/PROVENANCE.md),
trimmed down to what a cheap, every-round eval needs and parameterized so the model,
schedule, and data-loading pieces can each be swapped for a miner's override.

Deliberately dropped vs. upstream (all orthogonal to scoring a training-loop change at
proxy scale -- see HANDOFF.md §5 for why these are reserved for the out-of-band deep eval
instead): DDP / multi-GPU, FP8 training, torch.compile, meta-device init, checkpoint
save/resume, wandb logging, CORE-benchmark evaluation, sampling. What's kept is exactly
upstream's algorithm for the pieces every submission shares: scaling-law-derived batch
size / weight-decay correction (lines 260-304 of the pinned base_train.py), the training
step body (lines 505-544), and the val-bpb evaluation (`nanochat.loss_eval.evaluate_bpb`).

Overridable via `overrides_dir` (optional; see referee.py for how it's populated from a
miner's EXTRA_FILES): `model.py` (GPTConfig, GPT), `schedule.py` (lr_multiplier,
muon_momentum, weight_decay), `data.py` (data_iterator, TRAIN SPLIT ONLY -- see
`_val_data_iterator`). Any file absent falls back to the DEFAULT_* below, which are
verbatim copies of upstream's own logic -- see baseline/model.py, baseline/schedule.py,
baseline/data.py for the reviewable originals.

Two adversarial-design decisions live here, both found by actually threat-modeling "the
model computes its own score":

1. **The validation split is never overridable**, even though `data.py` is a legitimate
   hook for training data. If it were, a malicious `data_iterator` could special-case
   `split == "val"` to hand back degenerate, trivially-predictable batches and fake an
   arbitrarily low val_bpb unrelated to real training quality. See `_val_data_iterator`.
2. **The scored metric is never the model's own reported loss.** Calling
   `evaluate_bpb(model, ...)` the way upstream does trusts `model(x, y, loss_reduction=
   'none')` -- a fully miner-controlled `forward()` -- to honestly report its own loss. A
   malicious model could return an arbitrary loss tensor disconnected from its actual
   predictions. `_referee_evaluate_bpb` instead calls the model with `targets=None`
   (upstream's own forward() returns raw logits in that case -- verified against the
   pinned commit) and computes cross-entropy against the true `y` independently, so the
   model never even sees the validation targets it's scored against, let alone reports
   its own loss on them. Training loss (`model(x, y)` inside the training loop) is left
   as the model's own computation -- if a miner's model lies there, it only sabotages its
   own gradients, which shows up as a worse independently-computed val_bpb anyway.
"""

from __future__ import annotations

import importlib.util
import math
import time
from pathlib import Path
from types import ModuleType

import torch

# Fixed architecture knobs not exposed to miners or round input -- see input.schema.json
# (only depth / max_seq_len / batch sizing are configurable; these two hold the model's
# width:depth ratio and attention head size constant across every submission and round).
ASPECT_RATIO = 64
HEAD_DIM = 128

# Upstream's own default LR/weight-decay magnitudes (scripts/base_train.py argparse
# defaults). The schedule hook controls the *shape* of the schedule over the run, not
# these base magnitudes -- same split upstream makes between CLI args and closures.
BASE_EMBEDDING_LR = 0.3
BASE_UNEMBEDDING_LR = 0.008
BASE_MATRIX_LR = 0.02
BASE_SCALAR_LR = 0.5
BASE_WEIGHT_DECAY = 0.28
WARMUP_STEPS = 40
WARMDOWN_RATIO = 0.65
FINAL_LR_FRAC = 0.05

# Reference horizon nanochat measured its batch-size scaling law against (d12, see
# upstream lines 271-275) -- kept as a constant here since the proxy pass never trains a
# d12-scale model; this only affects the auto-computed weight_decay_scaled formula.
B_REF = 2**19


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_model(overrides_dir: Path | None):
    if overrides_dir is not None and (overrides_dir / "model.py").exists():
        mod = _load_module(overrides_dir / "model.py", "submission_model")
        return mod.GPT, mod.GPTConfig
    from nanochat.gpt import GPT, GPTConfig  # default: unmodified upstream

    return GPT, GPTConfig


def _resolve_schedule(overrides_dir: Path | None):
    if overrides_dir is not None and (overrides_dir / "schedule.py").exists():
        mod = _load_module(overrides_dir / "schedule.py", "submission_schedule")
        return mod.lr_multiplier, mod.muon_momentum, mod.weight_decay
    from schedule_defaults import lr_multiplier, muon_momentum, weight_decay  # see below

    return lr_multiplier, muon_momentum, weight_decay


def _resolve_train_data_iterator(overrides_dir: Path | None):
    """Overridable -- this is the "data packing/loading" competition surface. Only ever
    used for split="train". See `_val_data_iterator` for why validation data is not
    overridable at all."""
    if overrides_dir is not None and (overrides_dir / "data.py").exists():
        mod = _load_module(overrides_dir / "data.py", "submission_data")
        return mod.data_iterator
    from nanochat.dataloader import tokenizing_distributed_data_loader_with_state_bos_bestfit as data_iterator

    return data_iterator


def _val_data_iterator():
    """NEVER overridable, regardless of EXTRA_FILES. If a miner's `data.py` also
    controlled the validation split, a malicious data_iterator could special-case
    `split == "val"` to hand back degenerate/trivially-predictable batches (e.g. constant
    sequences) and fake an arbitrarily low val_bpb with no relationship to real training
    quality -- the referee must own the ground truth it scores against, same principle as
    `private_data` being referee-only in every other competition (security-checklist.md
    §3: "never send validation criteria... to the player"; here it's an in-process
    boundary instead of a sandbox one, but the same rule applies)."""
    from nanochat.dataloader import tokenizing_distributed_data_loader_with_state_bos_bestfit as data_iterator

    return data_iterator


def _build_config(GPTConfig, vocab_size: int, depth: int, max_seq_len: int, window_pattern: str = "L"):
    base_dim = depth * ASPECT_RATIO
    model_dim = ((base_dim + HEAD_DIM - 1) // HEAD_DIM) * HEAD_DIM
    num_heads = model_dim // HEAD_DIM
    return GPTConfig(
        sequence_len=max_seq_len,
        vocab_size=vocab_size,
        n_layer=depth,
        n_head=num_heads,
        n_kv_head=num_heads,
        n_embd=model_dim,
        window_pattern=window_pattern,
    )


def _referee_evaluate_bpb(model, batches, steps: int, token_bytes, vocab_size: int) -> float:
    """Same bits-per-byte math as `nanochat.loss_eval.evaluate_bpb`, but computed
    independently of the model's own loss path -- see module docstring's "why not
    evaluate_bpb directly" note. We call the model with `targets=None` (upstream's own
    forward() returns raw logits in that case, never a self-computed loss -- verified
    against the pinned commit's gpt.py) and compute cross-entropy against the true `y`
    ourselves, so a submitted model can never influence the number by lying about its own
    loss: it only ever sees `idx` and must actually predict correctly to score well.
    """
    import torch.nn.functional as F

    total_nats = torch.zeros((), dtype=torch.float32, device=model.get_device())
    total_bytes = torch.zeros((), dtype=torch.int64, device=model.get_device())
    batch_iter = iter(batches)
    for _ in range(steps):
        x, y = next(batch_iter)
        logits = model(x, targets=None)
        if not torch.is_tensor(logits) or logits.shape[:2] != x.shape or logits.shape[-1] != vocab_size:
            raise ValueError(
                f"model returned logits of shape {getattr(logits, 'shape', type(logits))}, "
                f"expected ({x.shape[0]}, {x.shape[1]}, {vocab_size})"
            )
        loss2d = F.cross_entropy(logits.view(-1, vocab_size), y.view(-1), ignore_index=-1, reduction="none")
        y_flat = y.view(-1)
        valid = y_flat >= 0
        y_safe = torch.where(valid, y_flat, torch.zeros_like(y_flat))
        num_bytes = torch.where(valid, token_bytes[y_safe], torch.zeros_like(y_flat, dtype=token_bytes.dtype))
        total_nats += (loss2d * (num_bytes > 0)).sum()
        total_bytes += num_bytes.sum()
    total_nats_f = total_nats.item()
    total_bytes_i = total_bytes.item()
    if total_bytes_i == 0 or not math.isfinite(total_nats_f):
        return float("inf")
    return total_nats_f / (math.log(2) * total_bytes_i)


def run_proxy_training(overrides_dir: Path | None, cfg: dict, seed: int, device_type: str = "cpu") -> dict:
    """Run the fixed-step proxy pass and return {val_bpb, tokens_trained, wall_time_s}.

    `cfg` carries the round's input.schema.json fields (depth, max_seq_len,
    device_batch_size, total_batch_size, num_iterations, eval_tokens).
    """
    from nanochat.tokenizer import get_token_bytes, get_tokenizer

    # Determinism as a security property (security-checklist.md §9): same submission +
    # same seed must produce the same score, or a scoring dispute becomes unanswerable.
    # warn_only=True because a submission's own architecture may use an op with no
    # deterministic kernel -- we still want the run to complete and be scored rather than
    # crash outright; nondeterminism from that op is then a submission-visible risk it
    # chose to take, not a referee bug.
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    device = torch.device(device_type)

    GPT, GPTConfig = _resolve_model(overrides_dir)
    lr_multiplier, muon_momentum, weight_decay = _resolve_schedule(overrides_dir)
    train_data_iterator = _resolve_train_data_iterator(overrides_dir)
    val_data_iterator = _val_data_iterator()  # never overridable -- see its own docstring

    tokenizer = get_tokenizer()
    token_bytes = get_token_bytes(device=device)
    vocab_size = tokenizer.get_vocab_size()

    config = _build_config(GPTConfig, vocab_size, cfg["depth"], cfg["max_seq_len"])
    model = GPT(config).to(device)
    model.init_weights()

    num_iterations = cfg["num_iterations"]
    total_batch_size = cfg["total_batch_size"]
    device_batch_size = cfg["device_batch_size"]
    max_seq_len = cfg["max_seq_len"]

    tokens_per_step = device_batch_size * max_seq_len
    assert total_batch_size % tokens_per_step == 0, (
        f"total_batch_size ({total_batch_size}) must be a multiple of "
        f"device_batch_size*max_seq_len ({tokens_per_step})"
    )
    grad_accum_steps = total_batch_size // tokens_per_step

    # Weight-decay correction for the (tiny) training horizon actually used, following
    # upstream's T_epoch-constancy argument (base_train.py lines 296-304).
    target_tokens = total_batch_size * num_iterations
    d_ref = 12 * ASPECT_RATIO * num_iterations  # rough horizon proxy at this tiny scale
    weight_decay_scaled = BASE_WEIGHT_DECAY * math.sqrt(total_batch_size / B_REF) * (max(d_ref, 1) / max(target_tokens, 1))

    optimizer = model.setup_optimizer(
        unembedding_lr=BASE_UNEMBEDDING_LR,
        embedding_lr=BASE_EMBEDDING_LR,
        matrix_lr=BASE_MATRIX_LR,
        weight_decay=weight_decay_scaled,
        scalar_lr=BASE_SCALAR_LR,
    )

    train_loader = train_data_iterator(tokenizer, device_batch_size, max_seq_len, split="train", device=device)
    x, y, _ = next(train_loader)

    t0 = time.monotonic()
    model.train()
    for step in range(num_iterations):
        for _ in range(grad_accum_steps):
            loss = model(x, y)
            (loss / grad_accum_steps).backward()
            x, y, _ = next(train_loader)
        lrm = lr_multiplier(step, num_iterations, {
            "warmup_steps": WARMUP_STEPS, "warmdown_ratio": WARMDOWN_RATIO, "final_lr_frac": FINAL_LR_FRAC,
        })
        momentum = muon_momentum(step, num_iterations, {"warmdown_ratio": WARMDOWN_RATIO})
        wd = weight_decay(step, num_iterations, {}, weight_decay_scaled)
        for group in optimizer.param_groups:
            group["lr"] = group["initial_lr"] * lrm
            if group.get("kind") == "muon":
                group["momentum"] = momentum
                group["weight_decay"] = wd
        optimizer.step()
        model.zero_grad(set_to_none=True)
    wall_time_s = time.monotonic() - t0

    model.eval()
    # _referee_evaluate_bpb wants a (x, y) 2-tuple iterator; the data_iterator contract
    # yields (x, y, state_dict) 3-tuples (matching upstream's *_with_state_* generator,
    # since the training loop above needs the state_dict). Strip it here rather than
    # change the contract -- upstream keeps the same two shapes as two separate functions
    # for exactly this reason.
    def _drop_state(loader):
        for x, y, _ in loader:
            yield x, y

    val_loader = _drop_state(val_data_iterator(tokenizer, device_batch_size, max_seq_len, split="val", device=device))
    eval_steps = max(1, cfg["eval_tokens"] // tokens_per_step)
    val_bpb = _referee_evaluate_bpb(model, val_loader, eval_steps, token_bytes, vocab_size)

    return {
        "val_bpb": float(val_bpb),
        "tokens_trained": target_tokens,
        "wall_time_s": round(wall_time_s, 2),
    }
