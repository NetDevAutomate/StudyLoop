"""Contract tests for the immutable, isolated E2E test world."""

from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

import pytest
from e2e._env import RunningServer, build_test_world, start_server


def test_world_ignores_poisoned_parent_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    poison = tmp_path / "poison"
    poison.mkdir()
    monkeypatch.setenv("HOME", str(poison))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(poison / "wrong.yaml"))
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(poison / "wrong-plans"))

    root = tmp_path / "world"
    world = build_test_world(root, port=18699)

    assert world.env["HOME"] == str(world.home)
    assert world.env["STUDYLOOP_CONFIG"] == str(world.config)
    assert world.env["STUDYLOOP_PLANS_DIR"] == str(world.plans)
    assert world.env["PATH"].split(":", maxsplit=1)[0] == str(Path(sys.prefix) / "bin")


def test_world_paths_are_under_its_temporary_root(tmp_path: Path) -> None:
    root = tmp_path / "world"
    world = build_test_world(root, port=18700, fake_agent=True)

    for path in (
        world.cwd,
        world.home,
        world.tmp_dir,
        world.vault,
        world.config,
        world.session_db,
        world.session_dir,
        world.plans,
    ):
        assert path.is_relative_to(world.root), path

    assert world.env["STUDYLOOP_TEST_AGENT"] == "1"
    assert world.base_url == "http://127.0.0.1:18700"


def test_world_canonicalises_a_root_with_a_symlinked_ancestor(tmp_path: Path) -> None:
    """macOS exposes its temporary directory through the /var -> /private/var alias."""
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    requested_root = alias / "world"

    world = build_test_world(requested_root, port=18704)

    assert world.root == requested_root.resolve()
    assert world.plans == world.root / "study-plans"
    assert world.env["STUDYLOOP_PLANS_DIR"] == str(world.plans)


def test_world_is_frozen_and_environment_is_read_only(tmp_path: Path) -> None:
    world = build_test_world(tmp_path / "world", port=18701)

    with pytest.raises(FrozenInstanceError):
        world.port = 9999  # type: ignore[misc]

    with pytest.raises(TypeError):
        world.env["HOME"] = "/poison"  # type: ignore[index]


def test_start_server_binds_world_to_process_launcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world = build_test_world(tmp_path / "world", port=18702)
    captured: dict[str, object] = {}

    def fake_start_web_server(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("e2e._env.start_web_server", fake_start_web_server)

    server = start_server(world)

    assert captured["args"] == (world.port,)
    assert captured["env"] is world.env
    assert captured["cwd"] == world.cwd
    assert server.world is world
    assert server.base_url == world.base_url


def test_running_server_waits_after_forced_kill(tmp_path: Path) -> None:
    world = build_test_world(tmp_path / "world", port=18703)
    process = Mock()
    process.wait.side_effect = [RuntimeError("termination timed out"), None]
    server = RunningServer(world=world, proc=process)

    server.stop()

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 2
