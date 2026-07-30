"""Full-loop tests: real player HTTP, real referee, real scoring, stub model.

Also the exploit tests. Each one encodes a way the competition could be won without
doing the work, and asserts it does not pay.
"""

from __future__ import annotations

import textwrap
import threading
from pathlib import Path

import pytest

from apex_sdk.gym_v1 import RefereeContext
from apex_sdk.gym_v1.client import PlayerClient
from apex_sdk.gym_v1.player import _make_handler
from http.server import ThreadingHTTPServer

from player.launch import HarnessPlayer
from referee.referee import ResearchReferee
from tools import stub_model

BASELINE = str(Path(__file__).resolve().parent.parent / "baseline" / "submission.py")


class QuietReferee(ResearchReferee):
    """Same scorer; the trace does not go to /data, which does not exist under pytest."""

    def trace(self, event: dict) -> None:
        pass


@pytest.fixture(scope="module")
def model_env():
    server = stub_model.serve(0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    yield url
    server.shutdown()


@pytest.fixture
def run_episode(model_env, monkeypatch):
    monkeypatch.setenv("MODEL_BASE_URL", model_env)
    monkeypatch.setenv("MODEL_NAME", "stub")
    monkeypatch.setenv("MODEL_TEMPERATURE", "0")
    monkeypatch.setenv("MODEL_MAX_OUTPUT_TOKENS", "256")
    monkeypatch.setenv("MODEL_TOKEN_BUDGET", "200000")

    def _run(submission: str, seed: int = 7, num_questions: int = 14, **config):
        player = HarnessPlayer(submission)
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(player, "/health"))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            client = PlayerClient(url)
            ctx = RefereeContext(
                match_id=f"test-{seed}",
                seed=seed,
                config={"num_questions": num_questions, "token_pool": 200_000, **config},
                player_urls=[url],
                num_players=1,
            )
            return QuietReferee().play_game(ctx, [client]), client
        finally:
            server.shutdown()

    return _run


def write(tmp_path: Path, body: str, name: str = "submission.py") -> str:
    p = tmp_path / name
    p.write_text(textwrap.dedent(body))
    return str(p)


# --------------------------------------------------------------- the happy path


def test_baseline_completes_a_round_and_scores(run_episode):
    result, _ = run_episode(BASELINE)
    assert 0.0 < result.raw_scores[0] <= 1.0
    md = result.metadata
    assert md["num_questions"] == 14
    assert md["model_calls"] > 0 and md["tokens_spent"] > 0
    assert md["corpus_documents"] > 1000
    assert set(md["outcomes"]) <= {"correct", "correct_uncited", "wrong", "abstained", "step_budget_exhausted"}


def test_result_is_reproducible_for_the_same_seed(run_episode):
    a, _ = run_episode(BASELINE, seed=11)
    b, _ = run_episode(BASELINE, seed=11)
    assert a.raw_scores == b.raw_scores


def test_different_seeds_give_a_different_round(run_episode):
    a, _ = run_episode(BASELINE, seed=11)
    b, _ = run_episode(BASELINE, seed=12)
    assert [q["question_id"] for q in a.metadata["questions"]] == [q["question_id"] for q in b.metadata["questions"]]
    assert a.metadata["questions"] != b.metadata["questions"]


def test_metadata_exposes_the_diagnostics_a_designer_needs(run_episode):
    result, _ = run_episode(BASELINE)
    md = result.metadata
    assert md["by_hops"] and md["by_trap"]
    assert 0.0 <= md["token_utilisation"] <= 1.0
    assert all("template" in q and "traps" in q for q in md["questions"])


# --------------------------------------------------------------- exploits


def test_a_harness_that_never_calls_the_model_cannot_score(run_episode, tmp_path):
    """The load-bearing check, and the reason the model is a referee-side tool rather than a
    sidecar. A harness with no model calls has no channel to the corpus at all, so guessing
    is all it has left — and guessing has to lose to abstaining, which has to lose to
    actually reading."""
    guesser = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config): pass
            def act(self, observation):
                return {"tool": "answer", "text": "Aldoria", "citations": []}
        """,
        "guesser.py",
    )
    abstainer = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config): pass
            def act(self, observation):
                return {"tool": "answer", "text": "UNKNOWN", "citations": []}
        """,
        "abstainer.py",
    )
    g, _ = run_episode(guesser)
    a, _ = run_episode(abstainer)
    assert g.metadata["model_calls"] == 0 and a.metadata["model_calls"] == 0
    assert g.raw_scores[0] <= a.raw_scores[0]
    # ...and both must lose badly to the reference harness, which actually reads.
    b, _ = run_episode(BASELINE)
    assert b.raw_scores[0] > a.raw_scores[0] * 1.5


def test_citing_everything_does_not_beat_citing_accurately(run_episode, tmp_path):
    """A harness that answers correctly but sprays citations must not reach full marks."""
    sub = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config): pass
            def act(self, observation):
                ids = [f"lab:{i:04d}" for i in range(20)]
                return {"tool": "answer", "text": "UNKNOWN", "citations": ids}
        """,
    )
    result, _ = run_episode(sub)
    assert all(q["citation_precision"] < 0.5 for q in result.metadata["questions"])


def test_stalling_does_not_earn_the_abstention_rate(run_episode, tmp_path):
    sub = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config): pass
            def act(self, observation):
                return {"tool": "search", "query": "Institute", "k": 1}
        """,
    )
    result, _ = run_episode(sub, max_steps_per_question=6)
    assert result.raw_scores[0] == 0.0
    assert set(result.metadata["outcomes"]) == {"step_budget_exhausted"}


def test_the_token_pool_is_shared_so_a_greedy_harness_starves_itself(run_episode, tmp_path):
    """Burning the whole pool on question one has to cost the rest of the round."""
    sub = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config):
                self.first = not getattr(self, "seen", False)
                self.seen = True
                self.n = 0
            def act(self, observation):
                self.n += 1
                if self.first and self.n < 30:
                    hits = (observation.get("last") or {}).get("results") or []
                    if not hits:
                        return {"tool": "search", "query": "Institute research facility", "k": 20}
                    keep = [h["doc_id"] for h in hits[:3]]
                    if not observation["context"]["doc_ids"]:
                        return {"tool": "add", "doc_ids": keep}
                    return {"tool": "ask", "instruction": "Summarize every document at length.",
                            "max_output_tokens": 256}
                return {"tool": "answer", "text": "UNKNOWN", "citations": []}
        """,
    )
    result, _ = run_episode(sub, num_questions=14, token_pool=6000)
    md = result.metadata
    first = md["questions"][0]
    assert first["tokens_spent"] > sum(q["tokens_spent"] for q in md["questions"][1:])
    # The consequence, which is the actual point: the rest of the round got nothing.
    assert all(q["tokens_spent"] == 0 for q in md["questions"][1:])


def test_the_model_output_ceiling_is_enforced_end_to_end(run_episode, tmp_path):
    sub = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config): pass
            def act(self, observation):
                last = observation.get("last") or {}
                if last.get("type") == "ask":
                    self.spent = last["completion_tokens"]
                    return {"tool": "answer", "text": "UNKNOWN", "citations": []}
                return {"tool": "ask", "instruction": "Report the city.",
                        "max_output_tokens": 10 ** 9}
        """,
    )
    result, _ = run_episode(sub, num_questions=7)
    assert result.metadata["model_calls"] == 7


# --------------------------------------------------------------- submission failures


def test_a_submission_without_a_harness_class_fails_readiness(tmp_path):
    p = tmp_path / "submission.py"
    p.write_text("x = 1\n")
    assert not HarnessPlayer(str(p)).is_ready()


def test_a_submission_missing_a_method_fails_readiness(tmp_path):
    p = tmp_path / "submission.py"
    p.write_text("class Harness:\n    def act(self, o): return {}\n")
    player = HarnessPlayer(str(p))
    assert not player.is_ready()
    assert "start_question" in (player.load_error or "")


def test_a_submission_that_raises_on_import_fails_readiness(tmp_path):
    p = tmp_path / "submission.py"
    p.write_text("raise RuntimeError('boom')\n")
    assert not HarnessPlayer(str(p)).is_ready()


def test_a_harness_that_raises_is_attributed_to_the_submission(run_episode, tmp_path):
    """A crash must become a player_error the referee can attribute — never a referee
    failure, and never a silent zero that looks like a strategy."""
    sub = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config): pass
            def act(self, observation): raise ValueError("boom")
        """,
    )
    result, _ = run_episode(sub, num_questions=14)
    assert result.raw_scores[0] == 0.0
    assert set(result.metadata["outcomes"]) == {"player_error", "player_unreachable"}
    # ...and the referee must give up on a dead player rather than burn its whole timeout.
    assert result.metadata["outcomes"]["player_unreachable"] > 0


def test_a_harness_returning_garbage_actions_still_terminates(run_episode, tmp_path):
    sub = write(
        tmp_path,
        """
        class Harness:
            def start_question(self, config): pass
            def act(self, observation): return "not an action"
        """,
    )
    result, _ = run_episode(sub, num_questions=7, max_steps_per_question=5)
    assert result.raw_scores[0] == 0.0
