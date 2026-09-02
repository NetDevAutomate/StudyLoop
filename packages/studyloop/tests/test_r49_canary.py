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
whole directory: ``studyloop.tmux.LOCK_FILE`` is a separate, pre-existing,
contentless (0-byte) coordination lock hardcoded to ``~/.config/studyloop``
independent of any env var, in a file owned by a different lane (M2's
``tmux.py``) -- out of scope here, and legitimately appears in the fake home
too once ``studyloop.tmux`` is first imported after HOME is faked. Noted, not
fixed, in this milestone's evidence.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from harness.agents import long_running_agent  # noqa: E402
from harness.study import StudySession  # noqa: E402

pytestmark = [
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    pytest.mark.integration,
]


class TestR49Canary:
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
