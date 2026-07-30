# Provenance

## Vendored nanochat snapshot

- Upstream: https://github.com/karpathy/nanochat
- Pinned commit: `92d63d4e8bb4df75c3b71618f31ddde2378b2bcd` (`master` as of 2026-07-29)
- Commit archive sha256: `aa9955ca5ba3f64792494706f8888bb9d1e43a57bdda371435e58e02a85eb8c2`
  (`https://github.com/karpathy/nanochat/archive/92d63d4e8bb4df75c3b71618f31ddde2378b2bcd.tar.gz`)
- Fetched at referee **image build time** (see `referee/Dockerfile`), verified against the
  sha256 above before extraction, and never fetched at eval time -- the referee sandbox
  has no egress (`spec.yaml: referee.allow_internet: false`). Changing the pinned commit
  is a `spec.yaml` `version` bump, same as any other scoring change (security-checklist.md
  §9).
- Trimmed to the training-loop critical path only: `nanochat/gpt.py`, `nanochat/optim.py`
  (Muon, used inside `GPT.setup_optimizer`), `nanochat/dataloader.py`, `nanochat/dataset.py`,
  `nanochat/tokenizer.py`, `nanochat/common.py`, `nanochat/loss_eval.py`, plus
  `scripts/tok_train.py` (run once at referee image BUILD time, not carried at runtime --
  see below). Dropped entirely: chat SFT/RL (`scripts/chat_*.py`), and the full CORE
  benchmark suite (`tasks/`, `scripts/base_eval.py`) -- the proxy eval scores validation
  bpb only (see HANDOFF.md §6); CORE-style scoring is reserved for the out-of-band deep
  eval (`tools/run_deep_eval.py`), which can shell out to nanochat's own
  `scripts/base_train.py` and `scripts/base_eval.py` unmodified at full scale.

## Tokenizer and data: baked into the referee image at build time, not fetched at eval time

The referee sandbox has no egress at eval time (`spec.yaml: referee.allow_internet:
false`), so `get_tokenizer()` and the dataloader must find an already-trained tokenizer
and real pretraining data shards already on disk -- neither can be downloaded or trained
on demand during a round. `referee/Dockerfile` pins and bakes both in at build time:

- **Data shards**: 1 train shard (`shard_00000.parquet`) + the always-included val shard
  (`shard_06542.parquet`) from `karpathy/climbmix-400b-shuffle` on HuggingFace (upstream's
  real pretraining corpus, not a synthetic stand-in), matching upstream's own
  `python -m nanochat.dataset -n 1` convention. ~92MB each, pinned by content sha256
  (`shard_00000`: `054ddbd98abf30d773c54de578fc9d579bafeb6c14e04e97bd36aa90e825bf9b`;
  `shard_06542`: `769fe59d108dfd2cfa186c63173b83fbfb90a7adb3519519ba6eaa6ca9889f94`),
  verified before the image build proceeds.
- **Tokenizer**: trained once at build time via `python -m scripts.tok_train --max-chars
  5000000` against the pinned train shard -- a real rustbpe BPE tokenizer (vocab_size
  32,768, upstream's default), not mocked. `--max-chars` is reduced from upstream's 2B
  default because this is a proxy-scale competition (input.schema.json caps depth<=8);
  the *quality* of the tokenizer doesn't change what's being measured (the training loop),
  only its granularity, and 5M chars trains in under a second.

## Measuring `baseline_raw_score` -- DONE, with real infra, not mocks

Measured by actually downloading both pinned shards, training the real tokenizer exactly
as above, and running `baseline/submission.py` (empty `EXTRA_FILES`, i.e. zero
training-loop changes) through `train_runner.run_proxy_training` with
`fixtures/input.json`'s default config (depth=4, max_seq_len=512, num_iterations=20,
total_batch_size=512) on CPU, across 5 seeds:

| seed | val_bpb | wall_time_s |
|------|---------|-------------|
| 0    | 2.5870  | 5.26        |
| 1    | 2.6508  | 3.53        |
| 2    | 2.5178  | 3.40        |
| 3    | 2.6174  | 3.40        |
| 4    | 2.5136  | 3.54        |

**mean = 2.5773, stdev = 0.0606, n = 5** -- recorded in `spec.yaml`'s
`defaults.baseline_raw_score`. σ/mean ≈ 2.4%, comparable in relative scale to other
competitions' measured round-to-round variance in this repo (e.g. research-harness's
2.9% at n=64) despite a much smaller n here -- worth re-measuring with more seeds before
this competition actually launches, but not zero-effort placeholder data.

Reproduction (matches what `referee/Dockerfile` bakes into the image):
```bash
pip install torch pyarrow numpy requests filelock kernels psutil rustbpe tiktoken
NANOCHAT_BASE_DIR=/tmp/nanochat_cache python -m nanochat.dataset -n 1
NANOCHAT_BASE_DIR=/tmp/nanochat_cache python -m scripts.tok_train --max-chars 5000000
NANOCHAT_BASE_DIR=/tmp/nanochat_cache python tools/local_eval.py \
    --submission baseline/submission.py --input fixtures/input.json --seed 0
```

## `baseline/schedule.py` is a mechanical extraction, not a design choice

Upstream's `scripts/base_train.py` (pinned commit above, lines 360-386) defines the LR
multiplier, Muon momentum, and weight-decay schedules as three closures inside the
training script, over `args`/`num_iterations` captured from the enclosing scope -- not an
importable module. `baseline/schedule.py` is a literal transcription of those three
functions' formulas into standalone, parameterized functions; nothing about the schedule
itself changed. This is what makes the schedule an overridable hook at all (see
`baseline/schedule.py`'s module docstring).
