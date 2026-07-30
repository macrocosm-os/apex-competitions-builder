"""Per-question scoring for research_harness.

Four outcomes, chosen so that the degenerate strategies are all dominated:

    1.00  correct, and at least half the cited documents are genuine supporting docs
    0.60  correct, but the citations do not hold up (right answer, unshown work)
    0.15  abstained (answered the literal token UNKNOWN)
    0.00  wrong

Why abstention pays. Without it the optimal play under a hard token budget is to
guess confidently on every question, and the metric stops distinguishing a harness
that knows when it is lost from one that does not. At these weights the break-even
accuracy is 0.15/0.60 = 25% when citations are weak and 0.15/1.00 = 15% when they are
strong — so guessing is right only when the harness genuinely has better than a
one-in-five shot. Calibration becomes a first-class harness skill instead of a
rounding error.

Why citations are scored at all. A correct answer that cites a planted contradictor
was reached by luck or by the injection, and a competition that cannot tell those
apart from real retrieval will be won by whichever harness is luckiest. Scoring
provenance also gives the designer a per-round trap-resistance read (see
`metadata.traps` in the referee) that is impossible to fake.

Answer matching is EXACT after normalization. Containment would be fatally loose —
"Neandrern or Klosgou" must not count as correct — so the harness is required to emit
a bare value. Extracting one clean value from a small model's prose is itself part of
the job, and the normalizer below absorbs only unambiguous surface noise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ABSTAIN = "UNKNOWN"

SCORE_CORRECT_CITED = 1.0
SCORE_CORRECT_UNCITED = 0.6
SCORE_ABSTAIN = 0.15
SCORE_WRONG = 0.0

#: Fraction of cited documents that must be genuine supporting documents.
CITATION_PRECISION_FLOOR = 0.5

_STRIP_PREFIX = re.compile(r"^(the|a|an|city of|grant|dr\.?)\s+", re.I)
_STRIP_SUFFIX = re.compile(r"\s+(grant|institute|credits|report)$", re.I)
_PUNCT = re.compile(r"[^\w\s]")


def normalize(answer: str) -> str:
    """Fold unambiguous surface noise: case, punctuation, thousands separators, and the
    article/unit words that carry no identity ("the Komol Grant" -> "komol")."""
    s = str(answer).strip().strip("\"'")
    s = re.sub(r"(?<=\d)[,_ ](?=\d\d\d)", "", s)  # 12,500,000 -> 12500000
    s = _PUNCT.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Prefixes/suffixes can stack ("the city of Nengail").
    for _ in range(3):
        before = s
        s = _STRIP_SUFFIX.sub("", _STRIP_PREFIX.sub("", s)).strip()
        if s == before:
            break
    return s.lower()


@dataclass(frozen=True)
class QuestionScore:
    question_id: str
    score: float
    outcome: str
    correct: bool
    abstained: bool
    citation_precision: float
    cited_trap: bool
    hops: int
    template: str
    traps: tuple[str, ...]
    tokens_spent: int
    steps: int


def score_answer(
    question,
    answer_text: str,
    citations: list[str],
    tokens_spent: int,
    steps: int,
) -> QuestionScore:
    """Score one answered question. `question` is an env.world.Question."""
    cited = list(dict.fromkeys(citations or []))  # de-dupe, keep order
    gold = set(question.gold_doc_ids)
    traps = set(question.trap_doc_ids)
    precision = (sum(c in gold for c in cited) / len(cited)) if cited else 0.0
    cited_trap = any(c in traps for c in cited)

    abstained = normalize(answer_text) == normalize(ABSTAIN)
    correct = (not abstained) and normalize(answer_text) == normalize(question.answer)

    if abstained:
        score, outcome = SCORE_ABSTAIN, "abstained"
    elif not correct:
        score, outcome = SCORE_WRONG, "wrong"
    elif precision >= CITATION_PRECISION_FLOOR:
        score, outcome = SCORE_CORRECT_CITED, "correct"
    else:
        score, outcome = SCORE_CORRECT_UNCITED, "correct_uncited"

    return QuestionScore(
        question_id=question.question_id,
        score=score,
        outcome=outcome,
        correct=correct,
        abstained=abstained,
        citation_precision=round(precision, 4),
        cited_trap=cited_trap,
        hops=question.hops,
        template=question.template,
        traps=question.traps,
        tokens_spent=tokens_spent,
        steps=steps,
    )


def unanswered_score(question, tokens_spent: int, steps: int, reason: str) -> QuestionScore:
    """A question the harness never answered — ran out of steps, ran out of the shared
    token pool, crashed, or timed out. Scored as wrong, NOT as an abstention: abstention
    is a deliberate call the harness has to make and pay a step for, and letting a
    timeout collect the abstention rate would reward stalling."""
    return QuestionScore(
        question_id=question.question_id,
        score=SCORE_WRONG,
        outcome=reason,
        correct=False,
        abstained=False,
        citation_precision=0.0,
        cited_trap=False,
        hops=question.hops,
        template=question.template,
        traps=question.traps,
        tokens_spent=tokens_spent,
        steps=steps,
    )
