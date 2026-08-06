# Security & Anti-Exploit Checklist

Miners are adversarial, skilled, and economically motivated: the prize is continuous token emissions, so a working exploit pays out until someone notices. Every item below traces to a real design decision (or near-miss) in production. Walk the whole list before onboarding; Macrocosmos re-walks it during review.

The structural defense underneath everything here: the submission runs in a **player** sandbox and your scoring logic runs in a separate, competition-owned **referee** sandbox on a per-job network. A submission can never read, patch, or share a filesystem with the scorer. The checklist is about not undoing that isolation through what you *send* and what you *reveal*.

Two rules run through all of it. Defenses are **design inputs, not a hardening pass** — a scoring function that pays for the wrong behaviour has to be replaced (new spec `version`, miners already trained on the old one), so the pathways get closed while you are choosing the metric. And defenses are **never described in anything a miner can read** — see §9.

## 1. Data revealed in results and artifacts

The platform hides per-task result metadata and artifact files while a round is active and reveals them when the round completes. Within that constraint, **more revealed data is better** — per-task scores, per-instance timings, episode traces, matched diagnostic cues all shorten miners' iteration loops, and faster iteration is why you're running a competition. The line to hold:

- ✅ Safe to reveal post-round: per-instance scores and breakdowns, timings, logs of the miner's own execution, the round's seed **if and only if every round uses a fresh seed and the seed can't regenerate future rounds' data**.
- ❌ Never reveal, in any round: held-out pool contents beyond the sampled instances, ground-truth labels/answers for instances that may recur, scoring internals not in your published spec (detector weight tables, judge prompts, threshold internals), anything about *future* round generation.
- ❌ Never put secrets in immediately-visible error/failure reasons — miners see those during the active round. Error messages should say what was wrong with the submission, not what the evaluator was doing.
- Remember the round input (your `input_schema` payload) is eventually miner-visible. If a field would hurt in a miner's hands, it doesn't belong in a task — keep audit material (baseline scoring evidence, generation wall-times, machine fingerprints) out of the `generate_round` task output entirely.
- **Treat your player image and competition repo as exposable.** They can be public or private (your choice, per artifact), but the player image is miner-reachable and miners can inspect anything you ship in it — so design as if its contents are published on day one, whichever visibility you pick. Anything baked into them — helper data, judge configuration, thresholds — is fair game. Scoring assets belong in the referee image; secret behavioural checks belong in the Layer-2 screen image. Those two images are where secrets live and stay isolated from the player, regardless of how you set repo/image visibility.

## 2. Miners stealing from each other on shared infrastructure

- Each job gets its own sandboxes with isolated, per-job mount directories, deleted after evaluation. Do not weaken this: never design anything that needs a shared writable volume between two submissions' containers.
- In duels, player sandboxes and the referee share a per-job network — ensure players interact only *through* your referee (opponents exchange moves via your engine, never directly), and never mount both players' artifacts into one container.
- Keep your referee stateless across games and matches: no caching keyed on anything a submission controls, no temp files with predictable names, no submission bytes in logs a later game could read. A referee that remembers is a side channel.
- The reveal delay (`defaults.submission_reveal_days`) is the *sanctioned* way miners copy each other. Anything faster than that is a leak.

## 3. Data sent into the player sandbox that reveals the dataset

**Assume the miner reads every byte that enters the player sandbox**: the round input, the observation stream, files, env vars, command-line args, even timing side-channels. The container is their code running on their input.

- Never send a seed into the player sandbox that, combined with the miner-reachable player image (and repo, if public), regenerates hidden data (ground truth, upcoming instances, the held-out pool sampling). Seeds that only randomize the miner-visible instance are fine; seeds that parameterize your secret generator are not. When in doubt, send the generated instance, not the seed.
- Never send validation criteria, thresholds, expected outputs, or grader configuration to the player. Score in the referee: the player produces actions/outputs, the referee grades them against ground truth it alone holds.
- The referee's query stream itself leaks (the miner logs every `/act` request you make). Ensure observing the full request sequence for one round doesn't reveal enough to hard-code answers for the next.

## 4. Internet access

- Sandboxes have no internet, ever. Egress is blocked by the platform regardless of what your spec says (`allow_internet` should stay false; `network_disabled: false` only makes the player reachable by the referee on the per-job network). Internet would enable exfiltration of your task data, download of oversized models (bypassing your resource limits), calls to external compute (a $0 sandbox proxying to a rented H100 cluster), and coordination between miners.
- If the *evaluation* needs external resources (big datasets, LLM judges), bake them into the referee image or its data — pinned and content-hashed. The miner's artifact must be self-contained.

## 5. Filesystem persistence across iterations

- Mount directories are per-job and deleted after evaluation; images are immutable and pulled by digest. Do not create any writable location that survives an evaluation: no shared caches, no "warm-up state" directories. A persistent file is a message board — miners will use it to pass themselves information across evaluations (cached answers keyed on input hashes) or to poison other miners' runs.
- If you need expensive warm-up, bake it into your image at build time (pre-downloaded weights, pre-computed tables) — not runtime state.

## 6. Screening: two layers, and what belongs in each

- **Layer 1 (declarative, in your spec's `screening` block)** runs the platform's generic screener with no competition code: AST bans for `code` submissions (base forbidden sets for `socket`/network clients, file primitives beyond sanctioned paths, `pickle`/`marshal`/dynamic execution, `threading` timeout evasion, `mmap`, `signal`, dynamic-attribute escapes — extend with `extra_forbidden_*` rather than inventing your own) and structural validation for `torchscript`/`onnx` (size, magic bytes, minimum-weight-data floors, code-to-weights ratio). It's a tripwire, not the boundary — the sandbox is the actual defense — so it's fine that the config is visible in the spec (which the platform reviews, and which you may publish).
- **Layer 2 (optional, `entrypoints.screen`)** runs bespoke behavioural checks in your own separate image before evaluation (exit 0 = pass). Use it only for checks that must stay secret; it keeps your tripwires out of the miner-reachable player image (and lets you publish that image without publishing them).
- Never put screening or evaluation logic in the player image alongside miner code — the sandbox holding seeds and criteria must be a different container from the one running the submission. The platform enforces this shape; don't design around it.
- Binary artifacts need structural screening if they can smuggle code: a TorchScript archive contains Python code by design — screen size, magic bytes, weight floors, code-to-weights ratio. An ONNX graph cannot carry arbitrary code the same way, which is exactly why the more constrained artifact type is preferred.

## 7. Design so Layer-2 screening is unnecessary

The strongest security control is a submission format that can't express an attack:

- **Fix the architecture, accept only model artifacts.** If miners submit `onnx` with an exact input/output/opset manifest, there is no code to screen — validation is a typed rejection from your player's loader. (The production RL-duel competition would need no code screening at all had it launched artifact-only with a hard-coded model structure; its TorchScript format is why it carries one.)
- Same idea for non-ML domains: accept a policy table, a parameter vector, a JSON strategy spec — anything with a closed grammar you can validate structurally in your player before serving it.
- Constrained formats also produce **better solutions**: miners spend effort on the problem, not on probing your sandbox, and the winning artifact is something you can actually deploy.
- This is steering, not law. If your problem genuinely needs arbitrary code (heuristics, search, routing logic), use `artifact_type: code` with tightened Layer-1 config and tight budgets — but write down in your design doc why the constrained formats couldn't express the solution space, because Macrocosmos will ask.

## 8. Metric gaming (Goodhart attacks)

Not sandbox escapes — just beating your metric without solving your problem. Your gates should be derived from the success statement (SKILL.md design step 1): every way a submission could score without embodying the goal is a gate you need, and the round-by-round review of top submissions against that statement is what catches the ways you missed. This section is about submissions that play your metric; §9 is about submissions that attack the machinery that computes it. Both are metric design (SKILL.md design step 5), so both land in your referee before launch, not after an incident.

- Add **validity gates** in your referee that zero out degenerate outputs: an independent coherence/sanity judge, NaN/Inf and range guards, structural checks on outputs. Production example: an unsteered-model coherence judge that zeroes keyword-spam completions which would otherwise saturate a lexicon detector.
- Add **cost regularizers** where "more force" trivially raises the metric: efficiency penalties like `score × exp(-intervention_magnitude / scale)` stop maximal-intervention solutions from dominating.
- Probe your own metric adversarially before launch: spend a day trying to score high with solutions that are obviously wrong. Whatever you find, a miner finds within the first week — production competitions have had miners discover unintended strategies within days of launch.
- Watch the recorded per-run resource metrics and score distributions after launch; step-function score jumps across many miners usually mean a leak or a metric hole, not a breakthrough.

## 9. Malicious input into the scoring path — defended in the scoring, and never documented

A submission cannot reach your scorer's filesystem, but it does get to choose every byte your scorer reads from it. That makes the player→referee channel the one place a submission can attack your scoring directly, and the defense has to be built into how score is computed (SKILL.md design step 5) rather than layered on afterwards.

- **Validate every player response at the boundary before it can influence score**: type, shape, length, encoding, numeric range, NaN/Inf, nesting depth, payload size, indices within bounds. A response that fails validation becomes a low score you computed on purpose — never an exception, never a `None` that flows into arithmetic, never a value your scorer trusts because it arrived in the right field.
- **Audit every non-happy path for what it pays.** Walk your referee's exception handlers, timeout branches, forfeit handling, and retry logic and ask what score each yields. Partial credit for completed instances, neutral scores for missing outputs, dropping an instance from the denominator, or an unscored forfeit are all strategies as soon as they beat an honest attempt. Failing must always pay less than trying.
- **Never let a submission profit from breaking the harness.** A referee crash or referee timeout is attributed to you, stalls the round, and pollutes results — so a crafted response must not be able to cause one. Bound the work any single response can trigger (no unbounded loops, allocations, regexes, parsing, or recursion driven by player-controlled values), and keep per-instance and per-call budgets enforced in the referee, not just in the sandbox limits.
- **Make the aggregation exploit-free by construction**: fixed instance count, missing instances scoring zero rather than being omitted, clamped per-instance contributions, bounded and monotone terms, no divide-by-small, deterministic tiebreaks. If one instance can carry a whole evaluation, one crafted instance response is a winning strategy.
- **Verify with adversarial submissions, not by inspection.** Keep a set in your repo's tests — empty, constant, random, malformed types, NaN, oversized payload, deadline-staller, exception-inducer, protocol abuser (out-of-order or repeated calls), and your own best-guess exploit — and require each to score at or below your zero floor through the real player+referee loop. Run it again on every scoring change; a metric edit that quietly re-opens a pathway looks exactly like a harmless refactor.
- **Say none of it out loud.** No comment, docstring, README section, `result.json` metadata key, log line, or error string may name, explain, or hint at these defenses. Anything you write about a defense tells miners precisely which boundary to probe and — by what it omits — where you have not looked; error text visible during an active round is the worst offender. Write the checks as ordinary rules of the game in domain terms ("an action scores only if it is well-formed and arrives within the deadline"), name identifiers for what they measure rather than what they prevent, and let the miner README state the rules without the reasoning. The disclosure channel is `HANDOFF.md` §5, which reaches Macrocosmos privately at onboarding — write everything there, in full, including the pathways you decided not to close and why.

## 10. Determinism as a security property

Same submission + same round input + same seed must produce the same score: pin model revisions (full SHA), dataset content hashes, dependency versions; use greedy/deterministic inference; verify data integrity at load (checksum the pool). Non-determinism is not just noise — it is a dispute you cannot win ("your evaluator is random" is unanswerable without reproducibility) and a seed-fishing vector (see evaluation-design.md). Determinism is also what makes score-affecting changes auditable: any change to scoring is a new spec `version` with a new signed digest, reviewable in git.
