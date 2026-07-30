# Economic sustainability

Two very different cost profiles, matching the two-tier eval design (HANDOFF.md §6): the
per-round proxy pass is cheap and scales with submission volume; the periodic deep eval
is expensive and scales with a chosen, bounded K and cadence instead. Numbers below are
grounded in measurements actually taken in this repo (baseline/PROVENANCE.md) plus public
GPU spot pricing -- marked where they're an estimate rather than a measurement.

## Proxy pass: cost scales with submission volume, and is cheap

Measured (`baseline/PROVENANCE.md`): 3.4-5.3s wall-clock on CPU for the default proxy
config (depth=4, num_iterations=20, ~10K tokens trained). `spec.yaml` declares
`referee.resources.gpu_count: 1` for the real deployment -- a GPU run of a model this
tiny is dominated by fixed overhead (process startup, tokenizer load, optimizer setup),
not compute, so real wall-clock is unlikely to drop below ~2-3s even with a GPU; this
doc uses **10s per submission** as a conservative all-in estimate (training + submission
fetch + AST screen + container overhead), following evaluation-design.md's own
methodology for sizing eval cost against volume.

| submissions/day | referee-seconds/day | GPU-hours/day (1x H100-class) | rough $/day @ $2.50/GPU-hr |
|-----------------:|---------------------:|-------------------------------:|-----------------------------:|
| 50               | 500s                 | 0.14                            | $0.35                        |
| 200 (evaluation-design.md's own reference volume) | 2,000s | 0.56 | $1.39 |
| 1,000            | 10,000s               | 2.8                             | $6.94                        |

Even at high volume, the proxy pass alone is not the cost concern -- it's the same order
of magnitude as any other CPU-scale competition in this repo. This holds *because* the
proxy config caps depth<=8 and num_iterations<=200 (input.schema.json) -- if those caps
are ever loosened, re-run this table.

## Deep eval: the real cost driver, and the reason it's bounded by K and cadence, not volume

nanochat's real speedrun scale needs "hours on 8xH100" (the framing this whole
competition is built around) -- independent of how many submissions exist, only of how
many get promoted (`top_k` in `tools/run_deep_eval.py`) and how often (weekly, by
default). Using ~4 hours wall-clock for a full run at real scale (nanochat's own README
describes comparable multi-hour runs for full training+SFT pipelines; treat this as an
estimate pending an actual full-scale run, not a measurement this repo has taken) and
$2-3/GPU-hour spot pricing for H100-class instances (2026 public spot rates, e.g.
Lambda/RunPod-class providers):

    cost per deep-eval run  = 8 GPUs x 4 hours x ~$2.50/GPU-hour = ~$80
    cost per week (K submissions promoted, cadence = weekly)  = K x $80

| top_k | $/week | $/month |
|------:|-------:|--------:|
| 4     | $320   | ~$1,280 |
| 8 (HANDOFF.md's example) | $640 | ~$2,560 |
| 16    | $1,280 | ~$5,120 |

**This is the number that needs sign-off before launch, not the proxy pass.** `top_k` and
cadence in `tools/run_deep_eval.py` are the two knobs to tune against whatever budget is
approved -- lowering cadence to bi-weekly halves the run rate at the same K; lowering K
directly scales it. Unlike the proxy pass, this cost does NOT grow with submission
volume (only the top-K get promoted, regardless of how many total submissions exist),
so it's a fixed, plannable operating cost rather than a volume risk.

## Submission fee: sized against the proxy pass, not the deep eval

Per the platform's existing convention (evaluation-design.md), submission fees run
~$0.70-$1.00 in TAO per submission, sized to exceed marginal eval cost and discourage
low-effort resubmission-fishing. At ~10s of proxy compute (~$0.0003-0.0007 marginal cost
per the table above), the existing fee convention is already 1,000x+ the marginal proxy
cost -- more than sufficient for this competition's proxy tier without any
competition-specific adjustment. The deep-eval cost is NOT funded by submission fees (it
would need to be ~$80/submission at K=1 promotion odds to break even, an unreasonable
per-submission fee) -- it's a centrally-budgeted operating cost, same as any other fixed
infrastructure spend, sized by `top_k`/cadence above.

## Anti-spam / anti-resubmission-fishing, specific to this competition's determinism

Unlike prediction-market-style competitions where a leaked seed could regenerate hidden
future data, this competition's round SEED only affects `torch.manual_seed` (model
init + RNG state) -- it never parameterizes a secret generator, so there's no seed-fishing
angle to close here at all: `check_base_model`-style seed leakage concerns
(security-checklist.md) don't apply, because there's no hidden data behind the seed to
begin with. **Determinism means identical resubmissions score identically** (verified:
`torch.use_deterministic_algorithms` in train_runner.py), which is itself the anti-copy
lever combined with `submission_reveal_days: 14` (spec.yaml) -- a miner cannot improve
their score by resubmitting the same code, only by an actual training-loop change, so
the existing per-submission fee's anti-spam role (discourage volume, not discourage
resubmission specifically) is the only one this competition needs.

## What's still an estimate, not a measurement

- The 4-hour/8xH100 deep-eval run time is a stated assumption pending an actual
  full-scale run through `tools/run_deep_eval.py` against real infra.
- GPU spot pricing ($2-3/hour) moves with market conditions; re-check before committing
  to a `top_k`/cadence budget.
- The 10s/submission proxy estimate is conservative (measured CPU wall-clock was
  3.4-5.3s); real GPU + container overhead numbers should replace this once the referee
  image is actually built and run (see DOCKER_BUILD_NOTES.md).
