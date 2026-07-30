# algo_speedrun — designer / platform handoff

## 1. What it is

A nanochat-style (karpathy/nanochat) competition: miners improve the training-loop
critical path -- model architecture + optimizer construction (one hook, since
`GPT.setup_optimizer` is a method of the model in upstream nanochat), the LR/momentum/
weight-decay schedule, and training-split data packing -- and are scored on validation
bits-per-byte after a fixed, short training run. `lower_is_better: true`.

## 2. The design decision everything rests on: referee owns the trainer

Generalizes research-harness's "referee owns the model" invariant. There, the miner's
harness runs in the player sandbox and only ever talks to the frozen model through the
referee's meter. Here, GPU training has to happen where the GPU is, and doctrine keeps
GPU off the player sandbox (evaluation-design.md: "8 of 9 production competitions are
CPU-only end-to-end; the one GPU competition uses GPU only on the scoring side"). So the
inversion: the **player never trains anything** -- it holds the miner's screened
`submission.py` and returns its raw text over one gym_v1 `/act` call (`player/launch.py`).
The **referee** materializes that submission's `EXTRA_FILES` into a scratch copy of its
own pinned nanochat checkout and runs the actual training (`referee/referee.py`,
`referee/train_runner.py`).

This means the miner's code executes *inside the referee's own process*, not behind an
HTTP boundary the way research-harness's harness does. That's a real deviation from the
base `Referee` class's failure doctrine (`src/apex_sdk/gym_v1/referee.py`: "let
unexpected exceptions propagate so the platform blames the referee") -- a bad submission
(shape error, NaN, unsupported op, or a hang) has to be attributed to the *submission*,
not treated as a referee crash, so `referee.py` deliberately catches broadly around
exec+train and runs training under an internal wall-clock watchdog. See §8 for the full
threat model this drove and its module docstring for the mechanics.

## 3. Why one file (`artifact_type: code`, not a new bundle artifact type)

The schema allows exactly one submission artifact at one `target_path`
(`apex.competition.v1.json`) -- no tar/zip/repo artifact type exists, and asking for one
is an uncertain-timeline platform ask. A training-loop change is naturally multi-file, so
`submission.py` carries an `EXTRA_FILES: dict[str, str]` map that the referee
re-materializes into real files before importing (per security-checklist.md §7: "write
down why a more constrained format couldn't express the solution space" -- this does
express it, just via one file containing many). The cost: the platform's Layer-1
ASTGuard only ever inspects `target_path`'s literal bytes, so it never sees inside
`EXTRA_FILES`'s string values. `referee/screen.py` re-implements the same tripwire
locally (with a materially larger forbidden list than the platform's default, since this
competition's execution model is unlike anything else on the platform -- see §8) and is
applied to every virtual file before it's written to disk or imported. Covered by
`tests/test_screen.py`.

## 4. Actual dependency footprint (verified, not assumed)

Earlier drafts of `referee/Dockerfile` assumed torch+pyarrow were the only third-party
deps the trimmed nanochat surface needed. That was wrong -- verified by actually
installing and importing `nanochat.gpt`/`dataloader`/`tokenizer`/`loss_eval`/`common`
against the pinned commit: `nanochat/dataset.py` (pulled in transitively by
`dataloader.py`) needs `requests`, `common.py` needs `numpy` + `filelock`, `tokenizer.py`
needs `rustbpe` + `tiktoken`. The full list now matches upstream's own `pyproject.toml`
minus `wandb` (only the dropped logging path in upstream `base_train.py` needs it --
`train_runner.py` never imports it).

## 5. Why nanochat is vendored at build time, not committed to this repo

security-checklist.md §4: "if the evaluation needs external resources, bake them into the
referee image or its data -- pinned and content-hashed." `referee/Dockerfile` fetches
nanochat's pinned commit archive over the network **at image build time** (not at eval
time -- the running sandbox still has no egress, `spec.yaml: referee.allow_internet:
false`) and verifies it against a recorded sha256 before extracting. See
`baseline/PROVENANCE.md` for the exact commit and hash. This keeps thousands of lines of
upstream source out of this repo's git history while still being fully pinned and
reproducible -- a Docker build already fetches its base image over the network the same
way; nanochat is just one more pinned dependency, not a live fork.

`baseline/schedule.py` and `referee/schedule_defaults.py` are the one place this repo
holds logic that started life as upstream code: nanochat's LR/momentum/weight-decay
schedules are closures inline in `scripts/base_train.py`, not an importable module, so
making them an overridable hook required a mechanical (non-algorithmic) extraction into
standalone functions. See `baseline/PROVENANCE.md`.

## 6. Cheap proxy every round, deep eval weekly, out-of-band

nanochat's real speedrun scale needs hours on 8xH100 -- running that per submission per
round is unbounded compute spend, and the schema's `timeout_s` ceiling (max 7200s) and
the evaluation-design cost doctrine (20-minute hard ceiling) rule it out anyway.

- **Every round** (`referee/train_runner.py`): a fixed, tiny proxy pass -- depth-4 model,
  20 steps, CPU-feasible (matches nanochat's own documented "CPU/Macbook" smoke-test
  scale in `scripts/base_train.py`'s module docstring) -- scored on val bpb. This is what
  `spec.yaml`'s `defaults.*` actually governs and is fully expressible in today's schema,
  now that `referee.resources` exists (§7).
- **Weekly, out-of-band, NOT part of the round lifecycle**: `tools/run_deep_eval.py`
  takes the top-K submissions by cumulative proxy score and runs each through nanochat's
  own unmodified `scripts/base_train.py` + `scripts/base_eval.py` at real scale on rented
  GPU infra, producing a periodic leaderboard/bonus-weight adjustment. Deliberately kept
  outside `spec.yaml` so the competition ships without waiting on a native tiered-eval
  scheduler primitive, which still does not exist today (checked: no staged/tiered eval
  anywhere in the schema, docs, or any shipped competition) -- see `ECONOMICS.md` for the
  cost model this is sized against.

## 7. `referee.resources` -- implemented, not just proposed

Earlier drafts of this competition treated the missing `referee.resources` schema field
as an external platform blocker and shipped a `PLATFORM_PROPOSAL.md` requesting it. Given
the mainnet-merge goal, it's now implemented directly in this repo:
`src/apex_sdk/schema/apex.competition.v1.json` extracts the player's `resources` shape
into `$defs/resources` and adds an optional `referee.resources` property using the same
`$def`; `src/apex_sdk/spec.py`'s `check_resource_ceilings` validates both blocks
independently (`_check_resources_block`, reused for `resources` and `referee.resources`).
Covered by `tests/test_spec.py::test_referee_resources_*`. `spec.yaml` now declares
`referee.resources: {cpu_limit: 4, mem_limit: 1Gi, gpu_count: 1}` -- sized for the cheap
proxy pass only; this spec validates on `env=prod` (has a GPU pool) and correctly fails
on `env=stage` (no GPU pool, and the referee's cpu_limit exceeds stage's ceiling anyway),
which is intentional: this competition cannot run in a CPU-only environment.
`PLATFORM_PROPOSAL.md` is kept as a record of the original ask, marked resolved.

## 8. Adversarial threat model

Executing miner code directly inside the referee's own process (§2) is a materially
different trust boundary than every other competition in this repo, where the referee
only ever *observes* a player's HTTP responses. Threat-modeling that boundary found four
real issues, each verified against actually-running code (not just reasoned about) before
being called fixed -- see the exact reproduction commands in `tests/test_screen.py` and
`tests/test_train_runner.py`.

1. **Arbitrary file write via `EXTRA_FILES` paths.** The original `referee.py` did
   `scratch_path / rel_path` directly. Pathlib's `/` operator silently discards the left
   operand when the right is absolute -- `Path("/tmp/x") / "/etc/passwd" ==
   Path("/etc/passwd")` -- so an `EXTRA_FILES` key of `"/etc/passwd"` (or any absolute
   path, or a `../../`-prefixed relative one) would have written outside the scratch
   directory entirely, anywhere the referee process has filesystem permission,
   potentially overwriting `referee.py`/`train_runner.py` themselves on a running
   container. Fixed in `screen.py::materialize_extra_files`, which validates every path
   is relative with no `..`/empty components and resolves inside the scratch directory
   before anything touches disk. Verified: an absolute-path and a `..`-traversal
   `EXTRA_FILES` entry are both now rejected with `ScreenViolation` before any write.

2. **Miner-controlled validation data (`data.py` covering both splits).** The original
   `data_iterator` override applied to both `split="train"` and `split="val"`. Since the
   override is arbitrary code, a submission's `data_iterator` could special-case
   `split == "val"` to hand back degenerate, trivially-predictable batches (e.g. constant
   sequences) and fake an arbitrarily low `val_bpb` with zero relationship to real
   training quality. Fixed by making the validation split **never** overridable
   (`train_runner.py::_val_data_iterator`, always the referee's own default loader,
   regardless of `EXTRA_FILES`) -- same principle as `private_data` being referee-only
   everywhere else in this SDK. Verified end-to-end: a submission whose `data_iterator`
   attempts exactly this cheat scores identically to a submission with no override at
   all, proving the cheat path is unreachable, not just theoretically blocked.

3. **The model reporting its own loss as the score.** `nanochat.loss_eval.evaluate_bpb`
   (upstream's own scoring function) trusts `model(x, y, loss_reduction='none')` -- a
   fully miner-controlled `forward()` -- to honestly compute and return its own loss. A
   malicious model could return an arbitrary tensor disconnected from its actual
   predictions. Fixed with `train_runner.py::_referee_evaluate_bpb`, which calls the
   model with `targets=None` (upstream's own `forward()` returns raw logits in that case,
   confirmed by reading the pinned commit's `gpt.py`) and computes cross-entropy against
   the true `y` independently in the referee -- the model never even receives the
   validation targets, let alone reports a loss on them. Training loss (`model(x, y)`
   inside the training loop) is left as the model's own computation on purpose: if a
   miner's model lies there, it only sabotages its own gradients, which then shows up as
   a *worse* independently-computed `val_bpb`, not a better one. Verified two ways: (a) a
   model whose `forward()` returns a disconnected constant loss during training crashes
   cleanly in the optimizer (no valid gradients) rather than silently gaming anything;
   (b) a model whose *graph-connected* fake training loss zeroes its own gradients still
   scores an honest (untrained-model) `val_bpb`, not an artificially low one.

4. **Hangs read as referee crashes, not submission failures.** A submission with an
   infinite loop or pathological `forward()` would previously run out `referee.
   timeout_s` and get killed by the platform -- which, per `Referee.run()`'s own
   doctrine, means "no `result.json`, platform scores 0 for everyone, blames the
   referee," exactly backwards for a hang the *submission* caused.
   `referee.py::_run_with_deadline` runs training on a daemon thread with its own
   `TRAIN_WALLCLOCK_BUDGET_S` (300s -- generous for the proxy scale, far below the 1800s
   container timeout) and converts a still-running thread into a scored,
   submission-attributed `training_timeout` result; the daemon thread never blocks
   process exit even if the hang never resolves. Verified: a submission with a
   `time.sleep(999)` in its schedule override returns `terminal_reason="training_timeout"`
   well before the container-level timeout would ever fire.

Additional hardening, not tied to a single specific exploit but standard practice for
code that executes fully miner-controlled logic in-process (`screen.py`):
`FORBIDDEN_MODULES` extended to `threading`/`asyncio`/`sys`/`importlib`/`pickle`/
`marshal`/`shelve`/`signal`/`mmap`/`resource`/`pty`/`code`/`codeop` (beyond the base
network/subprocess set); `torch.load`/`torch.hub` calls blocked (unpickling with nothing
legitimate to load in this contract); `os.environ` attribute *access* blocked, not just
calls; dunder method *definitions* (`__reduce__`, `__getattr__`, etc.), not just
accesses, blocked. `torch.use_deterministic_algorithms(True, warn_only=True)` added
alongside the existing `torch.manual_seed` so scores stay disputable
(security-checklist.md §9) -- `warn_only` because a submission's own architecture might
legitimately use an op with no deterministic kernel, and the run should still complete
and be scored rather than crash on a submission-chosen risk.

What adversarial review did **not** find a way to fully close, and is left as a residual,
named risk rather than silently ignored: a submission's `model.py`/`schedule.py`/
`data.py` (train split) can still legitimately consume the referee's full CPU/GPU/memory
ceiling for the duration of `TRAIN_WALLCLOCK_BUDGET_S` (e.g. an inefficient but
"legal" op that isn't AST-forbidden) -- this is bounded by `referee.resources` (§7) and
the watchdog (item 4), not eliminated, exactly like every other competition's CPU/memory
ceilings bound rather than eliminate a wasteful-but-legal submission.

## 9. Simplifications in `train_runner.py` vs. upstream `base_train.py`

Dropped, all orthogonal to scoring a training-loop change at proxy scale: DDP/multi-GPU,
FP8 training, `torch.compile`, meta-device init (skipped since the proxy model is tiny),
checkpoint save/resume, wandb logging, CORE-benchmark evaluation, sampling. Kept: the
scaling-law-derived weight-decay correction and the training step body. Val-bpb
evaluation is *not* kept as-is -- see §8 item 3 for why it was deliberately reimplemented
rather than reused. If the deep-eval path (§6) shells out to real `scripts/base_train.py`
unmodified, these simplifications never need to be "un-simplified" -- they only ever
applied to the cheap pass.

## 10. Not done / needs a maintainer

- **`baseline_raw_score` measurement**: DONE, see `baseline/PROVENANCE.md` -- measured
  against real downloaded data and a real trained tokenizer, not mocks.
- **Docker builds**: DONE, see `DOCKER_BUILD_NOTES.md` -- both images were actually built
  and run (not just reasoned about), which found and fixed three real bugs (missing
  `curl`, missing `g++` needed at training time by nanochat's own optimizer, and this
  verification machine's Docker disk being too small for a real CUDA `torch` install --
  worked around locally with a CPU-only diagnostic substitution, documented there).
- **Image digests are placeholders** (`spec.yaml`, `sha256:000...0`) until this
  competition repo cuts a signed release, same as every other competition at this stage --
  this is an external action (cosign signing + registry push), not something this repo's
  code can produce on its own.
- **`referee/train_runner.py`'s weight-decay-correction reference horizon (`d_ref`) is a
  rough proxy**, not upstream's actual d12 measurement (upstream's constant assumes a
  specific reference model/batch size measured empirically; this competition never trains
  a d12 model). Worth revisiting now that `baseline_raw_score` is measured and this
  formula's effect on it is visible.
- **GPU execution was never exercised** -- every real run in this handoff (CPU
  measurement in PROVENANCE.md, in-container run in DOCKER_BUILD_NOTES.md) ran on CPU;
  this verification environment has no GPU passthrough to Docker.
- **Platform spec sync, cosign signing, and registry push are external actions** this
  repo cannot perform regardless of code completeness -- see the final readiness report
  for the full list of what Macrocosmos still needs to do.
