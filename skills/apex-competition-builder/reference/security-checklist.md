# Security & Anti-Exploit Checklist

Miners are adversarial, skilled, and economically motivated: the prize is continuous token emissions, so a working exploit pays out until someone notices. Every item below traces to a real design decision (or near-miss) in production. Walk the whole list before onboarding; Macrocosmos re-walks it during review.

The structural defense underneath everything here: the submission runs in a **player** sandbox and your scoring logic runs in a separate, competition-owned **referee** sandbox on a per-job network. A submission can never read, patch, or share a filesystem with the scorer. The checklist is about not undoing that isolation through what you *send* and what you *reveal*.

## 1. Data revealed in results and artifacts

The platform hides per-task result metadata and artifact files while a round is active and reveals them when the round completes. Within that constraint, **more revealed data is better** — per-task scores, per-instance timings, episode traces, matched diagnostic cues all shorten miners' iteration loops, and faster iteration is why you're running a competition. The line to hold:

- ✅ Safe to reveal post-round: per-instance scores and breakdowns, timings, logs of the miner's own execution, the round's seed **if and only if every round uses a fresh seed and the seed can't regenerate future rounds' data**.
- ❌ Never reveal, in any round: held-out pool contents beyond the sampled instances, ground-truth labels/answers for instances that may recur, scoring internals not in your published spec (detector weight tables, judge prompts, threshold internals), anything about *future* round generation.
- ❌ Never put secrets in immediately-visible error/failure reasons — miners see those during the active round. Error messages should say what was wrong with the submission, not what the evaluator was doing.
- Remember the round input (your `input_schema` payload) is eventually miner-visible. If a field would hurt in a miner's hands, it doesn't belong in a task — keep audit material (baseline scoring evidence, generation wall-times, machine fingerprints) out of the `generate_round` task output entirely.
- **Your player image and competition repo are public.** Anything baked into them — helper data, judge configuration, thresholds — is published on day one. Scoring assets belong in the referee image; secret behavioural checks belong in the Layer-2 screen image, which exists precisely so they stay private while the player image is public.

## 2. Miners stealing from each other on shared infrastructure

- Each job gets its own sandboxes with isolated, per-job mount directories, deleted after evaluation. Do not weaken this: never design anything that needs a shared writable volume between two submissions' containers.
- In duels, player sandboxes and the referee share a per-job network — ensure players interact only *through* your referee (opponents exchange moves via your engine, never directly), and never mount both players' artifacts into one container.
- Keep your referee stateless across games and matches: no caching keyed on anything a submission controls, no temp files with predictable names, no submission bytes in logs a later game could read. A referee that remembers is a side channel.
- The reveal delay (`defaults.submission_reveal_days`) is the *sanctioned* way miners copy each other. Anything faster than that is a leak.

## 3. Data sent into the player sandbox that reveals the dataset

**Assume the miner reads every byte that enters the player sandbox**: the round input, the observation stream, files, env vars, command-line args, even timing side-channels. The container is their code running on their input.

- Never send a seed into the player sandbox that, combined with your public repo/images, regenerates hidden data (ground truth, upcoming instances, the held-out pool sampling). Seeds that only randomize the miner-visible instance are fine; seeds that parameterize your secret generator are not. When in doubt, send the generated instance, not the seed.
- Never send validation criteria, thresholds, expected outputs, or grader configuration to the player. Score in the referee: the player produces actions/outputs, the referee grades them against ground truth it alone holds.
- The referee's query stream itself leaks (the miner logs every `/act` request you make). Ensure observing the full request sequence for one round doesn't reveal enough to hard-code answers for the next.

## 4. Internet access

- Sandboxes have no internet, ever. Egress is blocked by the platform regardless of what your spec says (`allow_internet` should stay false; `network_disabled: false` only makes the player reachable by the referee on the per-job network). Internet would enable exfiltration of your task data, download of oversized models (bypassing your resource limits), calls to external compute (a $0 sandbox proxying to a rented H100 cluster), and coordination between miners.
- If the *evaluation* needs external resources (big datasets, LLM judges), bake them into the referee image or its data — pinned and content-hashed. The miner's artifact must be self-contained.

## 5. Filesystem persistence across iterations

- Mount directories are per-job and deleted after evaluation; images are immutable and pulled by digest. Do not create any writable location that survives an evaluation: no shared caches, no "warm-up state" directories. A persistent file is a message board — miners will use it to pass themselves information across evaluations (cached answers keyed on input hashes) or to poison other miners' runs.
- If you need expensive warm-up, bake it into your image at build time (pre-downloaded weights, pre-computed tables) — not runtime state.

## 6. Screening: two layers, and what belongs in each

- **Layer 1 (declarative, in your spec's `screening` block)** runs the platform's generic screener with no competition code: AST bans for `code` submissions (base forbidden sets for `socket`/network clients, file primitives beyond sanctioned paths, `pickle`/`marshal`/dynamic execution, `threading` timeout evasion, `mmap`, `signal`, dynamic-attribute escapes — extend with `extra_forbidden_*` rather than inventing your own) and structural validation for `torchscript`/`onnx` (size, magic bytes, minimum-weight-data floors, code-to-weights ratio). It's a tripwire, not the boundary — the sandbox is the actual defense — so it's fine that the config is visible in the public spec.
- **Layer 2 (optional, `entrypoints.screen`)** runs bespoke behavioural checks in your own separate image before evaluation (exit 0 = pass). Use it only for checks that must stay secret; it's what lets your player image go public without publishing your tripwires.
- Never put screening or evaluation logic in the player image alongside miner code — the sandbox holding seeds and criteria must be a different container from the one running the submission. The platform enforces this shape; don't design around it.
- Binary artifacts need structural screening if they can smuggle code: a TorchScript archive contains Python code by design — screen size, magic bytes, weight floors, code-to-weights ratio. An ONNX graph cannot carry arbitrary code the same way, which is exactly why the more constrained artifact type is preferred.

## 7. Design so Layer-2 screening is unnecessary

The strongest security control is a submission format that can't express an attack:

- **Fix the architecture, accept only model artifacts.** If miners submit `onnx` with an exact input/output/opset manifest, there is no code to screen — validation is a typed rejection from your player's loader. (The production RL-duel competition would need no code screening at all had it launched artifact-only with a hard-coded model structure; its TorchScript format is why it carries one.)
- Same idea for non-ML domains: accept a policy table, a parameter vector, a JSON strategy spec — anything with a closed grammar you can validate structurally in your player before serving it.
- Constrained formats also produce **better solutions**: miners spend effort on the problem, not on probing your sandbox, and the winning artifact is something you can actually deploy.
- This is steering, not law. If your problem genuinely needs arbitrary code (heuristics, search, routing logic), use `artifact_type: code` with tightened Layer-1 config and tight budgets — but write down in your design doc why the constrained formats couldn't express the solution space, because Macrocosmos will ask.

## 8. Metric gaming (Goodhart attacks)

Not sandbox escapes — just beating your metric without solving your problem. Your gates should be derived from the success statement (SKILL.md design step 1): every way a submission could score without embodying the goal is a gate you need, and the round-by-round review of top submissions against that statement is what catches the ways you missed.

- Add **validity gates** in your referee that zero out degenerate outputs: an independent coherence/sanity judge, NaN/Inf and range guards, structural checks on outputs. Production example: an unsteered-model coherence judge that zeroes keyword-spam completions which would otherwise saturate a lexicon detector.
- Add **cost regularizers** where "more force" trivially raises the metric: efficiency penalties like `score × exp(-intervention_magnitude / scale)` stop maximal-intervention solutions from dominating.
- Probe your own metric adversarially before launch: spend a day trying to score high with solutions that are obviously wrong. Whatever you find, a miner finds within the first week — production competitions have had miners discover unintended strategies within days of launch.
- Watch the recorded per-run resource metrics and score distributions after launch; step-function score jumps across many miners usually mean a leak or a metric hole, not a breakthrough.

## 9. Determinism as a security property

Same submission + same round input + same seed must produce the same score: pin model revisions (full SHA), dataset content hashes, dependency versions; use greedy/deterministic inference; verify data integrity at load (checksum the pool). Non-determinism is not just noise — it is a dispute you cannot win ("your evaluator is random" is unanswerable without reproducibility) and a seed-fishing vector (see evaluation-design.md). Determinism is also what makes score-affecting changes auditable: any change to scoring is a new spec `version` with a new signed digest, reviewable in git.
