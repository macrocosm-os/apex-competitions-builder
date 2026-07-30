# Vibe-Coded Competition Report: `otto_product_classification`

A build log and SDK stress test, written from the point of view of a fresh user trying to ship a
competition shape the SDK did not previously support.

## Summary

`otto_product_classification` is a Kaggle-style Apex competition: one fixed tabular dataset split
70/30, miners submit a CSV of class probabilities for the public test features, and a referee
scores them on multiclass log loss against test labels it alone can read. Getting there required
two additive extensions to `apex.competition.v1` — a `csv` submission artifact type and a
`private_data` block for platform-mounted private ground truth — plus two genuine SDK bug fixes in
the `gym_v1` failure path.

## At a glance

| | |
|---|---|
| Base model | `claude-opus-5` (plus $0.0019 of Haiku 4.5 for incidentals) |
| **Cost** | **$34.65**, whole-session and whole-task — the session opened 85 seconds before the request |
| Tokens (billed) | 261.0k output · 38.0M cache-read · 1.0M cache-write · 479 uncached input |
| API time | **58m 49s** (wall 11h 38m — mostly idle waiting on prompts, not work) |
| SDK diff | 15 files, **+759 / −135** |
| New competition | 27 files, **2,467 lines** (excl. the generated 18,560-line `baseline/submission.csv`) |
| Tests | 17 → **119 passing** (+51 SDK, +51 competition), zero new dev dependencies |
| Wall-clock | ~1h35m from "clarify with me" to green, real dataset included |
| Human input | 5 prompts + 3 clarification rounds |
| Dataset | **real Otto**, 61,878 rows → 43,319 train / 18,559 test |
| Declared baseline | **0.473552** log loss (measured) |

## Scores

| Dimension | Score | One-line justification |
|---|---|---|
| **Ease of use** | **7 / 10** | Three ABCs and a spec file is genuinely the whole surface; you can hold it in your head. Points lost to `apex-dev run` not actually running anything, and to two footguns that cost real debugging time. |
| **Completeness** | **5 / 10** | The contract is complete and the docs are unusually honest. The *tooling* is not: no local two-sandbox harness, no dataset helpers, and the one CLI verb that would close the loop exits 3. |
| **SDK expressiveness** | **6 / 10** | The `gym_v1` player/referee split modelled a batched-prediction competition without a fight. But the two things this shape needs most — a data artifact and private scoring data — were both simply absent, and the schema is closed (`additionalProperties: false`), so absent means blocked. |

**Overall: 6 / 10 — a good contract with a thin toolbox.** The design is right; the gap is that
too much of the "author a competition" path is left as an exercise.

---

## What had to change in the SDK

Three of these were planned. Two were discovered by running the thing.

### 1. `submission.artifact_type` had no data option (planned)

The enum was `code | torchscript | onnx` — every option assumes the miner ships *logic*. A table
of predictions is none of them, and because the schema is `additionalProperties: false` there is no
escape hatch: you cannot smuggle a CSV through as `code` without the platform's ASTGuard screener
trying to `ast.parse` it.

Added `csv`, plus eight `screening` knobs for the generic Layer-1 validator (`required_columns`,
`expected_rows`, `id_column`, `value_min`/`value_max`, `row_sum`/`row_sum_tol`, `allow_nan`), and
one `allOf` conditional making the first three mandatory when `artifact_type: csv`. Without them a
csv competition has *no* Layer-1 at all, and every malformed CSV becomes a **referee**-attributed
failure — which silently poisons the competition's health metrics rather than the miner's score.

**Worth noting for the design docs:** `csv` belongs at the *top* of the constrained-format ladder,
above `onnx`. It is the only artifact type with nothing to execute. But it brings a failure mode
none of the others have — the submission *is* the answer key — which is why it needs `private_data`
and why reveal has to be suppressed.

### 2. There was no way to give the referee private data (planned)

Sandboxes have no egress, so a referee cannot fetch its own ground truth. The only existing option
is baking it into the referee image, which means the answer key lives in a layer anyone who can
pull the image can read, and rotating it means republishing.

Added an optional top-level `private_data` block (`uri` / `mount_path` / `sha256` / `read_only`),
plus `check_private_data()` in `spec.py` for the cross-field rules JSON Schema cannot express:
mount uniqueness, path normalisation, reserved locations, and — the important one — **no overlap
with `submission.target_path` in either direction**, so a private mount can never shadow the miner
artifact path.

Both additions are strictly additive: the `$id` and `apex.competition.v1` discriminator are
unchanged, `private_data` is optional and absent from the root `required` array, and hello-world +
humanoid-parkour still preflight clean. That mattered more than it sounds — putting `private_data`
in `required` would have retroactively invalidated every already-synced immutable `(id, version)`
in the private registry.

### 3. `apex-dev run` could not express a private mount (planned)

Added a repeatable `--private-data MOUNT_PATH=HOST_PATH`, which verifies **the same sha256 the
platform verifies**. That is the whole point: a stale local labels file now fails at exit 2 instead
of silently scoring against the wrong answers — a bug class that would otherwise be invisible until
someone compared a local number to a stage number.

### 4. 🐛 A player exception was attributed to the wrong party (found by running it)

`gym_v1/player.py`'s `do_POST` did not wrap the `reset`/`act` dispatch. So when my player correctly
rejected a submission with the wrong row count, the exception escaped the handler,
`BaseHTTPRequestHandler` dropped the connection, and the referee received a raw
`http.client.RemoteDisconnected` — which is not a `PlayerError`, so `play_game` crashed, wrote no
`result.json`, and **the platform would have blamed the referee for a bad submission**: score 0 for
everyone, fault recorded against the competition.

This is the single most consequential thing in this report. The SDK's own docstrings document the
intended behaviour ("Player HTTP error → the referee decides… Referee crash → attributed to the
REFEREE"), and the implementation quietly routed the first case into the second.

Fixed by returning 500 on a player exception (and 400 on a malformed referee request, so the two
stay distinguishable), and by catching `OSError` in `client._post` so *every* transport failure
becomes a `PlayerError`. Six new tests in `tests/test_gym_v1.py` pin it down.

### 5. 🐛 `wait_until_ready` cannot see a dead player (found by running it)

`PlayerClient.wait_until_ready` polls HTTP only. A player that exits on startup — the *normal*
outcome for a rejected submission — costs the full timeout and then reports a misleading "not
ready". On the platform the distinction is moot (both are submission failures), but locally it is
the difference between a 1-second and a 30-second edit/run loop. Worked around in
`tools/local_eval.py` with a `poll()` check; arguably belongs in the SDK.

### 6. Pre-existing issues fixed in passing

- **`_validate_solo_result` encoded a retired contract.** It asserted a top-level
  `{raw_score, eval_time_in_seconds}` that `gym_v1.GameResult` has never serialised. Dead code
  (`cmd_run` exits 3 before reaching it) but actively misleading — and `README.md` published the
  same wrong shape to designers. Both fixed; renamed `_validate_game_result` and tested.
- **`_run_solo` was 76 lines of unreachable code** implementing the retired single-sandbox model
  the codebase explicitly disowns. Deleted.
- **`__version__` had drifted** (`0.1.0` in `__init__.py` vs `0.3.0` in `pyproject.toml`). Now
  derived from package metadata so it cannot diverge again. Bumped to `0.4.0`.

---

## Fresh-user UX notes

### What worked well

- **The player/referee split is the right abstraction and it is small.** Three ABCs —
  `Player.reset/act`, `Referee.play_game`, `PlayerClient` — and that is genuinely all of it. I
  never had to fight the protocol. A batched-prediction competition (5 `/act` calls of 4,096 row
  ids) fell out naturally even though `gym_v1` was clearly designed for step-wise RL.
- **`humanoid-parkour` is an excellent worked example.** Reading one real competition end to end
  taught more than the docs did — especially `env/scoring.py` as "the metric lives in one shared
  module so the referee and the tools cannot diverge", which I copied directly.
- **The failure-attribution doctrine is genuinely good design**, and stated where you need it (the
  `referee.py` module docstring). "Raise and write nothing → blamed on you; return a result → blamed
  on the submission" is a sharp, memorable rule. It is also exactly the rule bug #4 broke.
- **`HANDOFF.md` forces the right thinking.** Its 12-question threat model is what surfaced the
  fatal leakage in the placeholder dataset. A checklist that makes you write down "the strongest
  exploit you know of" is worth more than a linter.
- **`preflight` is fast and its errors are readable.** Sub-second, precise JSON-pointer-ish paths.
- **Docs are honest about their own gaps** — parkour's HANDOFF reports its σ check *failing* and
  argues why it is acceptable, rather than tuning until it passed. That set the tone; I did the same.

### What cost me time

1. **`apex-dev run` doesn't run anything.** It validates and prints a plan, then exits 3. The
   headline verb of the dev CLI cannot execute the thing it describes, so every competition
   reinvents a local harness: parkour has `tools/local_eval.py`, I wrote a near-identical one, and
   the untracked `energy-forecast` has a third. That is the same ~120 lines written three times, and
   it is the single biggest completeness gap.
2. **The `env/` import path is a trap.** Both images `COPY env/ /app/env/` and run with `/app` as
   the script dir, so `import env` works *in the container* and fails everywhere else. My player
   subprocess died instantly with `ModuleNotFoundError: No module named 'env'`, and because of bug
   #5 the symptom was a 30-second timeout with a misleading message. Every competition needs the
   same `sys.path` shim in its tools and its `conftest.py`. A documented convention (or a
   `PYTHONPATH=/app` in the base images) would remove a whole class of first-run confusion.
3. **No dataset story at all.** There is no download, cache, split, or content-hash helper anywhere
   in the SDK — reasonable, since parkour generates its data from a seed, but a dataset competition
   is a large category and I wrote ~300 lines of `prepare_data.py` from scratch. The
   "byte-deterministic writer + committed `MANIFEST.sha256`" pattern is reusable and should probably
   be documented, if not shipped.
4. **Kaggle needs a browser round-trip.** `tools/prepare_data.py` returns HTTP 403 until the
   account accepts the competition rules once, interactively — not the SDK's fault, but it blocks a
   fully automated first run, so the script emits the exact rules URL rather than a bare HTTP error.
   Worth designing for: any customer-brought dataset behind a click-through licence hits this, and a
   competition that cannot bootstrap unattended cannot be CI-tested. Mitigated here with
   `tools/make_synthetic_source.py`, a same-shaped no-credentials stand-in.
5. **Two footguns the schema lets you walk into.** `action="append"` with a `None` default would
   crash the resolver on every spec without the flag (caught by a test I wrote specifically because
   it looked wrong). And `screening` claims in its own description to be "keyed by
   `submission.artifact_type`" while actually being a flat bag with no enforcement — a `csv` spec can
   happily set `min_weight_bytes`. Harmless today; filed as a follow-up.
6. **Sizing guidance doesn't cover fixed datasets.** `evaluation-design.md`'s whole procedure is
   built on σ across seeds. With a fixed test set σ_round is *identically zero*, so parkour's
   `measure_variance.py` prints `σ=0, PASS` — true and useless. I had to derive the right analysis
   (unpaired bootstrap SE vs **paired** SE of the difference, plus a bootstrap separability check)
   and then document it back into the reference. That is real design work the docs should carry.

### Ergonomics wishlist, ranked by value

1. A real referee-driven `apex-dev run` (or bless `local_eval.py` as an SDK-provided harness).
2. `PYTHONPATH=/app` in the base images, or a documented `env/` import convention.
3. `wait_until_ready` should notice a dead process when it owns one.
4. A `reveal_artifact: false` spec field — every prediction-CSV competition will need it (below).
5. A short "fixed-dataset competition" section in `evaluation-design.md` (now added).

---

## Design problems this shape exposes

Two are not implementation gaps; they are structural and need a decision.

**Reveal publishes the answer key.** After `submission_reveal_days` the platform reveals
submissions. For a `csv` artifact on a fixed test set, the winning submission *is* ground truth for
every scored row. A straight copy is harmless — it scores identically and so cannot clear the 1%
bar — but a **blend** of two revealed CSVs reliably beats both on log loss with zero modelling work,
and several revealed CSVs at ≈0.45 collectively pin down most true labels. No `screening` knob can
detect this. I set `submission_reveal_days: 3650` as a stopgap because the schema requires a number
and has no "never". This needs a real `reveal_artifact: false`, decided **before** any CSV
competition activates — and it will be true for every customer dataset, not just this one.

**The 1% takeover rule and a fixed test set are in tension.** σ_round is exactly 0, which is the
best possible news for reproducibility — identical resubmissions score identically forever, and
seed-fishing is structurally impossible rather than merely defended against. But nothing rotates,
so the leaderboard itself becomes the leak: every scored submission is one bit of information about
a test set that never changes. Overfitting pressure accumulates monotonically. The fix is a
scored-but-never-reported holdout slice, which is a *platform* capability nobody has yet.

---

## Limitations of this report

State plainly what is and is not verified.

- **The images were never built.** No Docker build, no cosign signing, so all three digests are
  placeholders. The `COPY env/ /app/env/` layout is verified only by the fact that the same import
  paths work under the local harness.
- **`apex-dev run` was verified only up to exit 3**, because that is all it does.
- **The private ground truth has not been uploaded to R2.** `private/test_labels.csv` exists
  locally with its digest already pinned in `spec.yaml` and `env/labels.py`; the upload must
  reproduce that digest exactly.
- **Cost and token figures come from `/cost`, and they are strictly session-bound and
  task-bound.** Three sibling Claude Code sessions were building other competitions in parallel on
  the same machine, so this was worth verifying rather than assuming. The session transcript opens
  at 07:29:14Z and the competition request lands at 07:30:39Z — 85 seconds later — and the
  transcript carries exactly one session ID, so **$34.65 and the 4,209 changed lines are this task
  and nothing else.** Parallel sessions write separate transcripts and bill separately.
- **The wall-clock figure is misleading on its own.** 11h 38m is real for the session, but API time
  was 58m 49s; the rest is idle time between prompts while the user was away. Roughly 1h 35m of
  that was active build time.
- **One figure from `/usage` is *not* session-bound, and I originally misused it.** The
  "what's contributing to your limits usage" percentages are computed across *all local sessions on
  this machine*, so with four running concurrently they describe the machine, not this build. An
  earlier draft of this report presented "89% of usage was at >150k context", "64% from sessions
  active 8+ hours", and "35% from subagent-heavy sessions" as properties of this competition. They
  are not, and the claims have been removed.
- **A correction to an earlier draft's token numbers.** I first derived tokens by summing `usage`
  fields from the session transcript and got 400.6k output / 66.7M cache-read. That was
  **double-counted**: each API response is written to the transcript roughly twice (150 of 308
  usage-bearing rows in the main transcript were duplicate message IDs), so the raw sum
  approximately doubles the real figure. Deduplicating by message ID gives 172.8k output / 39.1M
  cache-read, which prices to ~$34–40 at Opus 5 rates ($5 in / $25 out / $0.50 cache-read /
  $6.25–10 cache-write depending on TTL) — consistent with the billed $34.65. **`/cost` was right
  and my transcript tally was wrong**; the table above now uses `/cost` exclusively.
- **`import apex_sdk; apex_sdk.__version__` still reports `0.3.0`** in the existing editable
  install until it is reinstalled — the metadata is cached. `pyproject.toml` says `0.4.0`.
- The synthetic stand-in (`tools/make_synthetic_source.py`) is retained as a no-credentials path
  for miners and CI, not because the real data is missing.

### An earlier draft's predictions, checked against the real data

The plan was written before the dataset was obtainable, so its estimates are now falsifiable —
worth recording, because it is the only honest measure of how much of this was guesswork:

| Predicted | Actual | |
|---|---|---|
| 43,319 train / 18,559 test | 43,319 / 18,559 | ✅ exact, all 9 per-class counts too |
| baseline 0.48–0.55 | **0.473552** | ✅ marginally better than the band |
| ρ(per-row) ≈ 0.9 | **0.904** | ✅ |
| `SE_paired` 2–3× better than unpaired | **2.3×** (0.003051 vs 0.006897) | ✅ |
| class prior ≈2.06 | 1.9503 | ⚠️ 5% optimistic |
| small GBM 0.60–0.65 | 0.537174 | ⚠️ 12% pessimistic |

## What *is* verified

- **The real Otto dataset**, downloaded, split, and pinned: upstream sha256
  `11d3618a…4329a3b4` (61,878 rows) → 43,319 train / 18,559 test, stratified, with
  `tools/prepare_data.py --check` confirming the byte-deterministic writer reproduces all three
  derived files' hashes.
- `ruff` + `black` + **119 tests** green, from a starting point of 17.
- `apex-dev preflight` exits 0 on the new spec **and** still on hello-world and humanoid-parkour —
  the schema change is backward compatible.
- The real player subprocess + real referee loop over HTTP: a uniform submission scores exactly
  `2.1972245773362196` (= ln 9), which calibrates the clip, the renormalisation order, and the
  parser in one assertion.
- **All 13 probe variants** on the real data: 4 file-level rejections at startup (`bad_header`,
  `duplicate_id`, `empty_file`, `wrong_width`), 3 row-level gates charged at exactly
  `2.1972 + 34.5388/18559 = 2.1989672` (`non_finite`, `out_of_range`, `row_sum`), 2 row-count
  mismatches → `reset_failed` at the worst finite score 34.5388, and a scored gradient of
  uniform **2.1972** → prior **1.9503** → gbm-small **0.5372** → baseline **0.4736**.
- **Sizing, measured:** σ_round = 0 (bit-identical repeat runs); unpaired bootstrap SE 0.006897
  vs `margin/4` 0.001184 (FAIL, reported honestly); paired SE 0.003051 at ρ = 0.904; separability
  2000/2000 bootstrap resamples.
- Ground-truth failure paths: absent mount and sha256 mismatch both raise `RuntimeError` and write
  no result — the platform-attribution path.
- `--private-data`: happy path prints the mount, a wrong file fails with a sha256 mismatch at exit
  2, and omitting it names the missing mount.
- `tools/prepare_data.py --check` confirms the byte-deterministic writer reproduces all three
  files' hashes.
- **The leakage exploit, measured on the real dataset:** `--variant onehot_answer` builds the
  answer key from the private labels and scores **8.0e-07**, against a baseline of 0.4736 and a
  Kaggle-winning ensemble of ≈0.38. A ~592,000× improvement over the world's best 2015 entry, from
  a `dict` lookup. This is why the competition is configured stage-only at incentive weight 0.

---

## What drove the cost

Read straight off this session's own billed tokens — not from the machine-wide `/usage`
attribution, which four concurrent sessions make useless for a single build:

- **Cache-read was ~146× the output volume** (38.0M vs 261.0k). That single ratio is the whole
  story: **the cost of this task was reading, not writing.** Output tokens came to ~$6.53 of the
  $34.65; cache-read was ~$19.
- **Authoring a competition is intrinsically a long-context task.** You hold the schema, the
  `gym_v1` protocol, a worked example, and your own new files in view at once — and long context
  is expensive even when fully cached. The lever is a competition-authoring context that doesn't
  require reading all of `humanoid-parkour` to learn the conventions.
- **The three subagents were the best-value spend on the page.** One Explore and two Plan agents
  cost ~$2 of deduplicated usage between them, and they are what surfaced the dataset leakage and
  the reveal hole *before* any code was written.

For calibration: **$34.65 and ~1h 35m of active build time produced a complete, tested
competition, a real dataset pipeline, and two genuine SDK bug fixes** — roughly the cost of an
hour of engineer time.

## Recommendation

Land the two schema additions — they are additive, tested, and backward compatible, and
`private_data` is the load-bearing primitive for every "customer brings a dataset" competition.
Land the two `gym_v1` fixes regardless of anything else in this report; bug #4 misattributes
submission failures to the referee today, for every existing competition, not just this one.

Treat `otto_product_classification` itself as the reference implementation and integration test,
not a live competition: its placeholder dataset's labels are public and the exploit is measured
above. Everything else in the directory transfers verbatim to a dataset whose labels were never
published.

The blocking platform work is listed in `HANDOFF.md` §7 — a Layer-1 CSV screener and an R2
fetch/verify/mount stage in the worker are prerequisites, and both have longer lead times than any
of the SDK work here.
