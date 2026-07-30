"""World-generator invariants. These are the well-posedness guarantees the competition
rests on: if any of them breaks, questions stop having exactly one defensible answer and
the scores stop meaning anything.
"""

from __future__ import annotations

import re

import pytest

from env.world import (
    AUTHORITATIVE_SOURCE,
    RELATIONS,
    TEMPLATES,
    TRAP_KINDS,
    generate_world,
)


@pytest.fixture(scope="module")
def world():
    return generate_world(seed=1234, num_questions=70)


def test_deterministic_from_seed(world):
    again = generate_world(seed=1234, num_questions=70)
    assert [d.render() for d in again.documents.values()] == [d.render() for d in world.documents.values()]
    assert [(q.question_id, q.text, q.answer, q.traps) for q in again.questions] == [
        (q.question_id, q.text, q.answer, q.traps) for q in world.questions
    ]


def test_different_seeds_give_different_worlds():
    a, b = generate_world(seed=1, num_questions=7), generate_world(seed=2, num_questions=7)
    assert [q.text for q in a.questions] != [q.text for q in b.questions]


def test_answer_is_stated_by_the_last_gold_document(world):
    """The gold chain must actually support the answer — every hop's value has to appear
    in the document credited with stating it."""
    for q in world.questions:
        for hop in q.chain:
            if hop.relation == "index":
                continue
            doc = world.documents[hop.doc_id]
            pattern = RELATIONS[hop.relation][0]
            m = pattern.search(doc.text)
            assert m, f"{q.question_id}: {doc.doc_id} does not state {hop.relation}"
            assert m.group(1) == hop.value, f"{q.question_id}: {doc.doc_id} states {m.group(1)}, chain says {hop.value}"
        assert q.answer == q.chain[q.hops - 1].value


def test_chain_is_forward_functional_so_the_answer_is_unique(world):
    """Each hop's document must state its relation exactly once. A second statement would
    be a second answer."""
    for q in world.questions:
        for hop in q.chain:
            if hop.relation == "index":
                continue
            doc = world.documents[hop.doc_id]
            assert len(RELATIONS[hop.relation][0].findall(doc.text)) == 1


def test_entry_entity_appears_in_the_question(world):
    """The question has to name its entry point, or it is unanswerable rather than hard."""
    for q in world.questions:
        entry = world.documents[q.chain[0].doc_id]
        name = entry.title.replace("Dr. ", "").replace("The ", "").replace(" Report", "")
        assert name in q.text, f"{q.question_id} does not name its entry entity {name}"


def test_intermediate_entities_are_not_in_the_question(world):
    """Iterative retrieval must be FORCED: if a later hop's entity were named in the
    question, a harness could jump straight to the answer document and the whole agent
    loop would be optional."""
    for q in world.questions:
        for hop in q.chain[:-1]:
            if hop.relation in ("index", "amount"):
                continue
            assert hop.value not in q.text, f"{q.question_id} leaks intermediate {hop.value}"


def test_all_templates_are_exercised(world):
    assert {q.template for q in world.questions} == set(TEMPLATES)


def test_traps_are_indistinguishable_by_identity(world):
    """A trap must not be filterable by doc_id or title. If it were, the whole adversarial
    axis would collapse into a one-line filter."""
    trapped = [q for q in world.questions if q.trap_doc_ids]
    assert trapped, "trap_rate produced no traps"
    for q in trapped:
        trap = world.documents[q.trap_doc_ids[0]]
        victim = world.documents[q.chain[q.trap_hop].doc_id]
        assert trap.title == victim.title
        assert trap.doc_id.split(":")[0] == victim.doc_id.split(":")[0]
        assert re.fullmatch(r"[a-z]+:\d{4}", trap.doc_id)


def test_traps_assert_a_wrong_value_of_the_right_type(world):
    for q in world.questions:
        if not q.trap_doc_ids:
            continue
        hop = q.chain[q.trap_hop]
        trap = world.documents[q.trap_doc_ids[0]]
        m = RELATIONS[hop.relation][0].search(trap.text)
        assert m, f"{q.question_id}: trap states nothing for {hop.relation}"
        assert m.group(1) != hop.value, f"{q.question_id}: trap agrees with the truth"


def test_stale_traps_are_older_and_authoritative(world):
    """`stale` is the trap provenance filtering cannot catch: it must look authoritative
    and be older, or it tests nothing new."""
    seen = False
    for q in world.questions:
        if q.traps != ("stale",):
            continue
        seen = True
        trap = world.documents[q.trap_doc_ids[0]]
        victim = world.documents[q.chain[q.trap_hop].doc_id]
        assert trap.source == AUTHORITATIVE_SOURCE
        assert trap.revised < victim.revised
    assert seen


def test_ambiguous_traps_defeat_both_cheap_rules_and_add_an_index(world):
    """`ambiguous` is the headroom trap: same source AND same date, so neither filtering
    nor recency resolves it, and a registry-index document is the only way through."""
    seen = False
    for q in world.questions:
        if q.traps != ("ambiguous",):
            continue
        seen = True
        trap = world.documents[q.trap_doc_ids[0]]
        victim = world.documents[q.chain[q.trap_hop].doc_id]
        assert trap.source == victim.source == AUTHORITATIVE_SOURCE
        assert trap.revised == victim.revised
        index_hops = [h for h in q.chain if h.relation == "index"]
        assert len(index_hops) == 1
        index_doc = world.documents[index_hops[0].doc_id]
        assert victim.doc_id in index_doc.text and trap.doc_id in index_doc.text
        # ...and the index must not be guessable from the question id, or detecting the
        # trap becomes free and the token cost the trap exists to impose disappears.
        assert q.question_id not in index_doc.doc_id
    assert seen


def test_contradictor_and_injection_traps_are_unreliable_sources(world):
    for q in world.questions:
        if q.traps and q.traps[0] in ("contradictor", "injection"):
            assert world.documents[q.trap_doc_ids[0]].source != AUTHORITATIVE_SOURCE


def test_injection_trap_carries_imperative_text(world):
    injections = [q for q in world.questions if q.traps == ("injection",)]
    assert injections
    for q in injections:
        assert "disregard" in world.documents[q.trap_doc_ids[0]].text.lower()


def test_every_trap_kind_appears_over_enough_questions():
    world = generate_world(seed=99, num_questions=140, trap_rate=1.0)
    assert {q.traps[0] for q in world.questions} == set(TRAP_KINDS)


def test_trap_rate_zero_is_clean():
    world = generate_world(seed=5, num_questions=14, trap_rate=0.0)
    assert all(not q.traps for q in world.questions)


def test_titles_are_unique_apart_from_deliberate_trap_duplicates(world):
    """Two entities sharing a title would let BM25 conflate them and could give a question
    a second defensible answer. Traps duplicate a title on purpose; nothing else may."""
    trap_ids = {d for q in world.questions for d in q.trap_doc_ids}
    titles = [
        d.title for d in world.documents.values() if d.doc_id not in trap_ids and not d.doc_id.startswith("index:")
    ]
    assert len(titles) == len(set(titles))


def test_every_hop_document_is_findable_by_its_entity_name(world):
    """The corpus must be navigable: once a harness knows an entity's name, searching for
    it has to surface that entity's document. Every hop depends on this."""
    for q in world.questions:
        for hop in q.chain:
            doc = world.documents[hop.doc_id]
            hits = [doc_id for doc_id, _ in world.index.search(doc.title, 8)]
            assert doc.doc_id in hits, f"{q.question_id}: {doc.doc_id} unreachable by its own title"


def test_dumping_the_raw_question_into_search_is_materially_worse(world):
    """A design property, asserted so it does not regress away: pasting the question into
    the index is a weak query, because the phrasing dilutes the one distinctive term. A
    harness has to extract the entity it wants first, which makes query formulation a real
    lever rather than a formality."""
    naive = sum(1 for q in world.questions if q.chain[0].doc_id not in [d for d, _ in world.index.search(q.text, 8)])
    targeted = sum(
        1
        for q in world.questions
        if q.chain[0].doc_id not in [d for d, _ in world.index.search(world.documents[q.chain[0].doc_id].title, 8)]
    )
    assert targeted == 0
    assert naive > 0


def test_search_is_stable_and_ranked(world):
    hits = world.index.search("Institute located in the city", 10)
    assert hits == world.index.search("Institute located in the city", 10)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


def test_search_handles_no_match(world):
    assert world.index.search("zzzznotaterminthecorpus", 5) == []
    assert world.index.search("   ", 5) == []
