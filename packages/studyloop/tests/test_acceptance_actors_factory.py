"""get_actor()/skip_reason(): the factory truth table and the skip-reason
matrix for missing env (lanes.json TESTS FIRST items).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.direct import DirectActor  # noqa: E402
from acceptance.actors.factory import KNOWN_ACTORS, get_actor, skip_reason  # noqa: E402
from acceptance.actors.gateway import GatewayActor  # noqa: E402
from acceptance.actors.harness import HarnessActor  # noqa: E402
from acceptance.actors.protocol import ActorError, LearnerActor  # noqa: E402
from acceptance.actors.scripted import ScriptedActor  # noqa: E402
from acceptance.turn_script import load_turn_script  # noqa: E402


def _script():
    return load_turn_script({"version": 1, "turns": [{"prompt": "hi"}]})


class TestFactoryTruthTable:
    """One row per known actor: get_actor() returns the right concrete
    type, and it structurally satisfies LearnerActor."""

    def test_scripted_returns_scripted_actor(self) -> None:
        actor = get_actor("scripted", turn_script=_script())
        assert isinstance(actor, ScriptedActor)
        assert isinstance(actor, LearnerActor)

    def test_gateway_returns_gateway_actor(self) -> None:
        env = {"LITELLM_API_KEY": "k", "STUDYLOOP_ACC_GATEWAY_MODEL": "m"}
        actor = get_actor("gateway", env=env)
        assert isinstance(actor, GatewayActor)
        assert isinstance(actor, LearnerActor)

    def test_direct_returns_direct_actor(self) -> None:
        env = {"OPENAI_API_KEY": "k"}
        actor = get_actor("direct", env=env)
        assert isinstance(actor, DirectActor)
        assert isinstance(actor, LearnerActor)

    def test_harness_returns_harness_actor(self, tmp_path: Path) -> None:
        env = {"STUDYLOOP_ACC_HARNESS_ACTOR_CMD": "sh /tmp/does-not-need-to-exist.sh"}
        actor = get_actor("harness", env=env, harness_socket_dir=tmp_path / "sock")
        assert isinstance(actor, HarnessActor)
        assert isinstance(actor, LearnerActor)

    def test_unknown_actor_is_a_loud_failure(self) -> None:
        with pytest.raises(ActorError, match="unknown actor"):
            get_actor("nonexistent")

    def test_known_actors_matches_every_row_above(self) -> None:
        assert {"scripted", "gateway", "direct", "harness"} == KNOWN_ACTORS

    def test_scripted_without_turn_script_is_a_loud_failure_not_a_skip(self) -> None:
        """Missing turn_script is a caller bug (nothing sets it via env),
        so get_actor() raises rather than silently building nothing."""
        with pytest.raises(ActorError):
            get_actor("scripted")

    def test_harness_without_socket_dir_is_a_loud_failure(self) -> None:
        env = {"STUDYLOOP_ACC_HARNESS_ACTOR_CMD": "sh /tmp/x.sh"}
        with pytest.raises(ActorError, match="socket"):
            get_actor("harness", env=env)


class TestSkipReasonMatrix:
    def test_unknown_actor_raises_instead_of_returning_a_skip_string(self) -> None:
        with pytest.raises(ActorError):
            skip_reason("nonexistent", env={})

    def test_scripted_skips_only_when_no_turn_script_given(self) -> None:
        assert skip_reason("scripted", env={}, turn_script=None) is not None
        assert skip_reason("scripted", env={}, turn_script=_script()) is None

    @pytest.mark.parametrize(
        ("env", "expect_skip"),
        [
            ({}, True),
            ({"LITELLM_API_KEY": "k"}, True),
            ({"STUDYLOOP_ACC_GATEWAY_MODEL": "m"}, True),
            ({"LITELLM_API_KEY": "k", "STUDYLOOP_ACC_GATEWAY_MODEL": "m"}, False),
        ],
    )
    def test_gateway_skip_matrix(self, env: dict, expect_skip: bool) -> None:
        reason = skip_reason("gateway", env=env)
        assert (reason is not None) is expect_skip
        if expect_skip:
            assert reason  # named, not an empty string

    @pytest.mark.parametrize(
        ("env", "expect_skip"),
        [
            ({}, True),
            ({"OPENAI_API_KEY": "k"}, False),
            ({"STUDYLOOP_ACC_DIRECT_PROVIDER": "anthropic"}, True),
            ({"STUDYLOOP_ACC_DIRECT_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "k"}, False),
        ],
    )
    def test_direct_skip_matrix(self, env: dict, expect_skip: bool) -> None:
        reason = skip_reason("direct", env=env)
        assert (reason is not None) is expect_skip

    def test_direct_unknown_provider_raises_not_skips(self) -> None:
        with pytest.raises(ActorError):
            skip_reason("direct", env={"STUDYLOOP_ACC_DIRECT_PROVIDER": "not-a-provider"})

    def test_harness_skips_when_command_missing(self) -> None:
        assert skip_reason("harness", env={}) is not None

    def test_harness_available_when_tmux_and_command_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/tmux")
        env = {"STUDYLOOP_ACC_HARNESS_ACTOR_CMD": "sh /tmp/x.sh"}
        assert skip_reason("harness", env=env) is None

    def test_harness_skips_when_tmux_missing_even_with_command_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda _name: None)
        env = {"STUDYLOOP_ACC_HARNESS_ACTOR_CMD": "sh /tmp/x.sh"}
        reason = skip_reason("harness", env=env)
        assert reason is not None
        assert "tmux" in reason
