"""Scoring rules, including the incentive properties the metric is supposed to have."""

from __future__ import annotations

import pytest

from env.scoring import (
    SCORE_ABSTAIN,
    SCORE_CORRECT_CITED,
    SCORE_CORRECT_UNCITED,
    SCORE_WRONG,
    normalize,
    score_answer,
    unanswered_score,
)
from env.world import Hop, Question


def q(answer="Nengail", gold=("paper:0001", "researcher:0002", "lab:0003"), traps=()):
    chain = tuple(Hop(doc_id=d, relation="city", value=answer) for d in gold)
    return Question(
        question_id="q000",
        text="In which city ...?",
        answer=answer,
        template="paper_author_city",
        chain=chain,
        trap_doc_ids=tuple(traps),
        traps=("contradictor",) if traps else (),
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Nengail", "nengail"),
        ("  nengail. ", "nengail"),
        ("The city of Nengail", "nengail"),
        ('"Nengail"', "nengail"),
        ("the Komol Grant", "komol"),
        ("Dr. Houklondzu", "houklondzu"),
        ("12,500,000", "12500000"),
        ("12500000 credits", "12500000"),
    ],
)
def test_normalize_folds_only_unambiguous_surface_noise(raw, expected):
    assert normalize(raw) == expected


def test_normalize_does_not_fold_two_candidates_into_one():
    """Containment matching would score "Nengail or Klosgou" as correct. Exact matching
    after normalization must not."""
    assert normalize("Nengail or Klosgou") != normalize("Nengail")


def test_correct_and_well_cited_scores_full():
    s = score_answer(q(), "Nengail", ["paper:0001", "lab:0003"], 500, 6)
    assert s.score == SCORE_CORRECT_CITED
    assert s.outcome == "correct" and s.citation_precision == 1.0


def test_correct_but_uncited_scores_less_than_correct_and_cited():
    s = score_answer(q(), "Nengail", [], 500, 6)
    assert s.score == SCORE_CORRECT_UNCITED
    assert SCORE_CORRECT_UNCITED < SCORE_CORRECT_CITED


def test_citation_spam_does_not_buy_the_full_score():
    """Citing everything is the obvious way to game a citation term; precision has to make
    it worse than citing accurately."""
    # 9 distinct ids after de-duplication (lab:0003 is both gold and in the spam range).
    s = score_answer(q(), "Nengail", ["lab:0003"] + [f"lab:{i:04d}" for i in range(9)], 500, 6)
    assert s.citation_precision == pytest.approx(1 / 9, abs=1e-4)  # reported to 4 dp
    assert s.score == SCORE_CORRECT_UNCITED


def test_wrong_answer_scores_zero_however_well_cited():
    s = score_answer(q(), "Klosgou", ["paper:0001", "researcher:0002", "lab:0003"], 500, 6)
    assert s.score == SCORE_WRONG and s.outcome == "wrong"


def test_abstention_pays_more_than_a_wrong_guess_and_less_than_a_right_one():
    s = score_answer(q(), "UNKNOWN", [], 100, 2)
    assert s.score == SCORE_ABSTAIN
    assert SCORE_WRONG < SCORE_ABSTAIN < SCORE_CORRECT_UNCITED
    assert s.abstained and not s.correct


def test_abstention_is_case_insensitive():
    assert score_answer(q(), "unknown", [], 0, 1).abstained


def test_break_even_accuracy_is_low_enough_to_reward_trying():
    """If abstaining paid too well the whole field would abstain. Guessing must win as soon
    as the harness has better than a ~1-in-4 shot."""
    assert SCORE_ABSTAIN / SCORE_CORRECT_UNCITED <= 0.25
    assert SCORE_ABSTAIN / SCORE_CORRECT_CITED <= 0.15


def test_citing_a_trap_is_recorded():
    question = q(traps=("lab:0004",))
    s = score_answer(question, "Nengail", ["lab:0004"], 500, 6)
    assert s.cited_trap and s.score == SCORE_CORRECT_UNCITED


def test_running_out_is_scored_as_wrong_not_as_an_abstention():
    """Otherwise stalling until the step or token cap collects the abstention rate for
    free, and abstention stops being a decision the harness has to make."""
    s = unanswered_score(q(), 900, 40, "step_budget_exhausted")
    assert s.score == SCORE_WRONG
    assert not s.abstained and s.outcome == "step_budget_exhausted"


def test_duplicate_citations_do_not_inflate_precision():
    s = score_answer(q(), "Nengail", ["lab:0003", "lab:0003", "lab:9999"], 500, 6)
    assert s.citation_precision == pytest.approx(0.5)
