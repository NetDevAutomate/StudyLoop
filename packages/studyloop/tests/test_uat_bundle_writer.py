"""Unit tests for tests/acceptance/uat/bundle.py -- UNGATED (council D-19/D-26).

Deliberately OUTSIDE tests/acceptance/ and carrying no ``acceptance`` marker:
these test the MECHANISM (manifest schema, inventory hashing, the path
guard, the durable-root resolution rule) never a live UAT journey, so they
must run under the default ``just test`` gate -- a regression here (a
bundle that starts leaking outside its run dir, or a durable root that
starts following a scratch state dir) must be caught by every CI run, not
only a ``STUDYLOOP_UAT=1`` opt-in one.

Path bootstrapping mirrors test_acceptance_isolation.py's convention
(sys.path insert, then a plain import) rather than a conftest.py.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.uat import bundle as bundle_module  # noqa: E402
from acceptance.uat.bundle import (  # noqa: E402
    BundlePathEscapesRunDirError,
    DurableRootUnresolvedError,
    ManifestFields,
    RunCounts,
    build_file_inventory,
    resolve_durable_root,
    sha256_of_bytes,
    write_bundle,
)


def _fields(**overrides: object) -> ManifestFields:
    base = {
        "run_id": "run-0001",
        "date": "2026-09-15T00:00:00Z",
        "repo_sha": "deadbeef",
        "dirty": False,
        "harness": "kiro",
        "actor_backend": "scripted",
        "platform": "darwin",
        "counts": RunCounts(passed=3, skipped=0, failed=0),
    }
    base.update(overrides)
    return ManifestFields(**base)  # type: ignore[arg-type]


class TestManifestSchema:
    def test_manifest_json_carries_every_required_field(self, tmp_path: Path) -> None:
        manifest_path = write_bundle(tmp_path, _fields())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        for key in (
            "run_id",
            "date",
            "repo_sha",
            "dirty",
            "patch_identity",
            "harness",
            "harness_version",
            "platform",
            "auth_mode",
            "actor_backend",
            "actor_model",
            "rubric_version",
            "rubric_hash",
            "seeds",
            "counts",
            "failure_artifacts",
            "file_inventory",
        ):
            assert key in manifest, f"manifest.json is missing {key!r}"

        assert manifest["run_id"] == "run-0001"
        assert manifest["counts"] == {"passed": 3, "skipped": 0, "failed": 0}

    def test_optional_fields_default_to_null_not_absent(self, tmp_path: Path) -> None:
        manifest_path = write_bundle(tmp_path, _fields())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["patch_identity"] is None
        assert manifest["harness_version"] is None
        assert manifest["auth_mode"] is None
        assert manifest["actor_model"] is None
        assert manifest["rubric_version"] is None
        assert manifest["rubric_hash"] is None


class TestFileInventoryHashing:
    def test_inventory_hashes_match_sha256_of_written_files(self, tmp_path: Path) -> None:
        files = {
            "transcript.jsonl": b'{"turn": 1}\n',
            "traces/trace-1.zip": b"not-a-real-zip-but-bytes",
        }
        manifest_path = write_bundle(tmp_path, _fields(), files=files)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        inventory = manifest["file_inventory"]

        assert inventory["transcript.jsonl"] == sha256_of_bytes(files["transcript.jsonl"])
        assert inventory["traces/trace-1.zip"] == sha256_of_bytes(files["traces/trace-1.zip"])
        # manifest.json itself was written AFTER the inventory was built, so
        # it must not be hashing itself.
        assert "manifest.json" not in inventory

    def test_build_file_inventory_matches_write_bundle_inventory(self, tmp_path: Path) -> None:
        files = {"a.txt": b"aaa", "b/c.txt": b"ccc"}
        manifest_path = write_bundle(tmp_path, _fields(), files=files)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Rebuilding the inventory independently (now including manifest.json,
        # since it exists on disk by this point) must still agree on every
        # OTHER file's hash.
        rebuilt = build_file_inventory(tmp_path)
        for rel, digest in manifest["file_inventory"].items():
            assert rebuilt[rel] == digest


class TestPathEscapeGuard:
    def test_refuses_absolute_path(self, tmp_path: Path) -> None:
        with pytest.raises(BundlePathEscapesRunDirError):
            write_bundle(tmp_path, _fields(), files={"/etc/passwd": b"pwned"})

    def test_refuses_dotdot_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(BundlePathEscapesRunDirError):
            write_bundle(tmp_path, _fields(), files={"../escape.txt": b"pwned"})

    def test_refuses_dotdot_buried_in_a_deeper_path(self, tmp_path: Path) -> None:
        with pytest.raises(BundlePathEscapesRunDirError):
            write_bundle(tmp_path, _fields(), files={"a/../../escape.txt": b"pwned"})

    def test_safe_nested_relative_path_is_accepted(self, tmp_path: Path) -> None:
        manifest_path = write_bundle(tmp_path, _fields(), files={"a/b/c.txt": b"ok"})
        assert (tmp_path / "a" / "b" / "c.txt").read_bytes() == b"ok"
        assert manifest_path.exists()


class TestRunDirIsCreatedPrivate:
    """D-14: the durable evidence root is 'created private' (council brief §2).

    A restrictive umask alone is not enough to rely on -- a shared/CI box
    may run with ``022``, which would leave the run dir group/world
    readable. ``write_bundle`` must force ``0o700`` on the directory it
    creates regardless of the process umask.
    """

    def test_run_dir_is_mode_0700_even_under_a_permissive_umask(self, tmp_path: Path) -> None:
        if os.name == "nt":
            pytest.skip("POSIX permission bits only")
        run_dir = tmp_path / "private-run"
        old_umask = os.umask(0o022)
        try:
            write_bundle(run_dir, _fields())
        finally:
            os.umask(old_umask)
        mode = stat.S_IMODE(run_dir.stat().st_mode)
        assert mode == 0o700, f"expected run dir mode 0o700, got {oct(mode)}"

    def test_preexisting_run_dir_is_tightened_to_0700(self, tmp_path: Path) -> None:
        if os.name == "nt":
            pytest.skip("POSIX permission bits only")
        run_dir = tmp_path / "already-here"
        run_dir.mkdir(mode=0o755)
        write_bundle(run_dir, _fields())
        mode = stat.S_IMODE(run_dir.stat().st_mode)
        assert mode == 0o700, f"expected run dir mode 0o700, got {oct(mode)}"

    def test_nested_subdirectories_created_for_a_named_file_are_also_0700(
        self, tmp_path: Path
    ) -> None:
        """Defense-in-depth for the 'created private' guarantee (D-14).

        The run dir itself is already forced to 0o700, which blocks
        traversal into any nested subdirectory regardless of that
        subdirectory's own mode -- but a nested dir created under a
        permissive umask (e.g. ``022``) for a file like
        ``traces/trace-1.zip`` should not be left world/group-readable in
        its own right, for consistency with the tree-wide privacy claim.
        """
        if os.name == "nt":
            pytest.skip("POSIX permission bits only")
        run_dir = tmp_path / "nested-run"
        old_umask = os.umask(0o022)
        try:
            write_bundle(run_dir, _fields(), files={"traces/trace-1.zip": b"not-a-real-zip"})
        finally:
            os.umask(old_umask)
        nested_dir = run_dir / "traces"
        mode = stat.S_IMODE(nested_dir.stat().st_mode)
        assert mode == 0o700, f"expected nested dir mode 0o700, got {oct(mode)}"


class TestAtomicWrites:
    """D-14: the bundle is 'exported atomically before teardown'.

    Both the named files and ``manifest.json`` must be written via a
    temp-file-then-``os.replace`` so a crash mid-write can never leave a
    half-written artefact sitting at its final path.
    """

    def test_manifest_write_goes_through_os_replace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        replace_calls: list[tuple[str, str]] = []
        real_replace = os.replace

        def spy_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            replace_calls.append((str(src), str(dst)))
            real_replace(src, dst)

        monkeypatch.setattr(bundle_module.os, "replace", spy_replace)
        manifest_path = write_bundle(tmp_path, _fields(), files={"a.txt": b"hi"})

        assert replace_calls, "expected write_bundle to finalize writes via os.replace"
        assert any(dst == str(manifest_path) for _src, dst in replace_calls)
        # No stray temp artefacts survive a successful write.
        leftovers = [p for p in tmp_path.rglob("*") if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_a_failed_replace_leaves_no_partial_manifest_or_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_replace(src: object, dst: object) -> None:
            raise OSError("simulated crash between temp-write and rename")

        monkeypatch.setattr(bundle_module.os, "replace", failing_replace)

        with pytest.raises(OSError):
            write_bundle(tmp_path, _fields())

        assert not (tmp_path / "manifest.json").exists()
        leftovers = [p for p in tmp_path.rglob("*") if p.name.endswith(".tmp")]
        assert leftovers == [], f"temp files left behind: {leftovers}"

    def test_a_failed_replace_on_a_named_file_leaves_no_partial_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_replace(src: object, dst: object) -> None:
            raise OSError("simulated crash between temp-write and rename")

        monkeypatch.setattr(bundle_module.os, "replace", failing_replace)

        with pytest.raises(OSError):
            write_bundle(tmp_path, _fields(), files={"transcript.jsonl": b'{"turn": 1}\n'})

        assert not (tmp_path / "transcript.jsonl").exists()
        leftovers = [p for p in tmp_path.rglob("*") if p.name.endswith(".tmp")]
        assert leftovers == [], f"temp files left behind: {leftovers}"


class TestDurableRootResolution:
    def test_default_root_is_under_home_local_share_studyloop_uat(self) -> None:
        real_env = {"HOME": "/Users/exampleuser"}
        root = resolve_durable_root(real_env=real_env, run_id="run-xyz")
        assert root == Path("/Users/exampleuser/.local/share/studyloop/uat/run-xyz")

    def test_override_env_var_wins_over_default(self) -> None:
        real_env = {
            "HOME": "/Users/exampleuser",
            "STUDYLOOP_UAT_EVIDENCE_ROOT": "/var/lib/studyloop-uat",
        }
        root = resolve_durable_root(real_env=real_env, run_id="run-xyz")
        assert root == Path("/var/lib/studyloop-uat/run-xyz")

    def test_missing_home_and_override_raises(self) -> None:
        with pytest.raises(DurableRootUnresolvedError):
            resolve_durable_root(real_env={}, run_id="run-xyz")

    def test_a_scratch_state_dir_present_in_the_mapping_never_relocates_it(self) -> None:
        """The property D-14 exists to guarantee.

        A naive implementation might have preferred ``STUDYLOOP_STATE_DIR``
        (the acceptance tier's OWN per-test scratch var) over ``HOME`` if it
        were present -- that is exactly the bug D-14 describes ("as
        originally drafted it inherited the per-test scratch
        STUDYLOOP_STATE_DIR and would have been swept"). Adding that key to
        the mapping must change nothing about the resolved path.
        """
        real_env = {"HOME": "/Users/exampleuser"}
        before = resolve_durable_root(real_env=real_env, run_id="run-xyz")

        scratch_state_dir = "/tmp/pytest-of-x/pytest-1/test_foo0/home/.local/share/studyloop"
        real_env_with_scratch_leak = {
            **real_env,
            "STUDYLOOP_STATE_DIR": scratch_state_dir,
        }
        after = resolve_durable_root(real_env=real_env_with_scratch_leak, run_id="run-xyz")

        assert before == after
        assert "pytest-of-x" not in str(after)
