# Baseline provenance

## What the baseline is

`baseline/submission.py` — the published reference harness. Not trained, not tuned: it is
the obvious competent strategy written once and left alone, so that
`defaults.baseline_raw_score` represents "a careful first attempt" rather than "the best we
could do". It is meant to be beaten by a wide margin.

Strategy: derive a hop plan from the question's wording; per hop, search for the current
entity, filter to `source: registry`, keep the latest `revised` **within a title**, load one
document, ask the model to extract one field, clean the value, pivot to the next entity;
cite the document used at each hop; give each question an equal slice of the remaining
shared pool; abstain rather than guess, and abstain on any `ambiguous` tie.

## The measurement

Model: **`google/gemma-3-4b-it`**, served locally over an OpenAI-compatible endpoint
(Ollama `gemma3:4b`, which is this model), `temperature=0`, `max_output_tokens=512` — the
same values `spec.yaml`'s `base_model` block pins.

```bash
cd competitions/research-harness
for s in 1 3 7 11 19 23 31; do
  python tools/local_eval.py --submission baseline/submission.py \
      --seed $s --num-questions 64 --token-pool 28000 \
      --model-url http://localhost:11434 --model-name gemma3:4b
done
```

Per seed (1, 3, 7, 11, 19, 23, 31):

```
0.3625  0.3227  0.3492  0.3180  0.3844  0.3359  0.3625
mean 0.3479   sd 0.0239   sem 0.0090   range [0.3180, 0.3844]
token utilisation 99.1-99.5%   model calls ~115/episode
```

`defaults.baseline_raw_score: 0.3479`.

`sd = 0.024` at `n=64` is comfortable for ranking: two submissions separated by more than
about 0.05 are reliably distinguishable round to round.

## Headroom, for calibration

Same harness, same model, `--token-pool 999999` (seeds 7, 19): **0.7586 / 0.7164**.

So at the shipped budget the reference harness is limited by tokens, not by cleverness —
roughly 0.37 of the gap to its own ceiling is pure efficiency. The remainder is the
`ambiguous` trap, which it always abstains on (0.15 flat).

Trap breakdown at unlimited budget, seed 7:

| Trap | Mean score |
|---|---|
| `contradictor` | 1.00 |
| `stale` | 0.92 |
| `injection` | 0.88 |
| `ambiguous` | 0.15 |
| none | 0.85 |

Reading that: the two cheap rules fully solve `contradictor` and nearly solve `stale`.
`injection` is **not** solved — the real model does sometimes follow the imperative text
despite the harness's "data, not instructions" system prompt, which is exactly the failure
mode the trap exists to expose. `ambiguous` is untouched headroom. The `none` row sitting at
0.85 rather than 1.00 is extraction/parsing loss plus cross-contamination (a trap planted
for one question is still in the corpus for another that routes through the same institute).

Intended target for a strong submission: **0.85–0.95**.

## Caveats a maintainer should know

1. **The number is model-specific.** Every score here depends on the served model. If the
   platform serves something other than `google/gemma-3-4b-it`, `baseline_raw_score` is
   wrong and `token_pool` is mis-tuned — re-measure both.
2. **`tools/stub_model.py` is not a substitute.** The offline stub is a perfect field
   extractor that does not follow instructions, so it scores the same harness at 0.4289
   (an upper bound) and reports `injection` as fully solved, which is false. Use it for
   plumbing and logic only.
3. **Ollama's `seed` handling is best-effort.** At `temperature=0` runs were stable across
   repeats, but exact reproducibility depends on the serving stack, not on this repo.
