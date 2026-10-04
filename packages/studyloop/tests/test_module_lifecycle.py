"""Lifecycle tests for optional modules: ``module new`` (C3) and the store (C4).

Module-contract v1, lane C. The scaffold must pass every conformance rule and carry one
offline, ``echo``-based drill; the store must refuse an unconforming module without touching
``modules.lock.json``. Red evidence lives under ``openspec/changes/module-contract-v1/evidence/C/``.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from studyloop.doctor.modules import check_module_prerequisites, probe_tool
from studyloop.modules.check import check_module
from studyloop.modules.scaffold import ScaffoldError, scaffold_module
from studyloop.modules.store import (
    ModuleCheckError,
    ModuleStore,
    StoreError,
    content_digest,
    git_provenance,
    load_lockfile,
    snapshot_dir,
)

_NETWORK_OR_CLUSTER = ("curl", "wget", "docker", "kind", "kubectl", "http://", "https://")


# ---------------------------------------------------------------------------
# C3 -- scaffold
# ---------------------------------------------------------------------------


def test_scaffold_passes_every_rule(tmp_path: Path) -> None:
    """Spec scenario: the output of ``module new <id>`` passes ``module check`` with no findings."""
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    report = check_module(module)
    assert report.findings == []
    assert report.ok is True


def test_scaffold_carries_one_offline_echo_drill(tmp_path: Path) -> None:
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    decks = sorted((module / "decks").glob("*.json"))
    assert len(decks) == 1
    deck = json.loads(decks[0].read_text(encoding="utf-8"))
    [task] = deck["tasks"]
    assert task["verification"]["command"] == "scripts/check.sh"
    script = module / "scripts" / "check.sh"
    text = script.read_text(encoding="utf-8")
    assert "echo" in text
    assert not any(token in text for token in _NETWORK_OR_CLUSTER)
    assert os.access(script, os.X_OK)
    # It really is offline and really exits 0: run it with a bare PATH and no inherited env.
    run = subprocess.run(
        ["/bin/sh", str(script)],
        env={"PATH": "/usr/bin:/bin"},
        cwd=module,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (run.returncode, run.stdout.strip()) == (0, "ready")


def test_scaffold_manifest_declares_only_what_the_drill_uses(tmp_path: Path) -> None:
    module = scaffold_module(tmp_path / "my-drills", "my-drills", topic="kubernetes")
    manifest = yaml.safe_load((module / "module.yaml").read_text(encoding="utf-8"))
    assert manifest["id"] == "my-drills"
    assert manifest["contract"] == 1
    assert manifest["topic"] == "kubernetes"
    assert manifest["capabilities"] == ["check"]
    assert manifest["prerequisites"] == []
    assert manifest["target"] == {"kind": "workdir"}


def test_scaffold_ships_its_own_offline_shell_test_not_python(tmp_path: Path) -> None:
    """§5.1 asks for ``tests/``; MC012 forbids ``*.py``, so the module's test is a shell script."""
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    tests = sorted(p.name for p in (module / "tests").iterdir())
    assert tests == ["check.sh"]
    assert not list(module.rglob("*.py"))
    run = subprocess.run(
        ["/bin/sh", str(module / "tests" / "check.sh")],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert run.returncode == 0, run.stderr


def test_scaffold_refuses_an_invalid_id(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError, match="not a module id"):
        scaffold_module(tmp_path / "x", "My Drills")
    assert not (tmp_path / "x").exists()


def test_scaffold_refuses_a_non_empty_destination(tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ScaffoldError, match="not empty"):
        scaffold_module(occupied, "occupied")
    assert sorted(p.name for p in occupied.iterdir()) == ["notes.txt"]


# ---------------------------------------------------------------------------
# C4 -- store: add / list / remove, modules.lock.json
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "modules"
VALID = FIXTURES / "valid-scaffold"


@pytest.fixture
def store(tmp_path: Path) -> ModuleStore:
    return ModuleStore(tmp_path / "store")


def _lock_bytes(store: ModuleStore) -> bytes | None:
    return store.lockfile.read_bytes() if store.lockfile.exists() else None


def _snapshot_names(store: ModuleStore) -> list[str]:
    if not store.snapshots.is_dir():
        return []
    return sorted(p.name for p in store.snapshots.iterdir())


def test_add_refuses_an_unconforming_module_and_leaves_the_lockfile_byte_identical(
    store: ModuleStore, tmp_path: Path
) -> None:
    """Spec scenario: nothing reaches the snapshot store or the lockfile; the finding is shown."""
    good = scaffold_module(tmp_path / "good", "good-drills")
    store.add(good)  # a populated lockfile is the harder case: it must not be rewritten either
    before = _lock_bytes(store)
    snapshots_before = _snapshot_names(store)
    assert before is not None

    with pytest.raises(ModuleCheckError) as excinfo:
        store.add(FIXTURES / "mc015" / "broken")

    assert {f.rule_id for f in excinfo.value.report.findings} == {"MC015"}
    assert _lock_bytes(store) == before
    assert _snapshot_names(store) == snapshots_before
    assert [e.id for e in load_lockfile(store.root)] == ["good-drills"]


def test_add_records_id_version_digest_and_snapshot(store: ModuleStore, tmp_path: Path) -> None:
    good = scaffold_module(tmp_path / "good", "good-drills")
    entry = store.add(good)
    assert (entry.id, entry.version) == ("good-drills", "0.1.0")
    assert entry.digest == content_digest(good)
    assert entry.digest.startswith("sha256:") and len(entry.digest) == len("sha256:") + 64
    assert snapshot_dir(entry) == store.snapshots / entry.digest.removeprefix("sha256:")
    assert snapshot_dir(entry).is_dir()
    assert entry.source == str(good.resolve())
    [listed] = load_lockfile(store.root)
    assert listed == entry
    raw = json.loads(store.lockfile.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert set(raw["modules"][0]) == {
        "id",
        "version",
        "digest",
        "snapshot",
        "source",
        "git_remote",
        "git_sha",
        "installed_at",
    }


def test_snapshot_is_a_read_only_copy_that_passes_check(store: ModuleStore, tmp_path: Path) -> None:
    good = scaffold_module(tmp_path / "good", "good-drills")
    entry = store.add(good)
    snapshot = snapshot_dir(entry)
    copied = sorted(p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file())
    original = sorted(p.relative_to(good).as_posix() for p in good.rglob("*") if p.is_file())
    assert copied == original
    for file in snapshot.rglob("*"):
        if not file.is_file():
            continue
        mode = stat.S_IMODE(file.stat().st_mode)
        expected = 0o555 if file.parent.name in ("scripts", "tests") else 0o444
        assert mode == expected, (file, oct(mode))
    assert content_digest(snapshot) == entry.digest
    assert check_module(snapshot).ok is True


def test_digest_is_content_addressed(tmp_path: Path) -> None:
    a = scaffold_module(tmp_path / "a", "same-drills")
    b = scaffold_module(tmp_path / "b", "same-drills")
    assert content_digest(a) == content_digest(b)
    (b / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.1\n\n- changed\n", encoding="utf-8")
    assert content_digest(a) != content_digest(b)


def test_add_outside_a_git_checkout_records_null_provenance(
    store: ModuleStore, tmp_path: Path
) -> None:
    # tmp_path is not inside a repository; git must not see one above it either.
    assert git_provenance(tmp_path) == (None, None)
    good = scaffold_module(tmp_path / "good", "good-drills")
    entry = store.add(good)
    assert (entry.git_remote, entry.git_sha) == (None, None)


def _git(cwd: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_add_inside_a_git_checkout_records_remote_and_head_without_a_fetch(
    store: ModuleStore, tmp_path: Path
) -> None:
    """Spec scenario: the lockfile entry carries the remote URL and HEAD sha and the digest."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "https://git.example.invalid/drills/good.git")
    good = scaffold_module(repo / "good", "good-drills")
    _git(repo, "add", "good")
    _git(repo, "commit", "-q", "-m", "fixture module")
    head = _git(repo, "rev-parse", "HEAD")

    entry = store.add(good)

    assert entry.git_remote == "https://git.example.invalid/drills/good.git"
    assert entry.git_sha == head
    assert len(head) == 40
    assert entry.digest == content_digest(good)
    # the fixture remote does not resolve: a fetch would have failed loudly, and did not run
    assert not (repo / ".git" / "FETCH_HEAD").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_checkout_without_a_remote_records_sha_and_null_remote(
    store: ModuleStore, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    good = scaffold_module(repo / "good", "good-drills")
    _git(repo, "add", "good")
    _git(repo, "commit", "-q", "-m", "fixture module")
    entry = store.add(good)
    assert entry.git_remote is None
    assert entry.git_sha == _git(repo, "rev-parse", "HEAD")


def test_list_is_lockfile_driven_and_sorted(store: ModuleStore, tmp_path: Path) -> None:
    assert store.entries() == []
    store.add(scaffold_module(tmp_path / "b", "beta-drills"))
    store.add(scaffold_module(tmp_path / "a", "alpha-drills"))
    assert [e.id for e in store.entries()] == ["alpha-drills", "beta-drills"]
    assert [e.id for e in load_lockfile(store.root)] == ["alpha-drills", "beta-drills"]


def test_re_adding_the_same_id_replaces_the_entry_and_drops_the_orphaned_snapshot(
    store: ModuleStore, tmp_path: Path
) -> None:
    good = scaffold_module(tmp_path / "good", "good-drills")
    first = store.add(good)
    (good / "CHANGELOG.md").write_text("# Changelog\n\n## 0.1.1\n\n- changed\n", encoding="utf-8")
    second = store.add(good)
    assert first.digest != second.digest
    assert [e.digest for e in store.entries()] == [second.digest]
    assert not snapshot_dir(first).exists()
    assert snapshot_dir(second).is_dir()


def test_remove_is_idempotent_and_lockfile_driven(store: ModuleStore, tmp_path: Path) -> None:
    entry = store.add(scaffold_module(tmp_path / "good", "good-drills"))
    assert store.remove("good-drills") is True
    assert store.entries() == []
    assert not snapshot_dir(entry).exists()
    after_first = _lock_bytes(store)
    assert store.remove("good-drills") is False
    assert _lock_bytes(store) == after_first
    assert store.remove("never-installed") is False
    assert _lock_bytes(store) == after_first


def test_load_lockfile_rejects_a_foreign_shape(tmp_path: Path) -> None:
    root = tmp_path / "store"
    root.mkdir()
    (root / "modules.lock.json").write_text('{"version": 7, "modules": []}', encoding="utf-8")
    with pytest.raises(StoreError, match="version-1"):
        load_lockfile(root)
    assert load_lockfile(tmp_path / "absent") == []


# ---------------------------------------------------------------------------
# C5 -- doctor probes for installed modules' prerequisites (fake binaries on PATH)
# ---------------------------------------------------------------------------


def _fake_bin(directory: Path, tool: str, output: str, exit_code: int = 0) -> Path:
    """A fake ``tool`` that logs its argv to $FAKE_PROBE_LOG and prints ``output``."""
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / tool
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "{tool} $*" >> "$FAKE_PROBE_LOG"\n'
        f"printf '%s\\n' '{output}'\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _probe_log(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _install_with_prerequisites(
    store: ModuleStore, tmp_path: Path, module_id: str, prerequisites: str
) -> None:
    module = scaffold_module(tmp_path / module_id, module_id)
    manifest = module / "module.yaml"
    text = manifest.read_text(encoding="utf-8")
    assert "prerequisites: []" in text
    manifest.write_text(
        text.replace(
            "prerequisites: []        # ids from core's enum: docker | kind | kubectl",
            f"prerequisites: {prerequisites}",
        ),
        encoding="utf-8",
    )
    assert check_module(module).ok is True
    store.add(module)


@pytest.fixture
def fake_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path]:
    """A PATH holding only fake docker/kind/kubectl, each logging every invocation."""
    log = tmp_path / "probe.log"
    monkeypatch.setenv("FAKE_PROBE_LOG", str(log))
    bins = tmp_path / "bin"
    _fake_bin(bins, "docker", "Docker version 27.1.1, build deadbeef")
    _fake_bin(bins, "kind", "kind version 0.24.0")
    _fake_bin(bins, "kubectl", "Client Version: v1.31.0")
    return str(bins), log


def test_no_module_installed_runs_no_probe(store: ModuleStore, fake_path: tuple[str, Path]) -> None:
    """Spec scenario: no module installed -> no prerequisite probe runs, nothing is touched."""
    path, log = fake_path
    assert check_module_prerequisites(store_root=store.root, path=path) == []
    assert _probe_log(log) == []


def test_probes_only_the_installed_modules_prerequisites_with_version_only(
    store: ModuleStore, tmp_path: Path, fake_path: tuple[str, Path]
) -> None:
    path, log = fake_path
    _install_with_prerequisites(
        store, tmp_path, "k8s-drills", '[{id: docker, min: "24"}, {id: kind}]'
    )
    _install_with_prerequisites(store, tmp_path, "docker-drills", "[{id: docker}]")

    results = check_module_prerequisites(store_root=store.root, path=path)

    assert [(r.category, r.name, r.status) for r in results] == [
        ("deps", "module_prereq_docker", "pass"),
        ("deps", "module_prereq_kind", "pass"),
    ]
    assert results[0].message == "docker 27.1.1 (needed by docker-drills, k8s-drills)"
    assert results[1].message == "kind 0.24.0 (needed by k8s-drills)"
    # kubectl is on PATH but no installed module needs it: never looked up, never run
    assert sorted(_probe_log(log)) == ["docker --version", "kind --version"]


def test_missing_tool_fails_and_an_old_version_warns(
    store: ModuleStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "probe.log"
    monkeypatch.setenv("FAKE_PROBE_LOG", str(log))
    bins = tmp_path / "bin"
    _fake_bin(bins, "docker", "Docker version 23.0.1, build cafebabe")
    # no kubectl on this PATH at all
    _install_with_prerequisites(
        store, tmp_path, "k8s-drills", '[{id: docker, min: "24"}, {id: kubectl}]'
    )

    results = {r.name: r for r in check_module_prerequisites(store_root=store.root, path=str(bins))}

    assert results["module_prereq_docker"].status == "warn"
    assert (
        "23.0.1 is below the minimum: k8s-drills needs >= 24"
        in results["module_prereq_docker"].message
    )
    assert results["module_prereq_kubectl"].status == "fail"
    assert "kubectl not found (needed by k8s-drills)" in results["module_prereq_kubectl"].message
    assert results["module_prereq_kubectl"].fix_hint
    assert _probe_log(log) == ["docker --version"]


def test_tool_that_rejects_version_flag_is_a_warn_not_a_fail(
    store: ModuleStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real kubectl has no --version flag; present-but-unparseable is reported, not hidden."""
    log = tmp_path / "probe.log"
    monkeypatch.setenv("FAKE_PROBE_LOG", str(log))
    bins = tmp_path / "bin"
    _fake_bin(bins, "kubectl", "Error: unknown flag: --version", exit_code=1)
    _install_with_prerequisites(store, tmp_path, "k8s-drills", "[{id: kubectl}]")

    [result] = check_module_prerequisites(store_root=store.root, path=str(bins))

    assert result.status == "warn"
    assert "version is unknown" in result.message
    assert "exited 1" in result.message
    assert _probe_log(log) == ["kubectl --version"]


def test_probe_tool_refuses_anything_outside_the_enum(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a prerequisite id"):
        probe_tool("rm", path=str(tmp_path))


def test_module_prerequisites_check_is_registered_under_deps() -> None:
    """A checker that is defined but never registered is a doctor that stays silent."""
    from studyloop.cli._doctor import _get_registry

    registered = {(category, fn.__name__) for category, fn in _get_registry()._checkers}
    assert ("deps", "check_module_prerequisites") in registered
