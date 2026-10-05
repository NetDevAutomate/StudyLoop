"""Live proof for a kdrill-converted module (module-contract v1, DoD item 7; lane W5).

Gated TWICE and skips cleanly without either: the tier's ``STUDYLOOP_ACC=1`` (the autouse
``_acceptance_gate`` in ``conftest.py``) and ``STUDYLOOP_LIVE=1`` here, because this test
creates a real kind cluster on the machine that runs it. It also needs:

- ``STUDYLOOP_KDRILL_MODULE`` -- path to the converted kdrill module directory (the module is not
  in this repository; owner tasks K1-K2 convert it and run this proof). Absent -> skip, named.
- ``STUDYLOOP_KDRILL_DRILL`` (optional) -- ``<module>/<deck>/<task>`` to run; default: the first
  task in the first deck that declares ``setupCommand``, ``command`` and ``cleanupCommand``.

Once opted in, a missing ``docker`` / ``kind`` / ``kubectl`` FAILS rather than skips (council
D-13: an opted-in run never passes through a skip).

**The sentinel-cluster assertion.** Before anything runs the test creates its own kind cluster,
``studyloop-sentinel-<hex>``; after ``setup`` -> ``check`` -> ``cleanup`` that cluster must still
exist and the set of clusters must be exactly what it was before plus the sentinel -- the drill
removed only what it created. A drill whose cleanup deletes the wrong cluster fails here, not in
a learner's lab. Every phase is run through the real CLI with the consent typed on stdin, inside
the tier's scratch environment (its own HOME, state dir, config and lockfile); the real
``~/.kube`` is never written because the module's scripts receive a scratch HOME.

Contract gap, recorded for the coordinator (W5): ``cli/_drill.py`` opens every attempt with
``target=workdir`` and nothing in core creates the §5.5 disposable cluster or writes the
one-context ``KUBECONFIG`` (``runner.build_environment`` refuses a ``kubeconfig-context``
attempt without one). A converted kdrill module therefore manages its own kind cluster from its
``scripts/`` through the declared ``kind``/``kubectl`` prerequisites, and this proof asserts the
blast radius that matters -- the sentinel survives -- rather than a core-written kubeconfig.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from .isolation import ScratchEnv

pytestmark = [pytest.mark.acceptance, pytest.mark.timeout(1800)]

_LIVE_ENV = "STUDYLOOP_LIVE"
_MODULE_ENV = "STUDYLOOP_KDRILL_MODULE"
_DRILL_ENV = "STUDYLOOP_KDRILL_DRILL"
_TOOLS = ("docker", "kind", "kubectl")
_SENTINEL_PREFIX = "studyloop-sentinel-"


def _live_opt_in() -> Path:
    """The module path, or a named skip for whichever opt-in is missing."""
    if os.environ.get(_LIVE_ENV) != "1":
        pytest.skip(f"live kdrill proof requires {_LIVE_ENV}=1 (it creates a kind cluster)")
    raw = os.environ.get(_MODULE_ENV, "").strip()
    if not raw:
        pytest.skip(f"live kdrill proof requires {_MODULE_ENV}=<path to the converted module>")
    module = Path(raw).expanduser()
    if not (module / "module.yaml").is_file():
        pytest.fail(f"{_MODULE_ENV}={raw!r} is not a module directory (no module.yaml)")
    missing = [tool for tool in _TOOLS if shutil.which(tool) is None]
    if missing:
        pytest.fail(f"opted in with {_LIVE_ENV}=1 but these tools are not on PATH: {missing}")
    return module


def _run(scratch: ScratchEnv, *argv: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        env=scratch.env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def _studyloop(
    scratch: ScratchEnv, *args: str, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    return _run(scratch, sys.executable, "-m", "studyloop.cli", *args, stdin=stdin)


def _clusters(scratch: ScratchEnv) -> set[str]:
    result = _run(scratch, "kind", "get", "clusters")
    assert result.returncode == 0, result.stderr
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _default_drill(module: Path, module_id: str) -> str:
    for deck_path in sorted((module / "decks").glob("*.json")):
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        for task in deck.get("tasks", []):
            verification = task.get("verification") or {}
            if all(verification.get(key) for key in ("setupCommand", "command", "cleanupCommand")):
                return f"{module_id}/{deck['id']}/{task['id']}"
    pytest.fail("no task in the module declares setupCommand, command and cleanupCommand")


@pytest.fixture()
def sentinel_cluster(scratch_env: ScratchEnv) -> Generator[str, None, None]:
    """A kind cluster that must survive the drill. Created before, deleted after -- by us."""
    _live_opt_in()
    name = f"{_SENTINEL_PREFIX}{secrets.token_hex(4)}"
    created = _run(scratch_env, "kind", "create", "cluster", "--name", name, "--wait", "180s")
    assert created.returncode == 0, created.stderr
    try:
        yield name
    finally:
        _run(scratch_env, "kind", "delete", "cluster", "--name", name)


def test_live_kdrill_drill_runs_three_phases_and_spares_the_sentinel_cluster(
    scratch_env: ScratchEnv, sentinel_cluster: str
) -> None:
    module = _live_opt_in()
    before = _clusters(scratch_env)
    assert sentinel_cluster in before

    checked = _studyloop(scratch_env, "module", "check", str(module))
    assert checked.returncode == 0, checked.stdout + checked.stderr
    added = _studyloop(scratch_env, "module", "add", "--json", str(module))
    assert added.returncode == 0, added.stdout + added.stderr
    entry = json.loads(added.stdout)
    module_id = entry["id"]
    lockfile = scratch_env.config_dir / "modules" / "modules.lock.json"
    assert lockfile.is_file(), "the lockfile lives in the scratch config dir, not the real one"

    drill = os.environ.get(_DRILL_ENV, "").strip() or _default_drill(module, module_id)
    transcript: list[str] = []
    for phase, allowed in (("setup", {0}), ("check", {0, 1}), ("cleanup", {0})):
        result = _studyloop(scratch_env, "drill", phase, drill, stdin="y\n")
        transcript.append(f"$ studyloop drill {phase} {drill}\n{result.stdout}{result.stderr}")
        assert "Run this phase now?" in result.stdout, f"{phase}: consent was not asked"
        assert "Script sha256:" in result.stdout, f"{phase}: the script digest was not shown"
        assert result.returncode in allowed, f"{phase} exit {result.returncode}:\n{transcript[-1]}"
        # No web session is live in the scratch world, so the hop reports exactly the
        # session-transports scenario "no running server is learner-visible".
        assert "Mentor not told: no_active_session" in result.stdout, transcript[-1]
        if phase == "setup":
            after_setup = _clusters(scratch_env)
            assert sentinel_cluster in after_setup, "setup removed the sentinel cluster"
            assert after_setup >= before, "setup removed a pre-existing cluster"

    after = _clusters(scratch_env)
    assert sentinel_cluster in after, "the drill's cleanup deleted the sentinel cluster"
    assert after == before, (
        f"the drill left or removed clusters it does not own: before={sorted(before)} "
        f"after={sorted(after)}"
    )

    attempts = list((scratch_env.state_dir).rglob("module-attempts/*/*/*/*"))
    assert attempts, "the attempt directory with the three phase records was not written"
    (scratch_env.home / "kdrill-live-transcript.txt").write_text(
        "\n\n".join(transcript), encoding="utf-8"
    )
