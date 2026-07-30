"""Referee behaviour, including the failure-attribution contract.

The distinction under test: a bad SUBMISSION must produce a written result with the worst
finite score, while missing or wrong GROUND TRUTH must raise so that no result.json is written
and the platform attributes the failure to the referee rather than to the miner.
"""

import pytest

from apex_sdk.gym_v1.client import PlayerError
from apex_sdk.gym_v1.referee import RefereeContext
from env.metric import MAX_ROW_LOSS, NUM_CLASSES, UNIFORM_LOGLOSS
from referee import OttoReferee

UNIFORM = [1.0 / NUM_CLASSES] * NUM_CLASSES
LABELS = "id,target\n1,Class_1\n2,Class_5\n3,Class_9\n"


@pytest.fixture
def labels_file(tmp_path, monkeypatch):
    p = tmp_path / "test_labels.csv"
    p.write_text(LABELS)
    # verify=False: these are synthetic labels, not the pinned ground truth.
    import env.labels as labels_mod

    monkeypatch.setattr(labels_mod, "TEST_LABELS_PATH", str(p))
    monkeypatch.setattr(labels_mod, "EXPECTED_TEST_ROWS", 3)
    monkeypatch.setattr(labels_mod, "TEST_LABELS_SHA256", __import__("hashlib").sha256(LABELS.encode()).hexdigest())
    return p


class _StubPlayer:
    """Stands in for a PlayerClient: records calls and replays scripted responses."""

    def __init__(self, rows=None, fail_on=None):
        self.rows = rows
        self.fail_on = fail_on
        self.acts = 0

    def reset(self, **kwargs):
        self.config = kwargs.get("config", {})
        if self.fail_on == "reset":
            raise PlayerError("/reset returned 500, expected 204")

    def act(self, observation, deadline_ms):
        self.acts += 1
        if self.fail_on == "act":
            raise PlayerError("/act returned 500, expected 200")
        if self.fail_on == "shape":
            return "not a list"
        if self.fail_on == "short":
            return [self.rows] * (len(observation) - 1)
        return [self.rows for _ in observation]


def _ctx(batch_size=4096):
    return RefereeContext(
        match_id="m",
        seed=1234,
        config={"batch_size": batch_size, "deadline_ms": 5000},
        player_urls=["http://p"],
        num_players=1,
    )


def test_uniform_submission_scores_ln_nine(labels_file):
    result = OttoReferee().play_game(_ctx(), [_StubPlayer(rows=UNIFORM)])
    assert result.raw_scores[0] == pytest.approx(UNIFORM_LOGLOSS)
    assert result.terminal_reason == "scored"
    assert result.winner == 0
    assert result.steps == 3
    assert result.metadata["num_invalid_rows"] == 0


def test_batching_covers_every_row_exactly_once(labels_file):
    player = _StubPlayer(rows=UNIFORM)
    result = OttoReferee().play_game(_ctx(batch_size=2), [player])
    assert player.acts == 2  # 3 rows at batch_size 2
    assert result.steps == 3
    assert result.raw_scores[0] == pytest.approx(UNIFORM_LOGLOSS)


def test_referee_tells_the_player_the_expected_row_count(labels_file):
    player = _StubPlayer(rows=UNIFORM)
    OttoReferee().play_game(_ctx(), [player])
    assert player.config["num_test_rows"] == 3


def test_seed_drives_nothing_but_is_recorded(labels_file):
    # Same submission, different seeds -> bit-identical score. sigma_round is exactly 0.
    a = OttoReferee().play_game(_ctx(), [_StubPlayer(rows=UNIFORM)])
    ctx_b = RefereeContext(
        match_id="m", seed=999999, config={"batch_size": 4096}, player_urls=["http://p"], num_players=1
    )
    b = OttoReferee().play_game(ctx_b, [_StubPlayer(rows=UNIFORM)])
    assert a.raw_scores == b.raw_scores
    assert a.metadata["seed"] == 1234 and b.metadata["seed"] == 999999


def test_invalid_rows_are_gated_and_counted(labels_file):
    result = OttoReferee().play_game(_ctx(), [_StubPlayer(rows=[0.0] * NUM_CLASSES)])
    assert result.metadata["gates"] == {"row_sum": 3}
    assert result.raw_scores[0] == pytest.approx(MAX_ROW_LOSS)


def test_missing_row_is_not_silently_given_a_uniform_score(labels_file):
    # None must cost MAX_ROW_LOSS, not ln(9): substituting uniform would pay a miner for rows
    # they never predicted, which is better than many honest guesses.
    player = _StubPlayer(rows=None)
    result = OttoReferee().play_game(_ctx(), [player])
    assert result.metadata["gates"] == {"missing_row": 3}
    assert result.raw_scores[0] == pytest.approx(MAX_ROW_LOSS)


@pytest.mark.parametrize(
    "fail_on,reason",
    [("reset", "reset_failed"), ("act", "player_error"), ("shape", "bad_batch_shape"), ("short", "bad_batch_shape")],
)
def test_submission_failures_write_a_result_with_the_worst_score(labels_file, fail_on, reason):
    result = OttoReferee().play_game(_ctx(), [_StubPlayer(rows=UNIFORM, fail_on=fail_on)])
    assert result.terminal_reason == reason
    assert result.raw_scores == [MAX_ROW_LOSS]
    assert result.winner == -1
    assert result.metadata["failure"] == reason


def test_missing_ground_truth_raises_and_writes_no_result(tmp_path, monkeypatch):
    import env.labels as labels_mod

    monkeypatch.setattr(labels_mod, "TEST_LABELS_PATH", str(tmp_path / "absent.csv"))
    with pytest.raises(RuntimeError, match="not mounted"):
        OttoReferee().play_game(_ctx(), [_StubPlayer(rows=UNIFORM)])


def test_hash_mismatched_ground_truth_raises(tmp_path, monkeypatch):
    p = tmp_path / "test_labels.csv"
    p.write_text(LABELS)
    import env.labels as labels_mod

    monkeypatch.setattr(labels_mod, "TEST_LABELS_PATH", str(p))
    monkeypatch.setattr(labels_mod, "TEST_LABELS_SHA256", "f" * 64)
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        OttoReferee().play_game(_ctx(), [_StubPlayer(rows=UNIFORM)])


def test_wrong_row_count_ground_truth_raises(tmp_path, monkeypatch):
    p = tmp_path / "test_labels.csv"
    p.write_text(LABELS)
    import env.labels as labels_mod

    monkeypatch.setattr(labels_mod, "TEST_LABELS_PATH", str(p))
    monkeypatch.setattr(labels_mod, "TEST_LABELS_SHA256", __import__("hashlib").sha256(LABELS.encode()).hexdigest())
    monkeypatch.setattr(labels_mod, "EXPECTED_TEST_ROWS", 18559)
    with pytest.raises(RuntimeError, match="row count"):
        OttoReferee().play_game(_ctx(), [_StubPlayer(rows=UNIFORM)])


def test_metadata_never_leaks_per_row_losses(labels_file):
    result = OttoReferee().play_game(_ctx(), [_StubPlayer(rows=UNIFORM)])
    # A per-row loss vector is a partial answer key. It must never be revealed.
    assert "losses" not in result.metadata
    assert not any(isinstance(v, list) for v in result.metadata.values())
