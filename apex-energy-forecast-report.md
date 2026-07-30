# Vibe-Coded Competition Report: `energy_forecast`

**One-liner:** A live grid-electricity-demand forecasting competition (miners
submit an ONNX model that predicts next-day US grid demand from 7 days of
history) — chosen specifically because genuine forecasting is exploit-resistant
only if the target hasn't happened yet, which pushed the build past what the
SDK currently supports and into a documented platform-extension proposal
rather than a silent workaround.

| | |
|---|---|
| Base model | Claude Sonnet 5 (`claude-sonnet-5`) — plus incidental Haiku 4.5 use (a background skill/tool call, <0.3% of cost) |
| **True cost (`/usage`)** | **$10.30** total — Sonnet 5: 424 input, 105.4k output, 16.4m cache read, 668.0k cache write tokens ($10.28); Haiku 4.5: 11.6k input, 453 output, 1 web search ($0.02) |
| API duration vs. wall time | 22m 23s of actual API time inside an 11h 36m wall-clock session (session had long idle/thinking gaps between turns, not continuous work) |
| Wall-clock shape | 1 planning phase (multi-round, incl. 2 background research agents + 1 web search) + 1 implementation phase, single session, no re-prompting for bugs (all bugs found and fixed via self-directed local testing) |
| Lines changed | **0 in the SDK itself** (`git diff --stat` on `src/apex_sdk`, `docs/`, `skills/` = clean) — 100% additive under `competitions/energy-forecast/`. Session-wide (`/usage`): **2,018 lines added, 46 removed** |
| New competition code | ~1,660 lines: 1,016 Python (14 files), 437 Markdown (3 files), 167 YAML/JSON (4 files), 2 Dockerfiles |
| Files created | 24 source files (+ 20 synthetic placeholder CSVs + 1 trained baseline.onnx, excluded from the count above as data/artifacts, not code) |
| SDK/design changes required | 1 proposed schema field (`defaults.resolution_delay_days`) + 1 proposed entrypoint (`entrypoints.resolve`) — written up as `PLATFORM_PROPOSAL.md`, not implemented in the SDK (correctly out of scope for a competition author) |
| Bugs hit during self-testing | 2, both in competition code, both self-diagnosed and fixed locally: (1) `target_timestamps` computed by array-slicing past the end of available data in live mode — fixed by generating them from the lock timestamp instead of slicing; (2) held-out ground-truth alignment in the local two-phase simulator — fixed by adding a `holdout_hours` test seam to `sample_instances` |

## Why this competition needed more than "fill in the template"

Every existing example/production competition in this SDK (`humanoid-parkour`,
`hello-world`) scores against a referee-owned generator or simulator: the
"answer" is synthesized fresh from a per-round seed, so a static held-out
pattern is exploit-resistant by construction. That pattern **does not
transfer** to a competition built on real public data (EIA-930 grid demand):
a static held-out split from already-published history can be memorized by a
miner who downloads the same public dataset, silently defeating the "can't
look up the future" property the whole competition idea rests on.

Confirming this, and confirming the SDK has no delayed-scoring primitive to
fix it (round execution is single-shot and synchronous — `Referee.run()`
must write `/data/result.json` before the sandbox exits, `generate_round` is
not internet-exempt, and the local referee-driven harness is an
acknowledged unimplemented follow-up in the SDK's own docs), took real
investigation before any code was written. The instruction to "not let the
rigidity of the SDK get in the way" is what turned this from a routine
template-fill into: build everything that *can* run today (backtest-mode
scoring, the full player/referee/baseline/tooling stack, an honest σ_round
sizing report) **and** write a concrete, scoped extension proposal for the
one piece that can't (`PLATFORM_PROPOSAL.md`), rather than quietly
downgrading the competition's premise to fit the current SDK.

## Fresh-user UX notes (what stood out building this cold)

**Strong:**
- The `gym_v1.Player` / `Referee` base classes are genuinely minimal — `reset`/`act`
  and `play_game` are the entire contract, and the humanoid-parkour example
  was a complete, copy-adaptable reference for every piece (Dockerfile,
  launch.py, referee.py, tools/local_eval.py, tools/measure_variance.py).
  Cloning that shape for a completely different domain (time-series vs.
  physics sim) took no guesswork.
- The `env/` shared-module convention (one source of truth imported by the
  referee, the baseline trainer, and every dev tool) is a good pattern and
  is what made local testing trustworthy — no risk of the baseline being
  scored differently than it was trained.
- `skills/apex-competition-builder/` (SKILL.md + evaluation-design.md +
  security-checklist.md) is unusually thorough for an SDK's design docs —
  the σ_round sizing procedure, the ONNX-first submission-format ladder, and
  the security checklist gave a concrete, checkable process rather than
  vague guidance. Following it is what surfaced the exploit-resistance gap
  in the first place, before any code was written.
- `apex-dev preflight` gives fast, precise, actionable errors (it correctly
  flagged the exact 2 proposed schema fields and 2 placeholder digests, and
  nothing else) — good signal for iterating on a spec.
- The ONNX-only, no-code submission format ladder is a genuinely strong
  security-by-construction idea: there was no Layer-2 screening to design at
  all for this competition, because there's no code in the sandbox to screen.

**Friction / gaps:**
- **No scaffolding command.** There's no `apex-dev new <competition>` or
  cookiecutter-style generator — starting a new competition means manually
  copying and adapting another competition's directory tree by hand (`mkdir`
  + read 6-8 reference files + rewrite). Fine for a second competition once
  you've seen the pattern; a real first-time cold-start would be slower.
- **No local two-sandbox harness**, acknowledged in the SDK's own docs
  (`apex-dev run` "referee-driven local execution is not implemented yet").
  In practice this meant hand-rolling `tools/local_eval.py` (subprocess the
  player, drive it over real HTTP with the real referee class) just to get
  a trustworthy local loop — necessary, reusable, but it's the same gap
  every competition author will independently re-solve until the SDK ships
  it.
- **The spec schema has no extension seam.** `additionalProperties: false`
  everywhere is good for strictness but means there is no way to even
  *draft* a spec that anticipates a needed platform feature — it's an
  all-or-nothing jump to a hypothetical `v2`. A documented "proposal"
  escape hatch (e.g. an `x-proposed` free-form block) would let designers
  express intent without producing a spec that fails validation for reasons
  unrelated to what's actually wrong with it.
- **No delayed/async scoring primitive at all.** This is the fundamental
  finding of this exercise: the SDK is built entirely around
  simulator/generator-style ground truth (referee always knows the answer
  by construction). Any competition whose ground truth is real-world and
  time-delayed (forecasting, predictions resolved by real outcomes, anything
  "can't look up the future" in the literal sense) hits this wall
  immediately and needs new platform machinery, not just a new spec.
- **`generate_round`'s internet policy is a dead end for live-data
  competitions**, stated flatly ("egress is blocked regardless of what your
  spec says") with no documented trusted tier for data-refresh jobs — which
  is fine as a sandbox rule, but the docs don't point authors toward the
  actual answer (an out-of-band, non-sandboxed CI pipeline), so it reads
  like a hard blocker until you think around it.

## Scores (out of 10, fresh-user perspective)

| Dimension | Score | Why |
|---|---|---|
| **Ease of use** | 6/10 | Excellent once you've read 5-6 files and have a reference competition to clone; no scaffolding tool, no local 2-sandbox harness, and every new competition currently re-solves the same "drive the referee over real HTTP locally" problem from scratch. |
| **Completeness** | 5/10 | Fully covers the sandbox-isolation, screening, signing, and sizing story for simulator-style competitions (where it's excellent) — but has a real, load-bearing gap for anything needing real-world/delayed ground truth, which is not a niche case (forecasting, predictions, any live-outcome competition). |
| **SDK expressiveness** | 6/10 | The `gym_v1` contract (`reset`/`act`/`play_game`) is flexible enough to express a completely different domain (time-series forecasting vs. physics locomotion) with no fighting the abstraction — the ceiling is high for anything scoreable synchronously. It hits a hard wall the moment scoring needs to happen *after* round close, because that phase doesn't exist in the schema at all. |
| **Docs quality** | 9/10 | The design-guide skill (goal statement → format ladder → metric → sizing → ops params → security checklist) is the best part of the whole SDK experience — it's what caught the exploit-resistance flaw in the naive approach before any code was written. |
