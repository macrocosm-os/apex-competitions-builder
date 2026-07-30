"""The tool surface and the budgets — the contract a harness is written against.

The load-bearing property under test throughout: document text NEVER reaches the harness.
Every observation the environment returns is checked for it.
"""

from __future__ import annotations

import json
import threading

import pytest

from env.model import BaseModel
from env.tools import MAX_SEARCH_K, Budget, Episode
from env.world import generate_world
from tools import stub_model


@pytest.fixture(scope="module")
def stub_url():
    server = stub_model.serve(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def ep(stub_url):
    world = generate_world(seed=42, num_questions=14)
    model = BaseModel(base_url=stub_url, model="stub", temperature=0.0, max_output_tokens=128)
    budget = Budget(tokens_remaining=20_000, max_steps_per_question=10, max_context_tokens=400)
    episode = Episode(world, model, budget)
    obs = episode.start_question(world.questions[0], questions_remaining=13)
    return episode, obs


def test_first_observation_carries_the_question_and_the_budgets(ep):
    _, obs = ep
    assert obs["question"] and obs["question_id"] == "q000"
    assert obs["tokens_remaining"] == 20_000 and obs["steps_remaining"] == 10
    assert obs["context"] == {"doc_ids": [], "tokens": 0}


def test_search_returns_metadata_but_never_document_text(ep):
    episode, obs = ep
    obs, done = episode.step({"tool": "search", "query": "Institute", "k": 5}, 13)
    assert not done
    results = obs["last"]["results"]
    assert results and len(results) <= 5
    for r in results:
        assert set(r) == {"doc_id", "title", "source", "revised", "est_tokens", "bm25"}
        body = episode.world.documents[r["doc_id"]].text
        assert body not in json.dumps(obs), "document text leaked into an observation"


def test_add_and_drop_track_the_buffer(ep):
    episode, _ = ep
    doc_id = next(iter(episode.world.documents))
    obs, _ = episode.step({"tool": "add", "doc_ids": [doc_id]}, 13)
    assert obs["context"]["doc_ids"] == [doc_id] and obs["context"]["tokens"] > 0
    obs, _ = episode.step({"tool": "drop", "doc_ids": [doc_id]}, 13)
    assert obs["context"] == {"doc_ids": [], "tokens": 0}


def test_add_is_idempotent_and_preserves_order(ep):
    episode, _ = ep
    a, b = list(episode.world.documents)[:2]
    episode.step({"tool": "add", "doc_ids": [a, b]}, 13)
    obs, _ = episode.step({"tool": "add", "doc_ids": [a]}, 13)
    assert obs["context"]["doc_ids"] == [a, b]


def test_context_cap_rejects_the_whole_add_rather_than_truncating(ep):
    """Silent truncation would make the score depend on a rule the harness cannot see."""
    episode, _ = ep
    many = list(episode.world.documents)[:60]
    obs, _ = episode.step({"tool": "add", "doc_ids": many}, 13)
    assert obs["last"]["type"] == "error" and "limit" in obs["last"]["error"]
    assert obs["context"]["doc_ids"] == []


def test_ask_returns_a_completion_and_charges_the_pool(ep):
    episode, _ = ep
    doc_id = next(d for d in episode.world.documents if d.startswith("lab:"))
    episode.step({"tool": "add", "doc_ids": [doc_id]}, 13)
    before = episode.budget.tokens_remaining
    obs, _ = episode.step({"tool": "ask", "instruction": "Report the city it is located in."}, 13)
    last = obs["last"]
    assert last["type"] == "ask" and last["completion"]
    assert last["tokens_spent"] > 0
    assert episode.budget.tokens_remaining == before - last["tokens_spent"]
    assert obs["tokens_remaining"] == episode.budget.tokens_remaining


def test_ask_is_the_only_channel_from_corpus_to_harness(ep):
    """The whole design rests on this: with no documents in the buffer the model has
    nothing to report, so a harness cannot read the corpus by any other route."""
    episode, _ = ep
    obs, _ = episode.step({"tool": "ask", "instruction": "Report the city it is located in."}, 13)
    assert "No documents" in obs["last"]["completion"]


def test_ask_is_refused_rather_than_overspending_the_pool(ep):
    episode, _ = ep
    episode.budget.tokens_remaining = 5
    obs, _ = episode.step({"tool": "ask", "instruction": "Report the city."}, 13)
    assert obs["last"]["type"] == "error" and "remain" in obs["last"]["error"]
    assert episode.budget.tokens_remaining == 5


def test_a_harness_cannot_raise_the_output_ceiling(ep):
    episode, _ = ep
    doc_id = next(d for d in episode.world.documents if d.startswith("lab:"))
    episode.step({"tool": "add", "doc_ids": [doc_id]}, 13)
    obs, _ = episode.step(
        {"tool": "ask", "instruction": "Report the city it is located in.", "max_output_tokens": 999_999}, 13
    )
    assert obs["last"]["type"] == "ask"
    assert obs["last"]["completion_tokens"] <= episode.model.max_output_tokens


def test_answer_ends_the_question(ep):
    episode, _ = ep
    obs, done = episode.step({"tool": "answer", "text": "Nengail", "citations": ["lab:0001"]}, 13)
    assert done and episode.run.answered
    assert episode.run.answer_text == "Nengail" and episode.run.citations == ["lab:0001"]
    assert obs["last"]["type"] == "answer"


@pytest.mark.parametrize(
    "action",
    [
        None,
        "search",
        {"tool": "nope"},
        {"tool": "search"},
        {"tool": "search", "query": ""},
        {"tool": "search", "query": "x", "k": 0},
        {"tool": "search", "query": "x", "k": MAX_SEARCH_K + 1},
        {"tool": "search", "query": "x", "k": True},
        {"tool": "add", "doc_ids": []},
        {"tool": "add", "doc_ids": ["nope:9999"]},
        {"tool": "add", "doc_ids": [1]},
        {"tool": "ask", "instruction": ""},
        {"tool": "ask", "instruction": "x", "max_output_tokens": 0},
        {"tool": "answer", "text": 42},
        {"tool": "answer", "text": "x", "citations": [7]},
    ],
)
def test_malformed_actions_are_typed_errors_not_crashes_or_silent_noops(ep, action):
    episode, _ = ep
    obs, done = episode.step(action, 13)
    assert not done
    assert obs["last"]["type"] == "error" and obs["last"]["error"]
    assert episode.run.steps == 1  # an error still costs a step


def test_step_cap_terminates_the_question(ep):
    episode, _ = ep
    for _ in range(9):
        obs, done = episode.step({"tool": "search", "query": "Institute"}, 13)
        assert not done
    obs, done = episode.step({"tool": "search", "query": "Institute"}, 13)
    assert done and episode.run.stop_reason == "step_budget_exhausted"
    assert not episode.run.answered


def test_citations_are_capped(ep):
    episode, _ = ep
    episode.step({"tool": "answer", "text": "x", "citations": [f"lab:{i:04d}" for i in range(50)]}, 13)
    assert len(episode.run.citations) == 20


def test_starting_a_question_clears_the_buffer_but_not_the_pool(ep):
    episode, _ = ep
    doc_id = next(d for d in episode.world.documents if d.startswith("lab:"))
    episode.step({"tool": "add", "doc_ids": [doc_id]}, 13)
    episode.step({"tool": "ask", "instruction": "Report the city it is located in."}, 13)
    spent = 20_000 - episode.budget.tokens_remaining
    assert spent > 0
    obs = episode.start_question(episode.world.questions[1], questions_remaining=12)
    assert obs["context"] == {"doc_ids": [], "tokens": 0}
    assert obs["tokens_remaining"] == 20_000 - spent, "the token pool is shared across questions"


def test_system_prompt_is_the_harness_s_to_control(ep):
    """Defending against a document that imitates instructions is the harness's job, so it
    has to be able to set the system prompt."""
    episode, _ = ep
    obs, _ = episode.step({"tool": "ask", "instruction": "Report the city.", "system": "Custom."}, 13)
    assert obs["last"]["type"] == "ask"
    obs, _ = episode.step({"tool": "ask", "instruction": "Report the city.", "system": 7}, 13)
    assert obs["last"]["type"] == "error"
