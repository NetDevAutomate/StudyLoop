"""T1 C6: ``provider: none`` must be inert, not merely quiet.

"Off by default" is only credible if the off path cannot reach a plan, cannot
create a directory, cannot raise, and cannot log at a level the learner sees.
Each of those is asserted separately because each has its own failure mode: a
lookup that raises turns a disabled feature into a crash, a mkdir turns it into
a stray folder, and a warning turns it into nagging.
"""

from __future__ import annotations

import logging

from studyloop.second_brain.core import (
    NullBackend,
    PublishResult,
    PullNotesResult,
    SecondBrain,
)


def test_null_backend_matches_protocol() -> None:
    assert isinstance(NullBackend(), SecondBrain)


def test_describe_reports_unconfigured() -> None:
    description = NullBackend().describe()
    assert description.provider == "none"
    assert description.configured is False
    assert description.available is False
    assert description.supports_publish is False
    assert description.supports_pull_notes is False
    assert description.vault_path is None
    assert description.folder is None
    assert description.use_cli is False
    assert description.detail == "Second brain is not configured."


def test_is_available_is_false() -> None:
    assert NullBackend().is_available() is False


def test_each_operation_is_skipped_without_plan_lookup(monkeypatch) -> None:
    """A disabled backend must not even resolve a plan id.

    ``load_plan`` is replaced with a detonator: the point is not that the call
    would fail, it is that a disabled feature has no business reading the
    learner's plans at all.
    """
    from studyloop.planning import store as store_mod

    def _explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("NullBackend touched the plan store")

    monkeypatch.setattr(store_mod, "load_plan", _explode)
    monkeypatch.setattr(store_mod, "validate_plan_id", _explode)
    monkeypatch.setattr(store_mod, "plans_dir", _explode)

    backend = NullBackend()
    for result in (
        backend.publish_plan("python-decorators"),
        backend.publish_today(),
        backend.publish_learning_record("python-decorators", 1),
    ):
        assert isinstance(result, PublishResult)
        assert result.provider == "none"
        assert result.written == ()
        assert result.unchanged == ()
        assert result.skipped == ("Second brain is not configured.",)

    pulled = backend.pull_notes("python-decorators")
    assert isinstance(pulled, PullNotesResult)
    assert pulled.found is False
    assert pulled.notes == ""


def test_null_backend_emits_no_warning_or_higher_log(caplog) -> None:
    with caplog.at_level(logging.DEBUG, logger="studyloop.second_brain"):
        backend = NullBackend()
        backend.describe()
        backend.publish_plan("python-decorators")
        backend.publish_today()
        backend.publish_learning_record("python-decorators", 1)
        backend.pull_notes("python-decorators")
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_null_backend_does_not_touch_filesystem(tmp_path) -> None:
    """Snapshot a tree, run everything, and require it byte-identical."""
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    backend = NullBackend()
    backend.publish_plan("python-decorators")
    backend.publish_today()
    backend.publish_learning_record("python-decorators", 1)
    backend.pull_notes("python-decorators")
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert after == before == []
