# Platform Proposal: Two-Phase Rounds (`resolution_delay_days` / `entrypoints.resolve`)

## Why this competition needs it

`energy_forecast` asks miners to forecast real-world electricity demand —
genuinely useful, and driven by physical/seasonal patterns rather than news
or social sentiment, unlike e.g. BTC-price forecasting. The property that
makes forecasting *automatically* exploit-resistant ("you can't look up the
future") only holds if the target period truly had not occurred anywhere on
the public record when the submission was scored.

Every existing Apex competition scores against a referee-owned generator or
simulator, so a static held-out dataset works fine — the "answer" doesn't
exist anywhere a miner could read it. That doesn't transfer to public data
like EIA-930: a held-out split drawn from already-published history can be
memorized (the input window is a unique key into a sequence anyone can
download), which silently defeats the whole premise. Genuine forecasting
against public data requires the target to be unrealized at scoring time —
which requires scoring to happen *after* the target period ends, not in the
same synchronous pass as today's single-shot round.

## What exists today vs. what's missing

Confirmed by reading the SDK (`src/apex_sdk/gym_v1/referee.py`,
`src/apex_sdk/schema/apex.competition.v1.json`, `src/apex_sdk/dev/cli.py`,
`docs/authoring.md`, `reference/evaluation-design.md`):

- Rounds are single-shot and synchronous: the referee runs `play_game()` once
  and must write `/data/result.json` before the sandbox exits. There is no
  "open now, finalize later" phase anywhere in the schema, docs, or CLI.
- `entrypoints.generate_round` runs once per round but is not internet-exempt
  — egress is blocked "regardless of what your spec says," with no distinct
  trusted tier for it. It cannot pull live data at round-generation time.
- `apex-dev run`'s referee-driven local harness is itself an unimplemented
  follow-up, so there's no existing local pattern for delayed scoring either.

## The proposed extension

Additive on top of `apex.competition.v1` (proposed discriminator
`apex.competition.v2`; existing `v1` competitions are unaffected):

```yaml
defaults:
  resolution_delay_days: 2   # NEW. 0 = today's synchronous behavior, unchanged.

entrypoints:
  resolve:                   # NEW. Optional; only meaningful when resolution_delay_days > 0.
    image: {ref: ..., digest: sha256:...}   # own image, like generate_round/screen
    command: ["python", "/app/resolve.py"]
    output_file: /data/result.json
    timeout_s: 120
```

**Lifecycle**: a round proceeds exactly as today through submission lock and
the `evaluate`/`referee` pass — except when `mode` (a competition-defined
round-input field, not a platform concept) indicates the round can't be fully
scored yet, the referee writes a placeholder result
(`terminal_reason: "pending_resolution"`) with the per-submission prediction
recorded in `metadata` (already a persisted, per-submission field today).
`resolution_delay_days` after round close, the platform runs
`entrypoints.resolve` in its own image, handing it:

1. The round's persisted locked predictions (the `metadata` the referee
   already wrote per submission — no new persistence primitive, just a new
   consumer of an existing one).
2. A **ground-truth feed file**: content-hashed, produced by a data pipeline
   that is *not* a miner-reachable sandbox (in this competition,
   `resolver/fetch_ground_truth.py` on a daily GitHub Actions cron — outside
   any Apex sandbox, with real internet access, exactly like the existing
   image-build/release pipeline already is). Never touches the player
   sandbox; produced independently of any specific round or submission.

`resolve` reads both, computes final `raw_scores`, and overwrites
`result.json` — same shape as today's `GameResult`, just written later.
Everything else (player sandbox, submission format, no-internet,
no-persistence, screening, determinism requirements) is completely
unchanged. The submission itself never sees the future data; it only ever
produces a prediction at lock time from confirmed history. The referee is
still the only thing that ever learns the outcome — it just learns it after
a delay instead of at build time.

## Why this doesn't weaken the platform's security model

- **No new trust surface for miners.** The player sandbox, the no-internet
  policy, and submission isolation are untouched. `entrypoints.resolve` is a
  competition-owned, digest-pinned, cosign-signed image — reviewed the same
  way the referee image is today.
- **No submission-controlled inputs to `resolve`.** The ground-truth feed is
  produced independently of any round or submission; the locked-predictions
  input is exactly the `metadata` the referee already persists today, just
  read later. Neither input is influenced by what a miner submits.
- **Determinism is preserved, just delayed.** `resolve` is a pure function of
  (locked predictions, ground-truth feed) — pin the feed by content hash the
  same way models/datasets are pinned elsewhere, and repeated resolve runs
  produce identical scores.

## Reference implementation in this repo

- `referee/referee.py` — implements the "live" lock-phase behavior against
  today's synchronous contract (writes the placeholder result + locked
  predictions in `metadata`) and a "backtest" mode that scores synchronously
  today, for local dev / baseline training / evaluation sizing.
- `resolver/resolve.py` — the reference `entrypoints.resolve` implementation:
  reads locked predictions + ground-truth feed, computes final scores.
- `resolver/fetch_ground_truth.py` + `.github/workflows/refresh-ground-truth.yml`
  — the daily, non-sandboxed data-refresh pipeline.
- `tools/simulate_two_phase.py` — exercises the full lock → resolve loop
  locally today, standing in for both the missing local harness and the
  missing platform primitive, so the design is validated end to end before
  either lands.

## What we're asking for

1. Review of the `apex.competition.v2` field additions above.
2. Scheduler support for a round that doesn't finalize at `evaluate` time:
   persist per-submission `metadata` (already done) through
   `resolution_delay_days`, then invoke `entrypoints.resolve` and accept its
   `result.json` as final.
3. Guidance on whether the ground-truth feed should be delivered as a mounted
   file (as assumed here) or fetched by `resolve` itself from a
   platform-provisioned, competition-scoped object store — either works with
   this reference implementation with a small adapter in `resolve.py`.

Until this lands, `energy_forecast` can run in `mode: backtest` only (see
README.md) — a real integration test of every other piece (data pipeline,
scoring, baseline, sizing), but not the live, exploit-resistant mode the
competition is designed around.
