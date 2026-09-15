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
import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

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
