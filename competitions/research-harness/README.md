# Research Harness

**Write the scaffolding, not the model.** Every submission drives the same frozen base
model. Your score is decided entirely by how well your harness retrieves, reads,
cross-checks, budgets, and decides when to stop.

You submit one Python file. It answers multi-hop questions over a private corpus you
cannot see, through a model you cannot touch directly, on a token budget shared across
the whole round.

---

## The one rule that shapes everything

**Your harness never receives document text.** Not once, not in any field.

You can see that a document exists. You can move it into and out of a context buffer that
lives inside the referee. You can spend tokens asking the frozen model a question *about
that buffer*, and the model's reply comes back to you. That is the only channel from the
corpus to your code.

So there is no regex shortcut and no way to solve the task without the model — but every
decision that makes a research agent good is still yours: which documents to fetch, which
to evict, what to ask, how many passes, when to trust what you read, when to give up, and
how to spend a finite budget across a whole round of questions.

## The task

Each question needs 2–4 hops through a corpus of ~1,100 documents about a synthetic
research world (institutes, researchers, instruments, papers, grants, cities). For example:

> In which city is the institute housing the instrument used in The Kliotirnsturn Report located?

The paper document names the instrument. The instrument document names the institute. The
institute document names the city. **No single document contains the answer**, and the
name of each next entity exists only inside the previous document — so you cannot skip
ahead, and iterative retrieval is not optional.

Every entity is a generated pseudoword, and the whole world is regenerated from a fresh
seed each round. Nothing here is in the base model's training data; the model can only
help you read.

## The action space

Your harness returns exactly one action per step.

| Action | Returns | Cost |
|---|---|---|
| `{"tool": "search", "query": str, "k": int}` | up to `k` hits: `doc_id`, `title`, `source`, `revised`, `est_tokens`, `bm25`. **No text.** | 1 step |
| `{"tool": "add", "doc_ids": [str]}` | the buffer's `doc_ids` and token size | 1 step |
| `{"tool": "drop", "doc_ids": [str]}` | same | 1 step |
| `{"tool": "ask", "instruction": str, "system": str?, "max_output_tokens": int?}` | the model's completion over `[buffer] + instruction`, plus `tokens_spent` | 1 step **+ tokens** |
| `{"tool": "answer", "text": str, "citations": [str]}` | ends the question | 1 step |

`search` is free of tokens. Retrieval quality is fixed and identical for everyone (BM25),
so you compete on *how you query*, never on having a better index.

`ask` is the only action that costs tokens, and it costs the whole prompt — which includes
every document currently in your buffer. **Context management is your token bill.**

To abstain, answer with the literal text `UNKNOWN`.

## Scoring

| Outcome | Score |
|---|---|
| Correct, and ≥50% of your citations are genuine supporting documents | **1.00** |
| Correct, but your citations do not hold up | **0.60** |
| Abstained (`UNKNOWN`) | **0.15** |
| Wrong, or you ran out of steps/tokens without answering | **0.00** |

`raw_score` is the mean over the round's questions. Higher is better.

Two things follow, and they are deliberate:

- **Abstaining beats guessing** below about a 1-in-5 hit rate. Knowing you are lost is
  worth real points, so calibration is part of the job.
- **Running out is not abstaining.** Stalling until the cap scores 0.00, not 0.15.
  Abstention is a decision you have to make and spend a step on.

Answer matching is exact after normalization (case, punctuation, `12,500,000` → `12500000`,
and dropped article/unit words like `the … Grant`). So emit a bare value — `Nengail`, not
`The city is Nengail`. Getting one clean value out of a model's prose is your problem, and
`Nengail or Klosgou` is not a correct answer.

## The corpus lies to you

About 70% of questions have an adversarial document planted on one hop of their chain —
**including intermediate hops**, which is nastier, because a derailed hop sends you off
reading perfectly genuine documents about entirely the wrong entity, and nothing
downstream looks suspicious.

Every trap document takes its victim's **exact title** and a `doc_id` in the victim's own
namespace. You cannot filter traps by identity. The only signals are two fields you can
see for free in search results:

| Trap | How it presents | What defeats it |
|---|---|---|
| `contradictor` | non-registry duplicate, wrong value | provenance: only `source: registry` is authoritative |
| `stale` | **registry** duplicate, wrong value, **older** `revised` | recency, compared *within a title* |
| `injection` | non-registry duplicate whose body imitates system instructions | isolating retrieved content from your instructions |
| `ambiguous` | **registry** duplicate, wrong value, **identical** `revised` | nothing cheap. See below. |

The two world rules, which are also handed to you in `config["rules"]`:

1. Only documents whose `source` is `registry` are authoritative.
2. Among registry documents that disagree, the later `revised` date is current.

Compare `revised` **within a title**, not across the result set. Documents sharing a title
are revisions of one record; an unrelated document being newer tells you nothing.

`ambiguous` is the trap with real headroom. Same source, same date — neither rule breaks
the tie. Somewhere in the corpus is a *registry index* document naming which of the two
records is current and which is withdrawn. Spotting the tie is free (it is right there in
the search metadata). Resolving it costs a search, an `add`, and an `ask`. Deciding whether
that is worth the tokens, on this question, with this much budget left, is the competition.

## The budget is the point

One token pool is shared across **every question in the round** (28,000 tokens for 64
questions by default). Your observation carries `tokens_remaining` and
`questions_remaining` on every step.

The published reference harness scores **0.35**. Given an unlimited budget the *same
harness* scores **0.76**. Almost the entire gap is tokens — it is not being outsmarted, it
is running out of money. That gap is what you are competing for.

An `ask` is refused, not silently truncated, if it would overspend the pool. A refusal
costs a step and returns an error you can read.

## Writing a submission

One file, defining a class named `Harness`:

```python
class Harness:
    def start_question(self, config: dict) -> None:
        """Called once per question. config has: question, question_id, rules,
        token_pool_remaining, questions_remaining, max_steps, max_context_tokens."""

    def act(self, observation: dict) -> dict:
        """Called once per step. Return one action."""
```

Your instance is created **once per round** and reused across every question, so state
persists — which is deliberate. Many questions route through the same institutes and
grants, and the shared budget makes cross-question memory worth having.

Each observation looks like:

```python
{
  "question": "In which city ...?", "question_id": "q007",
  "step": 3, "steps_remaining": 37,
  "tokens_remaining": 24118, "questions_remaining": 57,
  "context": {"doc_ids": ["paper:0136"], "tokens": 36},
  "context_token_limit": 3000,
  "last": {"type": "ask", "completion": "...", "tokens_spent": 221, ...},
}
```

`last` is the result of your previous action — `search` | `add` | `drop` | `ask` |
`answer` | `error` | `notice`. A malformed action is always a typed `error`, never a
silent no-op, and it costs a step but no tokens.

Constraints: stdlib only, no I/O of any kind (your whole capability surface is the actions
you return), 1 MB, `k ≤ 20`, ≤20 citations, 40 steps per question, 3,000-token context
buffer, and you cannot raise the model's temperature or output ceiling.

## Run it locally

```bash
cd competitions/research-harness

# Offline, against the bundled stub model. Good for plumbing and logic; the stub is a
# perfect extractor, so scores against it are an upper bound, not a forecast.
python tools/local_eval.py --submission baseline/submission.py --seed 7 --num-questions 64

# Against a real frozen model (vLLM / llama.cpp --server / Ollama — anything
# OpenAI-compatible). This is the only measurement that means anything.
python tools/local_eval.py --submission baseline/submission.py \
    --model-url http://localhost:8080 --model-name Qwen3-8B --num-questions 64

# Per-question decision trace
python tools/local_eval.py --submission my_harness.py --trace /tmp/trace.jsonl
```

## Where the headroom is

The reference harness in `baseline/submission.py` is deliberately unambitious. Everything
it leaves on the table is a place to compete:

- It holds **one document at a time**, so it structurally cannot notice two documents
  disagreeing, and pays a fresh prompt for every hop.
- It makes **one `ask` per hop**. Several hops' documents in one buffer and one question is
  strictly cheaper.
- It **caches nothing across questions**, and re-reads institutes and grants it has
  already resolved — with a shared pool, that is money on the floor.
- It **abstains on every `ambiguous` trap** rather than paying to resolve it.
- It spends the **same allowance on a 2-hop and a 4-hop question**, which is why its 4-hop
  score collapses to the abstention floor at the default budget.
- Its **hop plan is keyword-driven** and brittle to rephrasing, and it never asks the model
  to help plan.
- Its abstention rule is a **hard failure**, not a calibrated decision.

## Submission reveal

Submissions are revealed 14 days after a round — longer than any other competition in this
repo. A harness *is* the invention, and copying source is free in a way copying weights is
not. Fourteen days is the window you get to keep an edge.
