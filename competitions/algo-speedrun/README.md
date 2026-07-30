# Algorithmic Speedrun

A nanochat-style competition: you're not building a chatbot, you're improving the
training loop itself. Every submission trains the *same* tiny model, on the *same*
data, for the *same* number of steps -- the only thing that differs is the piece of the
loop you changed. Score is validation bits-per-byte (bpb) after that fixed run: **lower
is better**.

## The one rule that shapes everything

You never touch a GPU, and neither does your submitted code, directly. Your submission
is a description of changes to nanochat's training loop; the referee applies those
changes to its own pinned copy of nanochat and runs the training. This means:

- Your code cannot see the real training data, the real held-out validation set, or the
  hardware it's running on beyond what nanochat's own APIs expose.
- Every submission in a round faces the exact same tokenizer, the exact same data shards,
  the exact same seed. There is no data-leakage angle here -- the only lever is the loop.
- What you're actually competing on is nanochat's own critical path: model architecture
  (and, since nanochat couples the two, how the optimizer is built from it), the
  learning-rate/momentum/weight-decay schedule, and how training documents get packed
  into batches.

## Writing a submission

`submission.py` is a single file that defines one thing:

```python
EXTRA_FILES: dict[str, str] = {
    "model.py": "...",      # optional: GPTConfig + GPT-compatible class
    "schedule.py": "...",   # optional: lr_multiplier / muon_momentum / weight_decay
    "data.py": "...",       # optional: data_iterator
}
```

Any key you omit falls back to nanochat's own unmodified logic for that piece -- an
empty `EXTRA_FILES` (see `baseline/submission.py`) is the "changed nothing" baseline.
You don't have to hand-write this dict: work in a normal directory with `model.py` /
`schedule.py` / `data.py` files, then run:

```bash
python tools/pack_submission.py --overrides-dir ./my_changes --out submission.py
```

### The three hooks

- **`model.py`** -- `GPTConfig` (a dataclass: `sequence_len, vocab_size, n_layer, n_head,
  n_kv_head, n_embd, window_pattern`) and a `GPT`-compatible `nn.Module`: constructor
  `GPT(config)`, `forward(idx, targets=None) -> loss`, `init_weights()`,
  `setup_optimizer(unembedding_lr, embedding_lr, matrix_lr, weight_decay, scalar_lr) ->
  Optimizer`, `num_scaling_params()`, `estimate_flops()`. Optimizer construction lives
  here because it does in upstream nanochat too (`GPT.setup_optimizer`) -- architecture
  and optimizer are one hook, not two.
- **`schedule.py`** -- three pure functions: `lr_multiplier(step, num_iterations, cfg)`,
  `muon_momentum(step, num_iterations, cfg)`, `weight_decay(step, num_iterations, cfg,
  weight_decay_scaled)`. See `baseline/schedule.py` for nanochat's own formulas as a
  starting point.
- **`data.py`** -- `data_iterator(tokenizer, batch_size, seq_len, split, device,
  resume_state_dict=None)`, yielding `(inputs, targets, state_dict)` -- same signature as
  nanochat's own `tokenizing_distributed_data_loader_with_state_bos_bestfit`.

Any further files your `model.py`/`schedule.py`/`data.py` import are also fair game --
put them in the same overrides directory and the packer includes them; the referee
materializes everything into one scratch checkout before importing (see
`referee/referee.py`).

### What's screened

Every file inside `EXTRA_FILES` goes through the same AST tripwire as the outer
`submission.py` (`referee/screen.py`): no `socket`/`subprocess`/`urllib`/`requests`/
`ctypes`/`multiprocessing`, no `eval`/`exec`/`compile`/`__import__`, no `os.system`. Your
code has no I/O surface to reach for anyway -- it only ever gets called with tensors and
config dicts by the referee's training loop.

## Scoring: the cheap pass now, the real pass weekly

Every round scores a **fixed, tiny proxy run** -- a few dozen steps on a depth-4 model
(see `input.schema.json`). This is cheap enough to run on every submission, every round,
but it is *not* the whole story: nanochat's real speedrun scale needs hours on 8xH100,
which cannot happen per-submission-per-round without an unbounded compute bill. A
separate, periodic (weekly) deep evaluation takes that round's top-K submissions by
proxy score and runs each at full scale -- see HANDOFF.md §5.

## Run it locally

```bash
python tools/local_eval.py --submission baseline/submission.py --input fixtures/input.json --seed 0
```

Needs a real nanochat checkout on `PYTHONPATH` with a trained tokenizer and at least one
data shard present -- there is no offline stand-in, because the score *is* a measurement
of real training, not a game-like behavior a stub could approximate (see
`tools/local_eval.py`'s docstring).

## Submission reveal

`submission_reveal_days: 14` (spec.yaml `defaults`) -- your override code is copyable
once revealed, same as any harness-shaped competition (research-harness uses the same
window for the same reason: the idea, not the bytes, is what's protected until then).
