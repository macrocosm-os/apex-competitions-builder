"""The environment the miner's harness drives: a referee-side context buffer.

This is the heart of the competition. The harness NEVER receives document text. It can
see that a document exists (`search` returns id, title, provenance, size), it can move
documents into and out of a referee-side context buffer, and it can spend tokens asking
the frozen model a question *about the buffer*. Only model output crosses back.

    search(query, k)          -> [{doc_id, title, source, revised, est_tokens, bm25}]
    add(doc_ids) / drop(...)  -> buffer state (doc ids + token size)
    ask(instruction, system)  -> model completion over [buffer] + instruction
    answer(text, citations)   -> ends the question

That one restriction is what makes the base model provably load-bearing. A harness
cannot regex its way to the answer, because it has no text to regex; the only channel
from corpus to harness runs through the model. Everything a good harness does — which
documents to fetch, which to evict, what to ask, how many passes, when to stop, when to
abstain, how to spend a shared budget across questions — remains fully in its control.

Budgets:
  * one shared token pool for the WHOLE episode, so allocating effort across questions
    is a real decision (the harness sees tokens_remaining and questions_remaining);
  * a per-question step cap, so a harness cannot stall the round;
  * a context-buffer token cap, so "add every document" is not a strategy.

Every rejected action costs a step and no tokens, and returns a typed `error` — never a
silent no-op. A harness must be able to tell "you asked for something impossible" from
"the corpus does not contain it".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from env.model import BaseModel
from env.world import Question, World

#: Neutral default. A harness may override it — defending against a document that
#: contains instructions is the harness's job, not the environment's.
DEFAULT_SYSTEM = "You are a careful research assistant. Answer using only the supplied documents."

MAX_SEARCH_K = 20
MAX_CITATIONS = 20


@dataclass
class Budget:
    """Shared across the episode; `question_steps` resets per question."""

    tokens_remaining: int
    max_steps_per_question: int
    max_context_tokens: int


@dataclass
class QuestionRun:
    """Per-question accounting the referee turns into a score and a trace."""

    question: Question
    steps: int = 0
    tokens_spent: int = 0
    model_calls: int = 0
    answered: bool = False
    answer_text: str = ""
    citations: list[str] = field(default_factory=list)
    stop_reason: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)


class InvalidAction(ValueError):
    """The harness returned something that is not a well-formed action at all."""


class Episode:
    """Drives one harness through one question set against one world."""

    def __init__(self, world: World, model: BaseModel, budget: Budget):
        self.world = world
        self.model = model
        self.budget = budget
        self.context: list[str] = []  # doc_ids, in harness-chosen order
        self.run: QuestionRun | None = None

    # ----------------------------------------------------------------- lifecycle

    def start_question(self, question: Question, questions_remaining: int) -> dict[str, Any]:
        """Reset the buffer and return the first observation."""
        self.context = []
        self.run = QuestionRun(question=question)
        return self._observation(questions_remaining=questions_remaining, last={"type": "start"})

    def step(self, action: Any, questions_remaining: int) -> tuple[dict[str, Any], bool]:
        """Apply one harness action. Returns (observation, done)."""
        run = self.run
        if run is None:  # pragma: no cover - referee always calls start_question first
            raise RuntimeError("step() before start_question()")

        run.steps += 1
        try:
            last, done = self._dispatch(action)
        except InvalidAction as e:
            last, done = {"type": "error", "error": str(e)}, False

        run.events.append({"step": run.steps, **{k: v for k, v in last.items() if k != "completion"}})

        if not done and run.steps >= self.budget.max_steps_per_question:
            run.stop_reason = "step_budget_exhausted"
            done = True
        if not done and self.budget.tokens_remaining <= 0:
            # No tokens left anywhere in the episode: the harness can still answer from
            # what it already learned, but it gets one step to do it, not a silent zero.
            last = {"type": "notice", "notice": "token_pool_exhausted"}

        return self._observation(questions_remaining=questions_remaining, last=last), done

    def _observation(self, questions_remaining: int, last: dict[str, Any]) -> dict[str, Any]:
        run = self.run
        assert run is not None
        return {
            "question": run.question.text,
            "question_id": run.question.question_id,
            "step": run.steps,
            "steps_remaining": max(0, self.budget.max_steps_per_question - run.steps),
            "tokens_remaining": max(0, self.budget.tokens_remaining),
            "questions_remaining": questions_remaining,
            "context": {"doc_ids": list(self.context), "tokens": self._context_tokens()},
            "context_token_limit": self.budget.max_context_tokens,
            "last": last,
        }

    # ----------------------------------------------------------------- dispatch

    def _dispatch(self, action: Any) -> tuple[dict[str, Any], bool]:
        if not isinstance(action, dict):
            raise InvalidAction(f"action must be an object, got {type(action).__name__}")
        tool = action.get("tool")
        if tool == "search":
            return self._search(action), False
        if tool == "add":
            return self._add(action), False
        if tool == "drop":
            return self._drop(action), False
        if tool == "ask":
            return self._ask(action), False
        if tool == "answer":
            return self._answer(action), True
        raise InvalidAction(f"unknown tool {tool!r}; expected search|add|drop|ask|answer")

    def _search(self, action: dict) -> dict[str, Any]:
        query = action.get("query")
        if not isinstance(query, str) or not query.strip():
            raise InvalidAction("search requires a non-empty string `query`")
        k = action.get("k", 10)
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= MAX_SEARCH_K:
            raise InvalidAction(f"search `k` must be an integer in 1..{MAX_SEARCH_K}, got {k!r}")
        hits = self.world.index.search(query, k)
        return {
            "type": "search",
            "results": [
                {
                    "doc_id": doc_id,
                    "title": self.world.documents[doc_id].title,
                    "source": self.world.documents[doc_id].source,
                    "revised": self.world.documents[doc_id].revised,
                    "est_tokens": self.world.documents[doc_id].est_tokens,
                    "bm25": round(score, 3),
                }
                for doc_id, score in hits
            ],
        }

    def _doc_ids_arg(self, action: dict) -> list[str]:
        ids = action.get("doc_ids")
        if isinstance(ids, str):
            ids = [ids]
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise InvalidAction("`doc_ids` must be a non-empty string or list of strings")
        return list(dict.fromkeys(ids))

    def _add(self, action: dict) -> dict[str, Any]:
        ids = self._doc_ids_arg(action)
        unknown = [d for d in ids if d not in self.world.documents]
        if unknown:
            raise InvalidAction(f"unknown doc_ids: {unknown[:5]}")
        new = [d for d in ids if d not in self.context]
        projected = self._context_tokens() + sum(self.world.documents[d].est_tokens for d in new)
        if projected > self.budget.max_context_tokens:
            # Rejected whole, not truncated: a silently dropped document would make the
            # score depend on a rule the harness cannot see.
            raise InvalidAction(
                f"add would take the context to {projected} tokens, over the "
                f"{self.budget.max_context_tokens} limit; drop something first"
            )
        self.context.extend(new)
        return {"type": "add", "added": new, "doc_ids": list(self.context), "tokens": self._context_tokens()}

    def _drop(self, action: dict) -> dict[str, Any]:
        ids = set(self._doc_ids_arg(action))
        removed = [d for d in self.context if d in ids]
        self.context = [d for d in self.context if d not in ids]
        return {"type": "drop", "removed": removed, "doc_ids": list(self.context), "tokens": self._context_tokens()}

    def _ask(self, action: dict) -> dict[str, Any]:
        run = self.run
        assert run is not None
        instruction = action.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise InvalidAction("ask requires a non-empty string `instruction`")
        system = action.get("system") or DEFAULT_SYSTEM
        if not isinstance(system, str):
            raise InvalidAction("`system` must be a string when supplied")
        want_out = action.get("max_output_tokens", self.model.max_output_tokens)
        if not isinstance(want_out, int) or isinstance(want_out, bool) or want_out < 1:
            raise InvalidAction("`max_output_tokens` must be a positive integer when supplied")

        # Refuse rather than overspend. The estimate is deliberately conservative (it
        # assumes the full output cap is used) so the pool can never go negative and
        # every submission faces the same admission rule.
        estimate = (
            self._context_tokens()
            + max(1, (len(system) + len(instruction)) // 4)
            + min(want_out, self.model.max_output_tokens)
        )
        if estimate > self.budget.tokens_remaining:
            raise InvalidAction(
                f"ask needs ~{estimate} tokens but only {self.budget.tokens_remaining} remain in the "
                f"episode pool; shrink the context, ask for fewer output tokens, or answer now"
            )

        docs = "\n\n".join(self.world.documents[d].render() for d in self.context)
        user = f"<documents>\n{docs}\n</documents>\n\n{instruction}" if docs else instruction
        text, prompt_tokens, completion_tokens = self.model.complete(system, user, max_output_tokens=want_out)

        spent = prompt_tokens + completion_tokens
        self.budget.tokens_remaining = max(0, self.budget.tokens_remaining - spent)
        run.tokens_spent += spent
        run.model_calls += 1
        return {
            "type": "ask",
            "completion": text,
            "tokens_spent": spent,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }

    def _answer(self, action: dict) -> dict[str, Any]:
        run = self.run
        assert run is not None
        text = action.get("text")
        if not isinstance(text, str):
            raise InvalidAction('answer requires a string `text` (use "UNKNOWN" to abstain)')
        citations = action.get("citations") or []
        if isinstance(citations, str):
            citations = [citations]
        if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
            raise InvalidAction("`citations` must be a list of doc_id strings")
        run.answered = True
        run.answer_text = text
        run.citations = citations[:MAX_CITATIONS]
        run.stop_reason = "answered"
        return {"type": "answer", "text": text[:200], "citations": run.citations}

    def _context_tokens(self) -> int:
        return sum(self.world.documents[d].est_tokens for d in self.context)
