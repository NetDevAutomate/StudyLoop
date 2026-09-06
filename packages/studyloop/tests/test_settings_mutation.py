from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import pytest
import yaml

import studyloop.settings as settings

if TYPE_CHECKING:
    from pathlib import Path


def _blocking_process_mutation(
    config_path: str,
    key: str,
    entered: Any,
    release: Any,
) -> None:
    os.environ["STUDYLOOP_CONFIG"] = config_path

    def add_key(raw: dict[str, object]) -> dict[str, object]:
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("mutation release was not signalled")
        raw[key] = True
        return raw

    settings.mutate_raw_config(add_key)


def test_mutate_raw_config_preserves_unrelated_keys(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"unrelated": {"kept": True}}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    def add_browser(raw: dict[str, object]) -> dict[str, object]:
        raw["browser"] = "safari"
        return raw

    written = settings.mutate_raw_config(add_browser)

    assert written == config_path
    assert yaml.safe_load(config_path.read_text()) == {
        "unrelated": {"kept": True},
        "browser": "safari",
    }


def test_invalid_mutation_leaves_destination_unchanged(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    original = yaml.dump({"unrelated": {"kept": True}}).encode()
    config_path.write_bytes(original)
    config_path.chmod(0o600)
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    def select_invalid_provider(raw: dict[str, object]) -> dict[str, object]:
        raw["second_brain"] = {"provider": "invalid"}
        return raw

    with pytest.raises(settings.ConfigError):
        settings.mutate_raw_config(select_invalid_provider)

    assert config_path.read_bytes() == original
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_concurrent_mutations_serialize_and_reread_after_lock(tmp_path: Path, monkeypatch) -> None:
    import multiprocessing

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"unrelated": "kept"}))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    context = multiprocessing.get_context("spawn")
    first_entered = context.Event()
    first_release = context.Event()
    second_entered = context.Event()
    second_release = context.Event()
    second_release.set()
    first = context.Process(
        target=_blocking_process_mutation,
        args=(str(config_path), "first", first_entered, first_release),
    )
    second = context.Process(
        target=_blocking_process_mutation,
        args=(str(config_path), "second", second_entered, second_release),
    )

    first.start()
    assert first_entered.wait(timeout=5)
    second.start()
    serialized = not second_entered.wait(timeout=0.25)
    first_release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert serialized
    assert first.exitcode == 0
    assert second.exitcode == 0
    assert yaml.safe_load(config_path.read_text()) == {
        "unrelated": "kept",
        "first": True,
        "second": True,
    }


def test_replacement_failure_preserves_destination_and_removes_temp_file(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.yaml"
    original = yaml.dump({"unrelated": "kept"}).encode()
    config_path.write_bytes(original)
    config_path.chmod(0o600)
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    def add_browser(raw: dict[str, object]) -> dict[str, object]:
        raw["browser"] = "safari"
        return raw

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(settings.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        settings.mutate_raw_config(add_browser)

    assert config_path.read_bytes() == original
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(".config.yaml.*.tmp")) == []


def test_temp_file_is_flushed_and_synced_before_replacement(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))
    events: list[str] = []
    real_replace = os.replace

    def record_fsync(_file_descriptor: int) -> None:
        events.append("fsync")

    def record_replace(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(settings.os, "fsync", record_fsync)
    monkeypatch.setattr(settings.os, "replace", record_replace)

    def add_browser(raw: dict[str, object]) -> dict[str, object]:
        raw["browser"] = "safari"
        return raw

    settings.mutate_raw_config(add_browser)

    assert events == ["fsync", "replace"]


def test_mutation_preserves_existing_mode_and_creates_new_file_as_owner_only(
    tmp_path: Path, monkeypatch
) -> None:
    existing_path = tmp_path / "existing.yaml"
    existing_path.write_text("topics: []\n")
    existing_path.chmod(0o400)
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(existing_path))

    def add_browser(raw: dict[str, object]) -> dict[str, object]:
        raw["browser"] = "safari"
        return raw

    settings.mutate_raw_config(add_browser)

    new_path = tmp_path / "new.yaml"
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(new_path))
    settings.mutate_raw_config(add_browser)

    assert existing_path.stat().st_mode & 0o777 == 0o400
    assert new_path.stat().st_mode & 0o777 == 0o600


def test_write_raw_config_delegates_to_shared_mutation_owner(tmp_path: Path, monkeypatch) -> None:
    expected_path = tmp_path / "config.yaml"
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(expected_path))
    results: list[dict[str, object]] = []

    def capture_mutation(mutator: Any) -> Path:
        results.append(mutator({"stale": True}))
        return expected_path

    monkeypatch.setattr(settings, "mutate_raw_config", capture_mutation)

    written = settings.write_raw_config({"browser": "safari"})

    assert written == expected_path
    assert results == [{"browser": "safari"}]
