# Competition Onboarding Manifest: `<competition_id>`

Fill this document completely and submit it with your [**Competition onboarding
issue**](https://github.com/macrocosm-os/apex-competitions-builder/issues/new?template=competition-onboarding.yml)
on the toolkit repo (`macrocosm-os/apex-competitions-builder`) — the form has a field for
it, alongside a description of the competition, your repo URL, released tag,
and image refs + digests. Macrocosmos reviews it, copies your `spec.yaml`
into the private registry, and activates it on stage — where your baseline
runs a staging round — before going live. Incomplete sections are the most
common cause of a delayed launch.

> What Macrocosmos decides unilaterally: the final incentive weight, the
> submission fee, activation timing, and whether extra screening is required
> after security review. Everything else below is your proposal and will be
> discussed, not silently changed.

## 1. Goal statement & alignment plan

**What success looks like** (one paragraph, domain terms — what a winning
solution should *be*, not what score it gets; vague is acceptable, absent is
not):

> `<...>`

**Alignment checks** (2–3 concrete, checkable properties derived from the
goal) and **review plan** (what you will inspect in top submissions each
round, and which non-ranking diagnostics you will watch for score/goal
divergence):

- `<check 1>`
- `<check 2>`
- Review cadence & method: `<...>`

## 2. Deliverables

| Item | Where | Done |
|---|---|---|
| Competition repo (public or private) + released tag | `<url>` @ `<tag>` | ☐ |
| `spec.yaml` (`apex.competition.v1`) — `apex-dev preflight` passes | `<path in repo>` | ☐ |
| Player image | `<registry>/<image>@sha256:<digest>` | ☐ |
| Referee image | `<registry>/<image>@sha256:<digest>` | ☐ |
| Layer-2 screen image — or written justification for why none is needed (§5) | `<image@digest>` / n/a | ☐ |
| Round-generation entrypoint (`generate_round`) — or "platform seed is enough" | in spec / n/a | ☐ |
| Cosign identity + issuer (as declared in the spec `signature` block) | `<workflow url>` | ☐ |
| `input_schema` + input fixtures | `<paths>` | ☐ |
| Baseline submission (scores > 0 through the full player+referee loop) | `<path>` | ☐ |
| Adversarial submission set (each scores ≤ your zero floor through the full loop) | `<path>` | ☐ |
| Miner-facing README | `<path>` | ☐ |
| Evidence of a full end-to-end run (local two-image run or stage round) | `<attach output>` | ☐ |

Everything that affects scores must be pinned: image digests (`@sha256:`),
model revisions (full 40-char SHA), dataset content hashes, dependency
versions. List every pin here:

- model revision: `<sha or n/a>`
- dataset hash(es): `<sha256 or n/a>`

## 3. Ops parameters (your proposal — each with a one-line reason tied to §1)

Spec-carried values must match your `spec.yaml`; the rest are negotiated at
onboarding.

| Parameter | Where it lives | Proposal | Production norm |
|---|---|---|---|
| `process_type` | spec | cpu / gpu | cpu (gpu needs §6 justification and is platform-gated) |
| `kind` | spec | solo / duel | solo (7 of 9; duel needs a written case) |
| `duel` block (duels only) | spec | `<players_per_match, num_games_default, swap_sides>` / n/a | 2 players, swap_sides: true |
| `defaults.round_length_in_days` | spec | `<days>` | 1–2 days |
| `defaults.submission_reveal_days` | spec | `<days>` | 1–7 days |
| `defaults.lower_is_better` | spec | true / false | — |
| `defaults.baseline_raw_score` / `baseline_score` | spec | `<values>` | measured, not guessed |
| `resources` (per sandbox) | spec | `<cpu_limit, mem_limit, gpu_count>` | ~1 CPU / 1.5Gi (ceilings: stage 2 CPU / 2Gi, prod 4 CPU / 4Gi) |
| `evaluate.timeout_s` / `referee.timeout_s` | spec | `<seconds>` | median eval 1–10 min |
| Per-move deadline (`deadline_ms`, gym_v1) | referee config | `<ms>` / n/a | 0.5–5 s |
| Submission fee | platform | `<USD>` | ≈$1 (the anti-spam mechanism; final: Macrocosmos) |
| Incentive weight | platform | `<proposal>` | 0.02–0.05 (final: Macrocosmos) |

## 4. Evaluation-sizing justification (required paragraph)

Written evidence, not intent — run the procedure in
`reference/evaluation-design.md` and report:

- Instances per evaluation (N): `<N>`
- Measured σ_round across ≥20 master seeds with the baseline: `<value>` (attach the numbers)
- Typical top score and the resulting takeover margin (1%): `<value>`
- Check: σ_round ≤ ¼ × margin? `<yes/no + arithmetic>`
- Reference solutions rank consistently across all seeds? `<yes/no>`
- Total evaluation wall time at N: `<seconds>` (fits the spec timeouts above?)

## 5. Threat-model questionnaire (all answers required, "n/a" must say why)

This is the **only** place your defenses are written down: they live in the
scoring logic (SKILL.md design step 5) and are never named or explained in
comments, docstrings, metadata keys, error text, or the miner README. Be
exhaustive here — including the pathways you chose not to close, and why.

1. **Miner-visible surface.** List every field the round input carries, plus
   everything else that enters the player sandbox (env, config, observation
   stream). For each: why is it safe in an adversary's hands?
2. **Seed leverage.** Can ground truth, the held-out pool sampling, or any
   future round's data be regenerated from the round seed plus the miner-reachable
   player image (and repo, if public)?
3. **Degenerate submissions.** What raw score does a constant / empty /
   all-zeros / random-noise submission get? Which gate zeroes it if it
   would otherwise place?
4. **Baseline resubmission.** A miner submits your published baseline
   verbatim — what happens? (It must not take or hold the lead.)
5. **Metric gaming.** You spent a day adversarially probing your own metric
   (security-checklist §8). What did you find, and what gate now covers it?
6. **Malicious responses.** What does your referee do with a player response
   that is the wrong type, NaN/Inf, oversized, wrongly shaped, invalidly
   encoded, or out of range? Where is it validated, and what score results?
7. **Profitable failure.** What raw score is paid by a submission that
   induces a referee exception, stalls to every deadline, goes unhealthy
   mid-match, or returns nothing? Show each pays less than an honest bad
   answer, and that no exception, timeout, or forfeit branch yields partial
   or default credit.
8. **Aggregation integrity.** Fixed instance count? Do missing instances
   score zero rather than drop out of the denominator? Are per-instance
   contributions clamped and all terms bounded? Can one instance carry a
   whole evaluation?
9. **Adversarial submission results.** For each submission in the §2
   adversarial set, its raw score through the full player+referee loop,
   against your zero floor and your baseline.
10. **Defense hygiene.** Confirm no comment, docstring, log line, error
    string, `result.json` metadata key, or miner-README section names or
    explains any of the defenses above.
11. **Copy-plus-epsilon.** After the reveal delay, a miner copies the leader
    and perturbs it trivially. Does your metric/threshold make that a losing
    strategy?
12. **Cross-round leakage.** Does observing one full round (tasks, own
    diagnostics, the referee's query stream — miners log every request your
    referee makes) let a miner hard-code answers for later rounds? How fast
    does the pool/sampling rotate relative to that?
13. **Error-message hygiene.** What do your failure reasons / error texts
    reveal? (They are visible during the active round.)
14. **Referee state.** Is your referee deterministic and stateless across
    games/matches? Any caches, temp files, or logs keyed on
    submission-controlled values?
15. **Code execution.** If `artifact_type: code`: why could the format not
    be constrained to `onnx`/`torchscript`? Which `screening` extras does
    your spec add to the base forbidden sets? If artifacts: can the format
    smuggle code (TorchScript-style), and what structural checks block it?
16. **Player-image hygiene.** The player image is miner-reachable and may be
    public (repo/image visibility is your choice) — treat its contents as
    exposable and confirm it contains no ground truth, judge configuration, or
    held-out data. Secret checks belong in the referee or the Layer-2 screen image.
17. **Diagnostics payload.** What goes in `result.json` metadata / artifact
    files revealed at round completion, and why does none of it correlate
    with hidden ground truth?

## 6. GPU justification (only if `process_type: gpu`)

GPUs are platform-gated and belong on the scoring side, almost never in the
player sandbox. State: which sandbox needs it (referee vs player), what
computation needs it, why CPU with a smaller model/budget can't work,
expected GPU-minutes per evaluation, and the expected submission volume it
must sustain.

## 7. What happens next

1. Macrocosmos security review (re-walks `reference/security-checklist.md`
   against §5 answers; checks digest pinning, cosign identity, resource
   ceilings).
2. Your `spec.yaml` is copied verbatim into the private registry and
   activated on stage; your baseline runs a staging round.
3. One feedback round-trip — most often on evaluation sizing (§4) and the
   reveal policy.
4. Prod activation with the agreed incentive weight and fee. Updates later
   follow the same loop: bump `version`, re-sign, request activation.
