"""Mechanics for tests/acceptance/test_harness_matrix_live.py -- UNGATED.

Everything here proves a PREDICATE or a MECHANISM -- never a live session
against a real harness binary -- so it runs under the default ``just test``
gate (no ``acceptance`` marker), the same "matrix, never one green check"
principle (council D-19) applied to this lane's own drift guards: a guard
that only runs under ``STUDYLOOP_ACC=1`` never actually guards CI, since
nobody sets that variable there.

(Review finding, B2 fix round 1: ``TestAvailabilityPredicateMechanics`` and
``test_harness_order_is_exactly_release_harnesses_reordered`` used to live
INSIDE ``test_harness_matrix_live.py``, which carries a module-level
``pytestmark = [pytest.mark.acceptance, ...]`` -- so despite a docstring
claiming "this passes in CI with zero real harness binaries installed",
every test in that file, including these two, was deselected by the
default addopts and never ran without ``STUDYLOOP_ACC=1``. Moved here,
unchanged in substance, so the claim is finally true.)

Path bootstrapping mirrors test_harness_matrix.py's convention (sys.path
insert, then a plain import) rather than a conftest.py, which risks the
workspace's "two packages both named tests" pluggy registration conflict.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from studyloop.harnesses import CORE_HARNESSES, PREVIEW_HARNESSES, RELEASE_HARNESSES, get_harness

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.isolation import create_scratch_environment, sweep_scratch  # noqa: E402
from acceptance.test_harness_matrix_live import (  # noqa: E402
    HARNESS_ORDER,
    PROBES,
    _kiro_probe,
    _presence_only_probe,
    auth_mode_for,
    harness_available,
)
from harness.tmux import TmuxHarness  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator


def test_harness_order_is_exactly_release_harnesses_reordered() -> None:
    """A SET comparison alone would still pass with a duplicated entry
    (driving one harness twice, silently dropping another) or with the
    council's pinned order scrambled -- neither is what this test's own
    name claims to verify (review finding, B2 fix round 1)."""
    assert len(HARNESS_ORDER) == len(RELEASE_HARNESSES), (
        f"HARNESS_ORDER has {len(HARNESS_ORDER)} entries, RELEASE_HARNESSES "
        f"has {len(RELEASE_HARNESSES)} -- a duplicate or a drop would still "
        "pass a set-only comparison"
    )
    assert sorted(HARNESS_ORDER) == sorted(RELEASE_HARNESSES), (
        f"HARNESS_ORDER {sorted(HARNESS_ORDER)} has drifted from "
        f"RELEASE_HARNESSES {sorted(RELEASE_HARNESSES)}"
    )

    # Structural check of the council-pinned order, DERIVED from
    # CORE_HARNESSES/PREVIEW_HARNESSES rather than a second hand-written
    # literal that could drift from HARNESS_ORDER on its own: codex +
    # claude first (E-03 usage), then whatever's left of CORE (kiro), then
    # every PREVIEW_HARNESSES member, in PREVIEW_HARNESSES's own order,
    # strictly last.
    assert HARNESS_ORDER[:2] == ("codex", "claude"), (
        "codex and claude must be the first two entries (E-03 usage)"
    )
    remaining_core = [h for h in CORE_HARNESSES if h not in ("codex", "claude")]
    core_end = 2 + len(remaining_core)
    assert list(HARNESS_ORDER[2:core_end]) == remaining_core, (
        "the rest of CORE_HARNESSES must immediately follow codex/claude"
    )
    assert list(HARNESS_ORDER[core_end:]) == list(PREVIEW_HARNESSES), (
        "every PREVIEW_HARNESSES member must come last, in PREVIEW_HARNESSES's own order"
    )


class TestAuthModeRecording:
    """The bundle's ``auth_mode`` must say which world the harness actually saw.

    A ``presence-only`` run can pass mechanically while the harness prints
    "No API key found" for every turn (pi, 2026-09-16); a reader of the
    evidence must be able to tell that run from one where the harness held
    its real credentials, without opening turns.json.
    """

    @pytest.mark.parametrize("harness_name", RELEASE_HARNESSES)
    def test_real_auth_scratch_records_real_auth_for_every_harness(
        self, harness_name: str, tmp_path: Path
    ) -> None:
        scratch = create_scratch_environment(
            tmp_path, extra_env={"HOME": str(tmp_path), "PATH": "/usr/bin"}, real_harness_auth=True
        )
        try:
            assert auth_mode_for(harness_name, scratch) == "real-auth"
        finally:
            sweep_scratch(scratch)

    def test_scrubbed_scratch_keeps_the_original_split(self, tmp_path: Path) -> None:
        scratch = create_scratch_environment(tmp_path)
        try:
            assert auth_mode_for("kiro", scratch) == "verified"
            for name in PREVIEW_HARNESSES:
                assert auth_mode_for(name, scratch) == "presence-only"
        finally:
            sweep_scratch(scratch)


class TestAvailabilityPredicateMechanics:
    """(a) TESTS FIRST item: "no binary -> named skip", proven directly
    against the predicate rather than only via a live run -- so this
    passes in CI with zero real harness binaries installed."""

    @pytest.mark.parametrize("harness_name", HARNESS_ORDER)
    def test_missing_binary_is_a_named_skip_reason(
        self, harness_name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name, path=None: None)
        ok, reason = harness_available(harness_name, {})
        assert ok is False
        assert get_harness(harness_name).binary in reason

    def test_kiro_probe_names_the_login_failure(self, tmp_path: Path) -> None:
        stub = tmp_path / "kiro-cli"
        stub.write_text("#!/bin/sh\necho 'Not logged in' >&2\nexit 1\n", encoding="utf-8")
        stub.chmod(0o755)

        ok, reason = _kiro_probe(str(stub), {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})

        assert ok is False
        assert "kiro-cli" in reason
        assert "not logged in" in reason.lower()

    def test_presence_only_probe_passes_once_the_binary_exists(self) -> None:
        ok, reason = _presence_only_probe("/bin/true", {})
        assert ok is True
        assert reason == ""

    def test_every_release_harness_has_a_registered_probe(self) -> None:
        """PROBES is keyed by harness name, not an if/elif chain -- adding a
        real probe for a sixth harness must be a one-line dict entry, but
        every RELEASE_HARNESSES member must already resolve to SOME probe
        (real or the presence-only fallback), never a KeyError."""
        for name in RELEASE_HARNESSES:
            assert name in PROBES, f"{name} has no registered probe (real or fallback)"

    def test_harness_available_resolves_the_binary_against_the_given_env_path(
        self, tmp_path: Path
    ) -> None:
        """The binary must be resolved against the CALLER-supplied env's own
        PATH, not this test process's inherited PATH (review finding, B2
        fix round 1) -- otherwise a scratch env whose PATH ever diverges
        from the test process's own would decide presence against the
        wrong PATH than the one the child launch actually receives."""
        stub_dir = tmp_path / "only-here"
        stub_dir.mkdir()
        stub = stub_dir / "codex"
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)

        # Not on THIS process's PATH -- only on the env passed in.
        assert shutil.which("codex", path=str(stub_dir)) == str(stub)

        ok, _reason = harness_available("codex", {"PATH": str(stub_dir)})
        assert ok is True


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed")
class TestTmuxHarnessSocketWiring:
    """CI-safe positive control for the second blocker (review finding, B2
    fix round 1): a bare ``TmuxHarness()`` addresses the CALLER's own
    ``TMUX_TMPDIR``, not a scratch child's -- proven here with a real `tmux`
    server and a throwaway `sleep` session, never a real coding-agent
    binary, so it needs nothing but `tmux` itself."""

    @pytest.fixture
    def scratch_tmux_session(self) -> Iterator[tuple[dict[str, str], str]]:
        # A SHORT `/tmp`-rooted dir, not `tmp_path` -- a pytest `tmp_path`
        # is exactly the deep path shape that trips AF_UNIX's 104-byte
        # `sun_path` limit (see isolation.py's `_UNIX_SOCKET_PATH_LIMIT`
        # and its regression test); this fixture must not reintroduce the
        # very bug the module under test just fixed.
        import tempfile

        socket_dir = Path(tempfile.mkdtemp(prefix="sl-mech-", dir="/tmp"))
        os.chmod(socket_dir, 0o700)
        scratch_env = {**os.environ, "TMUX_TMPDIR": str(socket_dir)}
        session_name = f"sl-socket-wiring-{uuid.uuid4().hex[:8]}"
        created = subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "sleep", "30"],
            env=scratch_env,
            capture_output=True,
            text=True,
        )
        assert created.returncode == 0, f"tmux new-session failed: {created.stderr}"
        try:
            yield scratch_env, session_name
        finally:
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                env=scratch_env,
                capture_output=True,
                check=False,
            )
            shutil.rmtree(socket_dir, ignore_errors=True)

    def test_a_scratch_configured_harness_sees_the_scratch_session(
        self, scratch_tmux_session: tuple[dict[str, str], str]
    ) -> None:
        scratch_env, session_name = scratch_tmux_session
        scratch_tmux = TmuxHarness(env=scratch_env)
        assert scratch_tmux.session_exists(session_name) is True

    def test_a_default_socket_harness_does_not_see_the_scratch_session(
        self, scratch_tmux_session: tuple[dict[str, str], str]
    ) -> None:
        """The exact failure mode findings 1 and 2 described: a bare
        ``TmuxHarness()`` -- this test process's own env, whatever
        ``TMUX_TMPDIR`` (if any) that happens to be -- must NOT see a
        session that only exists under a different, scratch, socket dir."""
        _scratch_env, session_name = scratch_tmux_session
        default_tmux = TmuxHarness()
        assert default_tmux.session_exists(session_name) is False
