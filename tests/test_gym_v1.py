"""Contract tests for the gym_v1 player server and client.

The load-bearing property here is FAILURE ATTRIBUTION. A player that misbehaves is a
SUBMISSION failure and must reach the referee as a PlayerError it can catch and score. If a
player exception instead escapes as a raw transport error, the referee crashes, writes no
result.json, and the platform blames the REFEREE — scoring 0 for everyone and pinning the
fault on the competition instead of the bad submission.
"""

import threading
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from apex_sdk.gym_v1 import Player
from apex_sdk.gym_v1.client import PlayerClient, PlayerError
from apex_sdk.gym_v1.player import _make_handler


class _Scripted(Player):
    """A player that fails exactly where the test wants it to."""

    def __init__(self, fail_on: str | None = None, action: Any = None) -> None:
        self.fail_on = fail_on
        self.action = action if action is not None else [1.0, 2.0]

    def reset(self, match_id: str, player_index: int, seed: int, config: dict[str, Any]) -> None:
        if self.fail_on == "reset":
            raise ValueError("submission has 3 rows, expected 4")

    def act(self, observation: Any, deadline_ms: int) -> Any:
        if self.fail_on == "act":
            raise RuntimeError("boom")
        return self.action


@pytest.fixture
def serve_player():
    servers: list[ThreadingHTTPServer] = []

    def _start(player: Player) -> PlayerClient:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(player, "/health"))
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return PlayerClient(f"http://127.0.0.1:{server.server_address[1]}")

    yield _start
    for s in servers:
        s.shutdown()
        s.server_close()


def test_healthy_player_round_trips(serve_player):
    client = serve_player(_Scripted(action=[0.5, 0.5]))
    assert client.health() is True
    client.wait_until_ready(timeout_s=5)
    client.reset(match_id="m", player_index=0, seed=0, config={})
    assert client.act(observation=[1], deadline_ms=1000) == [0.5, 0.5]


def test_player_exception_in_reset_is_a_player_error(serve_player):
    # Previously the exception escaped the handler, the connection was dropped, and the caller
    # saw http.client.RemoteDisconnected — not a PlayerError.
    client = serve_player(_Scripted(fail_on="reset"))
    with pytest.raises(PlayerError) as ei:
        client.reset(match_id="m", player_index=0, seed=0, config={})
    assert "500" in str(ei.value)


def test_player_exception_in_act_is_a_player_error(serve_player):
    client = serve_player(_Scripted(fail_on="act"))
    with pytest.raises(PlayerError) as ei:
        client.act(observation=[1], deadline_ms=1000)
    assert "500" in str(ei.value)


def test_dead_player_is_a_player_error(serve_player):
    client = serve_player(_Scripted())
    client.wait_until_ready(timeout_s=5)
    # Nothing is listening on this port; a connection refusal must still be a PlayerError.
    dead = PlayerClient("http://127.0.0.1:1")
    assert dead.health() is False
    with pytest.raises(PlayerError):
        dead.act(observation=[1], deadline_ms=500)


def test_malformed_referee_request_is_a_400(serve_player):
    # A missing required field is the referee's bug, not the player's, so it must not be
    # reported as a 500 (which would be attributed to the submission).
    client = serve_player(_Scripted())
    status, _ = client._post("/reset", {"match_id": "m"}, timeout_s=5)
    assert status == 400
