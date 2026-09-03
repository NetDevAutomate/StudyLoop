"""R-49 canary: prove the integration harness cannot reach a real HOME.

The harness fixes in this milestone redirect IPC-file paths via
``STUDYLOOP_SESSION_DIR``. This test does not trust that redirection alone --
it fakes ``HOME`` itself for the whole test (test process AND every spawned
subprocess, since ``HOME`` is an inherited env var), so even a *silent*
redirection failure that fell back to ``Path.home()`` would land in the fake
home, never the developer's real one.

A marker file is planted in the fake home's ``.config/studyloop`` before a
full study-session lifecycle runs there. The assertion is scoped to the four
session-state IPC files R-49 is about (session-state.json, session-topics.md,
session-parking.md, session-oneline.txt) plus the marker itself, not the
whole directory: ``studyloop.tmux``'s coordination lock (contentless, 0-byte)
is EXPECTED to appear as a new entry under the fake home -- it is a
legitimate write, not a leak. **Resolved (C12/R-49f, council):** the lock
path used to be hardcoded to ``~/.config/studyloop`` independent of any env
var (a real gap this canary once had to carve an exception around, "noted,
not fixed"); it now resolves lazily from ``session_state.SESSION_DIR``
(``tmux._lock_file()``), the SAME ``STUDYLOOP_SESSION_DIR``/``HOME``-derived
resolution every other IPC file in this test already depends on -- so its
appearance under the fake home is now the SAME correctness property this
canary proves for everything else, not a carved-out exception to it.

R-49b (M3 council, arbitration A2'): the checks above only prove the
*end state* of the directory is clean -- a file created and then removed
again before the assertions run (e.g. a temp file written and deleted as
part of some cleanup path) would leave no trace in either the named-file
existence check or the marker's own content/mtime check, yet a write into
the fake home's session directory would still have genuinely happened.
Closed with a directory-level before/after snapshot: every entry's
(inode, mtime) plus the directory's *own* mtime (which POSIX bumps on
every create/rename/unlink within it, even if the net set of names ends
up unchanged). A create-then-remove round-trip leaves the final listing
identical to before but the directory mtime different -- exactly the gap
the named-file check alone cannot see.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import ClassVar

import pytest

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from harness.agents import long_running_agent  # noqa: E402
from harness.study import StudySession  # noqa: E402

# The one entry allowed to appear during the run: M2-owned tmux.py's
# coordination lock (see module docstring) -- everything else appearing,
# or anything disappearing, or the directory's own mtime moving without a
# fully-explained listing change, is a canary failure.
_PERMITTED_NEW_ENTRIES = frozenset({"studyloop-tmux.lock"})


def _snapshot_dir(directory: Path) -> tuple[int, dict[str, tuple[int, int]]]:
    """(directory's own mtime_ns, {entry name: (inode, mtime_ns)})."""
    entries = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns) for p in directory.iterdir()}
    return directory.stat().st_mtime_ns, entries


def _assert_no_transient_writes(
    before: tuple[int, dict[str, tuple[int, int]]],
    after: tuple[int, dict[str, tuple[int, int]]],
    permitted_new: frozenset[str] = frozenset(),
) -> None:
    """Raise if `after` shows any write `before`/`after`-only name-existence
    checks would miss -- including a create-then-remove round-trip that
    leaves the final listing identical to `before`.

    R-49b: split out from the canary's inline assertions so this detection
    logic itself has a fast, non-integration unit test
    (`test_snapshot_comparison_detects_create_then_remove_round_trip`)
    independent of the real tmux harness.
    """
    before_dir_mtime_ns, before_entries = before
    after_dir_mtime_ns, after_entries = after

    added = set(after_entries) - set(before_entries)
    removed = set(before_entries) - set(after_entries)
    if removed:
        raise AssertionError(
            f"entries present before vanished after: {sorted(removed)} -- something deleted them"
        )
    if not added <= permitted_new:
        raise AssertionError(f"unexpected new entries appeared: {sorted(added - permitted_new)}")
    for name in set(before_entries) & set(after_entries):
        if before_entries[name] != after_entries[name]:
            raise AssertionError(
                f"{name!r} was replaced or modified in place (inode/mtime "
                "changed) even though it is still present under the same name"
            )
    if not added and after_dir_mtime_ns != before_dir_mtime_ns:
        raise AssertionError(
            "the directory's own mtime changed even though its final "
            "listing is identical to before -- something was created and "
            "removed again inside it"
        )


class TestR49Canary:
    # Class-scoped, not module-scoped: `TestSnapshotComparisonDetectsTransientWrites`
    # below is fast unit coverage of `_assert_no_transient_writes` itself and
    # must run without tmux and outside `-m integration` (see its docstring).
    pytestmark: ClassVar = [
        pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
        pytest.mark.integration,
    ]

    def test_study_session_lifecycle_never_touches_fake_home_marker(self, tmp_path, monkeypatch):
        fake_home = tmp_path / "fake-home"
        fake_config_dir = fake_home / ".config" / "studyloop"
        fake_config_dir.mkdir(parents=True)

        marker = fake_config_dir / "marker.txt"
        marker_content = "R-49 canary marker -- must survive byte-for-byte\n"
        marker.write_text(marker_content)
        before_mtime = marker.stat().st_mtime

        ipc_names = (
            "session-state.json",
            "session-topics.md",
            "session-parking.md",
            "session-oneline.txt",
        )

        before_dir_mtime_ns, before_entries = _snapshot_dir(fake_config_dir)

        # HOME (not just STUDYLOOP_SESSION_DIR) is faked for the whole test,
        # including the subprocess StudySession.start()/end_via_cli() spawn
        # (they build their env from os.environ.copy(), which monkeypatch.setenv
        # mutates in place) -- so even a fallback Path.home() call anywhere in
        # the chain resolves under the fake home, never the real one.
        monkeypatch.setenv("HOME", str(fake_home))

        work_dir = tmp_path / "study-work"
        work_dir.mkdir()
        with StudySession(work_dir) as session:
            agent_cmd = long_running_agent(work_dir)
            session.start("R-49 Canary Topic", agent_cmd=agent_cmd)
            session.assert_agent_running()
            session.end_via_cli()

        assert marker.read_text() == marker_content, (
            "marker content changed -- something wrote into the fake home's session dir"
        )
        assert marker.stat().st_mtime == before_mtime, "marker was rewritten"
        present_ipc_files = [name for name in ipc_names if (fake_config_dir / name).exists()]
        assert present_ipc_files == [], (
            f"the real IPC-file names R-49 is about appeared in the fake "
            f"home's .config/studyloop: {present_ipc_files}"
        )

        # R-49b: end-state-only checks above cannot see a create-then-remove
        # round-trip. A directory-level snapshot can.
        before_snapshot = (before_dir_mtime_ns, before_entries)
        after_snapshot = _snapshot_dir(fake_config_dir)
        try:
            _assert_no_transient_writes(
                before_snapshot, after_snapshot, permitted_new=_PERMITTED_NEW_ENTRIES
            )
        except AssertionError as exc:
            raise AssertionError(f"fake home's .config/studyloop directory: {exc}") from exc


class TestSnapshotComparisonDetectsTransientWrites:
    """R-49b: fast, non-integration coverage of `_assert_no_transient_writes`
    itself -- proving the detection logic works, independent of the real
    tmux harness (slow, needs `tmux` installed, and cannot deliberately
    inject a transient write into third-party subprocess behavior)."""

    def test_no_changes_at_all_passes(self, tmp_path):
        (tmp_path / "marker.txt").write_text("x")
        before = _snapshot_dir(tmp_path)
        after = _snapshot_dir(tmp_path)
        _assert_no_transient_writes(before, after)  # must not raise

    def test_permitted_new_entry_passes(self, tmp_path):
        before = _snapshot_dir(tmp_path)
        (tmp_path / "studyloop-tmux.lock").write_text("")
        after = _snapshot_dir(tmp_path)
        _assert_no_transient_writes(before, after, permitted_new=frozenset({"studyloop-tmux.lock"}))

    def test_detects_create_then_remove_round_trip(self, tmp_path):
        """The exact gap R-49b closes: a file created and removed again
        before the "after" snapshot is taken leaves the listing identical
        to `before` -- an end-state-only check (unchanged final listing)
        would see nothing wrong. The directory's own mtime, bumped by both
        the create and the remove, still gives it away.
        """
        before = _snapshot_dir(tmp_path)

        transient = tmp_path / "transient-write.tmp"
        transient.write_text("something wrote here and then cleaned up")
        transient.unlink()

        after = _snapshot_dir(tmp_path)

        # The blind spot this item fixes, made explicit: the listings
        # really are identical -- a naive "did any name appear or
        # disappear" check would find nothing.
        assert after[1] == before[1]

        with pytest.raises(AssertionError, match="created and removed again"):
            _assert_no_transient_writes(before, after)

    def test_detects_an_existing_entry_modified_in_place(self, tmp_path):
        marker = tmp_path / "marker.txt"
        marker.write_text("original")
        before = _snapshot_dir(tmp_path)

        marker.write_text("tampered")

        after = _snapshot_dir(tmp_path)
        with pytest.raises(AssertionError, match="modified in place"):
            _assert_no_transient_writes(before, after)

    def test_detects_a_removed_entry(self, tmp_path):
        marker = tmp_path / "marker.txt"
        marker.write_text("x")
        before = _snapshot_dir(tmp_path)

        marker.unlink()

        after = _snapshot_dir(tmp_path)
        with pytest.raises(AssertionError, match="vanished"):
            _assert_no_transient_writes(before, after)

    def test_detects_an_unpermitted_new_entry(self, tmp_path):
        before = _snapshot_dir(tmp_path)

        (tmp_path / "session-state.json").write_text("{}")

        after = _snapshot_dir(tmp_path)
        with pytest.raises(AssertionError, match="unexpected new entries"):
            _assert_no_transient_writes(before, after)
