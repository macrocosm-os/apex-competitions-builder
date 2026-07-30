# Vibe-Coding Report: `humanoid_parkour`

**Competition summary:** Miners submit a single ONNX locomotion policy that drives a MuJoCo
humanoid through procedurally generated 20 m hurdle courses (easy/medium/hard tiers, fresh
courses every round from the platform seed); raw score = mean over 120 courses, rewarding
completion first and speed second. Fastest reliable runner leads the board.

Repo: https://github.com/macrocosm-os/apex-competition-humanoid-parkour @ `v0.1.1` ·
Onboarding: [issue #11](https://github.com/macrocosm-os/apex-competitions-builder/issues/11) ·
Review PR: [#10](https://github.com/macrocosm-os/apex-competitions-builder/pull/10)

## The numbers

| Metric | Value |
|---|---|
| Claude model | `claude-fable-5` (Claude Code CLI, single session; negligible haiku for internals) |
| Claude tokens | **~50M processed** (from `/cost`): 198.3K output, 1.4K uncached input, 1.8M cache writes, **48.3M cache reads** — cache reads dominate long agentic sessions (89% of usage was at >150K context) |
| Claude cost | **\$93.44** (from `/cost`) ≈ \$48 cache reads + \$36 cache writes (1h TTL, 2×) + $10 output |
| Session time | **1h 5m of API time** spread over ~30h wall clock (training ran ~9.5h of that; the rest was monitoring wakeups) |
| Code churn | 2,211 lines added, 165 removed (session-wide, incl. report + session tooling) |
| Idea → passing preflight + full local eval loop | **~2 h** wall clock |
| Idea → signed images, tagged release, onboarding issue filed | **~6 h** wall clock (incl. 15M-step baseline training) |
| Competition repo size | **1,367 LOC** total; **798 LOC** of Python (env + player + referee + tools + baseline recipe) |
| Session-side tooling (not shipped) | ~611 LOC (overnight trainer, consolidation, video renderer, parallel variance runner) |
| Commits to ship v0.1.1 | 4 |
| **SDK source changes required** | **0** |
| Baseline | PPO, ~110M env-steps (8 h on M3 Max laptop, CPU only) → raw 0.6957, completes ~18% of courses |

session: `claude --resume 356443d1-4634-4a4f-9475-d671996ffea8`

## SDK/design changes needed to achieve the goal

**None to the SDK itself** — the entire competition fit the existing `apex.competition.v1`
contract. That is the headline: a physics-sim RL competition, which the schema was not
specifically designed for, expressed cleanly as `solo` + `gym_v1` + `artifact_type: onnx`
with the referee owning MuJoCo. Design adaptations that were needed on *my* side:

1. **Hand-rolled the local eval harness.** `apex-dev run` validates and prints the plan but
   doesn't execute the player+referee pair (exits 3 by design). I wrote a ~90-line
   two-process harness (`tools/local_eval.py`) that runs the real `Referee.play_game()`
   against the real player HTTP server. Every designer will need this; it should be the
   SDK's job.
2. **Worked around the hard-coded `/data/result.json`.** `RESULT_PATH` in the SDK isn't
   configurable, and `/data` isn't writable on a dev Mac — the harness above calls
   `play_game()` directly instead of `Referee.run()` to dodge it.
3. **Built base images from a pinned SDK checkout in CI.** `apex-player-base` /
   `apex-referee-base` aren't published on ghcr, so the release workflow clones the SDK at
   a pinned SHA and builds them before building competition images (~2 min overhead per
   release, plus supply-chain surface the platform could remove by publishing signed bases).
4. **Redesigned the metric around the 1% takeover rule.** "Fastest time" (the natural
   framing) gives no gradient before anyone finishes and breaks `lower_is_better` scoring
   for non-finishers; the shipped metric (completion ⇒ 1 + time bonus, else progress
   fraction) is monotone and always comparable. The skill docs pushed me here early — good.
5. **Chicken-and-egg on tag-signed digests.** The spec must pin digests of images signed
   "on the released tag", but the digests only exist after the tag's CI runs. Resolved by
   building on the tag, then re-pointing the tag at the digest-pin commit. Workable, ugly;
   a documented convention (or spec-level `digest: pending` + registry-side resolution)
   would remove a real papercut.

## What a fresh user should know

**Where the SDK is genuinely strong:**

- `docs/authoring.md` + `examples/hello-world` + the `apex-competition-builder` skill
  (design order, security checklist, evaluation-sizing procedure, HANDOFF template) is the
  best-documented "build a competition" path I've used. The threat-model questionnaire
  forced real design fixes *before* code (out-of-bounds gate, seed-derivation one-way-ness,
  typed failures).
- The gym_v1 contract is tiny (Player: `reset`/`act`; Referee: `play_game`) and stdlib-only.
  Total integration code for a full MuJoCo competition: ~200 lines across player + referee.
- `apex-dev preflight` catches real mistakes (digest format, resource ceilings, schema
  drift) in <1 s. Spec-passes-preflight ⇒ platform-accepts is a great invariant.
- Player/referee sandbox separation made the security story almost free: ground truth
  simply lives where the submission can't be.

**Where you'll hit friction (in order of pain):**

1. **No runnable local loop out of the box** (see above) — the #1 gap. Everything else
   about the DX assumes fast iteration, and this is the step that gates it.
2. **The σ_round ≤ ¼-margin sizing criterion can be unsatisfiable** for progress-fraction
   metrics (measured: σ 0.033 vs bound 0.0017; closing it needs N≈9,000 courses). The
   within-round comparison is exactly paired so takeovers stay fair, but the docs demand a
   number the design can't produce — resolved by writing the analysis into HANDOFF §4 and
   flagging it for the promised sizing round-trip. The criterion should distinguish
   paired-within-round designs from frozen-leader-score designs.
3. **Small onboarding papercuts:** the `competition-onboarding` label referenced by the
   issue template didn't exist on the repo (had to create it); the issue template's
   "`apex-dev run` produced result.json" checkbox can't currently be satisfied.
4. **Not SDK's fault but will bite RL designers:** torch ≥2.13 exports ONNX with an
   external `.data` sidecar by default; the platform writes exactly one artifact file, and
   the model *silently works locally* (sidecar present) then would fail readiness in prod.
   The baseline recipe now embeds weights and the README warns about it — worth a line in
   the SDK docs too.

## Scores (fresh-user POV, 1–10)

| Dimension | Score | One-liner |
|---|---|---|
| **Ease of use** | **7.5** | Docs and skill are exceptional; losing 2 points to the missing local run harness and release-flow papercuts. |
| **Completeness** | **6.5** | Authoring, validation, and contracts are all there; execution tooling (local loop, published base images, result-path config) isn't yet. |
| **SDK expressiveness** | **9** | A MuJoCo RL parkour competition — seed-derived procedural rounds, ONNX-only submissions, multi-gate scoring — fit the schema with zero SDK changes and ~800 lines of Python. Hard to ask for more. |

**Overall: 7.5/10** — a fresh user with an idea and this SDK ships a real, signed,
review-ready competition in a day; give them `apex-dev run` that actually runs, and it's
an afternoon.
