"""A legacy-sync refusal is a refusal, not a traceback.

``sync_to_full`` and ``prune_hot`` raise ``LegacySyncRefused`` (a ``RuntimeError``)
when the database holds any ``context_*`` row (``replication/legacy.py``). Anyone
who has parked a topic has one (``parking.py`` seeds ``context_board_columns``),
and every current-schema ``delete`` writes a tombstone row. The ``sync-full`` and
``prune`` commands caught only ``ValueError`` and ``FileNotFoundError``, so the
learners the ``archive`` deprecation notice sends to ``sync-full`` were shown a
Python stack trace instead of the refusal's own message (plan 4, lane N finding;
ADR-0016 amendment).
"""

from __future__ import annotations

from typer.testing import CliRunner

from agent_session_tools.maintenance import app
from agent_session_tools.replication.legacy import MESSAGE, LegacySyncRefused

runner = CliRunner()


def _refuse(*_args, **_kwargs):
    raise LegacySyncRefused(MESSAGE)


class TestLegacyRefusalIsReported:
    def test_sync_full_prints_the_refusal_and_exits_1(self, monkeypatch) -> None:
        import agent_session_tools.tiering as tiering

        monkeypatch.setattr(tiering, "acquire_sync_lock", lambda: True)
        monkeypatch.setattr(tiering, "release_sync_lock", lambda: None)
        monkeypatch.setattr(tiering, "sync_to_full", _refuse)

        result = runner.invoke(app, ["sync-full"])

        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"refusal escaped as {type(result.exception).__name__}: {result.output}"
        )
        assert (
            "❌" in result.output and "Legacy SQL sync cannot transfer" in result.output
        )
        assert "Traceback" not in result.output

    def test_prune_prints_the_refusal_and_exits_1(self, monkeypatch) -> None:
        import agent_session_tools.tiering as tiering

        monkeypatch.setattr(tiering, "prune_hot", _refuse)

        result = runner.invoke(app, ["prune", "--days", "30"])

        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"refusal escaped as {type(result.exception).__name__}: {result.output}"
        )
        assert (
            "❌" in result.output and "Legacy SQL sync cannot transfer" in result.output
        )
        assert "Traceback" not in result.output

    def test_snapshot_reports_a_runtime_refusal_the_same_way(self, monkeypatch) -> None:
        import agent_session_tools.tiering as tiering

        monkeypatch.setattr(tiering, "create_snapshot", _refuse)

        result = runner.invoke(app, ["snapshot"])

        assert result.exit_code == 1, result.output
        assert result.exception is None or isinstance(result.exception, SystemExit), (
            f"refusal escaped as {type(result.exception).__name__}: {result.output}"
        )
        assert "❌" in result.output
