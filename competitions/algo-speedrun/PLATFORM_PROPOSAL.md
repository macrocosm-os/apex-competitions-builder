# Platform Proposal: `referee.resources` (and, later, native tiered evaluation)

> **Status: `referee.resources` is RESOLVED** -- implemented directly in this repo
> (`src/apex_sdk/schema/apex.competition.v1.json`, `src/apex_sdk/spec.py`, tests in
> `tests/test_spec.py`) rather than left as an external ask, once this competition's
> mainnet-merge goal made the schema gap a blocker rather than a nice-to-have. The design
> below is kept as the record of *why* -- what shipped matches this proposal exactly. The
> native-tiered-evaluation half of this doc (item 3 in "what we're asking for") is
> **still an open, non-blocking ask** -- `algo_speedrun` ships without it via the
> out-of-band `tools/run_deep_eval.py` instead (HANDOFF.md §6).

## Why this competition needs it

`algo_speedrun` asks miners to improve nanochat's training-loop critical path, scored by
actually running a (small, fixed) training pass inside the referee -- see HANDOFF.md §2
for why training has to live in the referee rather than the player. Even the cheap,
every-round proxy pass (a depth-4 model, 20 steps) benefits from a GPU, and the
periodic full-scale deep evaluation (HANDOFF.md §5) needs one outright. Neither is
expressible in the schema today.

## What exists today vs. what's missing

Confirmed by reading `src/apex_sdk/schema/apex.competition.v1.json` and every shipped
competition's `spec.yaml`:

- There is exactly **one** `resources` block in the whole schema
  (`apex.competition.v1.json:52-73`), and by convention (every shipped competition,
  e.g. `research-harness/spec.yaml`) it sizes the **player** sandbox.
- The `referee` block (`apex.competition.v1.json:305-326`) has `protocol`, `image`,
  `timeout_s`, `allow_internet` -- and no `resources` field at all. There is no way to
  declare "the player is 1 CPU / 512Mi and the referee is 8 CPUs / 32Gi / 1 GPU."
- `process_type` (`gpu`) is a single scheduling hint for the whole spec, gated by "the
  platform GPU opt-in pool" -- it says nothing about *which* sandbox gets the GPU.
- Every existing GPU-capable competition, per evaluation-design.md, uses the GPU only on
  the scoring side already -- so this gap likely blocks other competitions too, not just
  this one.

## The proposed extension

Additive on top of `apex.competition.v1` (existing specs, which never set `referee.
resources`, are unaffected by a default):

```yaml
referee:
  protocol: gym_v1
  image: {ref: ..., digest: sha256:...}
  timeout_s: 1800
  allow_internet: false
  resources:              # NEW. Same shape as the existing top-level `resources`.
    cpu_limit: 8
    mem_limit: 32Gi
    gpu_count: 1
```

Semantics: identical validation to the existing `resources` block (`check_resource_ceilings`
in `spec.py`), just scoped to the referee sandbox instead of (or in addition to) the
player. The existing top-level `resources` keeps meaning "the player" unchanged, so no
existing spec needs to change.

## Why this doesn't weaken the platform's security model

- **No new trust surface for miners.** The referee is already the trusted,
  competition-owned scorer; giving it more CPU/memory/GPU changes what it can *do*, not
  who can reach it. The player sandbox -- the one holding untrusted miner bytes -- is
  completely unaffected by this field.
- **Ceilings still apply.** The same stage/prod ceiling logic that bounds the player's
  `resources` today (`spec.py: ENV_CEILINGS`) extends unchanged to the referee's block; a
  GPU-bearing referee still needs the same platform GPU opt-in pool `process_type: gpu`
  already gates.
- **Determinism is unaffected.** This is a scheduling/resourcing change, not a scoring
  change -- it doesn't touch what the referee computes, only what it's allowed to run on.

## What we're asking for

1. Review of the `referee.resources` field addition above (schema + `spec.py` validation).
2. Confirmation of whether a GPU-bearing referee draws from the same opt-in pool as a
   GPU-bearing player, or needs a separate capacity/cost conversation given the training
   workload (minutes, not milliseconds, per job) is qualitatively different from typical
   scoring workloads.
3. Separately, and not blocking on (1)/(2): whether native tiered evaluation (a
   `tiers:` block generalizing the `generate_round`/`resolve` entrypoint pattern -- run
   everyone through a cheap pass every round, promote the top-K to an expensive pass on a
   slower cadence) is worth designing as a first-class scheduler concept. This
   competition ships without it (HANDOFF.md §5: the deep eval runs out-of-band via a
   separate script and referee image, same posture as `energy-forecast`'s
   `PLATFORM_PROPOSAL.md` shipping in `mode: backtest` while its own two-phase-rounds ask
   is reviewed), so this half of the ask is a "when convenient," not a blocker.

Until (1)/(2) land, `algo_speedrun` can develop and validate everything on CPU via
`tools/local_eval.py` (proxy scale is small enough to be CPU-feasible, matching
nanochat's own documented CPU/Macbook smoke-test invocation), but cannot sync a spec that
actually declares GPU on the referee, and therefore cannot go live.
