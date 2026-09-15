"""The FULL UAT evidence-bundle writer (council D-14/D-22, lane B4).

``tests/acceptance/evidence.py`` (B2) writes a deliberately NARROW bundle --
this module is the full schema that lane described as coming later: a
``manifest.json`` with run id, date, repo sha + dirty-tree/patch identity,
harness+version, platform, auth mode, actor backend+model, rubric
version+hash, seeds, full pass/fail/skip counts, failure artefacts, and a
file inventory with sha256s over every file the run wrote -- plus a durable
evidence root resolved from the REAL environment, captured BEFORE any
per-test scratch substitution happens (D-14: the original draft inherited
the per-test scratch ``STUDYLOOP_STATE_DIR`` and would have been swept by
the acceptance tier's own guarded sweeper the moment that test ended).

Two separate concerns, two separate functions:

- :func:`resolve_durable_root` answers "where does this run's bundle live,
  durably, outside any scratch tree" -- and answers it ONLY from an
  explicitly-passed environment mapping. It never reads a live
  ``os.environ`` itself and the string ``"STUDYLOOP_STATE_DIR"`` never
  appears in this function -- not merely "not preferred", genuinely absent
  from its logic -- which is what lets a test prove a scratch state dir
  cannot relocate it: the same ``real_env`` in, the same path out, even
  when that mapping ALSO happens to carry a scratch ``STUDYLOOP_STATE_DIR``
  key nothing here ever looks at.
- :func:`write_bundle` writes the files and the manifest INTO a run
  directory a caller already resolved (durable or scratch, this module
  does not care) -- and refuses, hard, to write anything a caller names
  with a relative path that would land outside that directory.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_MANIFEST_NAME = "manifest.json"

#: The durable root's own env var (D-14) -- distinct from the acceptance
#: tier's per-test ``STUDYLOOP_STATE_DIR``, deliberately, so the two can
#: never be confused for one another by name alone.
DURABLE_ROOT_ENV = "STUDYLOOP_UAT_EVIDENCE_ROOT"


class BundlePathEscapesRunDirError(ValueError):
    """A relative path handed to the writer would land outside ``run_dir``."""


class DurableRootUnresolvedError(ValueError):
    """Neither ``DURABLE_ROOT_ENV`` nor ``HOME`` is present in ``real_env``."""


def resolve_durable_root(*, real_env: Mapping[str, str], run_id: str) -> Path:
    """Resolve the durable evidence root for one UAT run.

    ``real_env`` must be the environment captured BEFORE any per-test
    scratch substitution -- see the module docstring. Default, when
    ``STUDYLOOP_UAT_EVIDENCE_ROOT`` is unset or empty:
    ``<HOME>/.local/share/studyloop/uat/<run_id>``.

    Raises :class:`DurableRootUnresolvedError` if ``real_env`` has neither
    the override variable nor ``HOME`` set -- there is then nothing safe
    to derive a durable path from.
    """
    override = real_env.get(DURABLE_ROOT_ENV, "").strip()
    if override:
        base = Path(override)
    else:
        home_raw = real_env.get("HOME", "").strip()
        if not home_raw:
            raise DurableRootUnresolvedError(
                f"real_env has neither {DURABLE_ROOT_ENV!r} nor 'HOME' set; "
                "cannot resolve a durable evidence root"
            )
        base = Path(home_raw) / ".local" / "share" / "studyloop" / "uat"
    return base / run_id


@dataclass(frozen=True, slots=True)
class RunCounts:
    """Full pass/fail/skip counts for one sign-off run (council D-22)."""

    passed: int
    skipped: int
    failed: int

    def as_dict(self) -> dict[str, int]:
        return {"passed": self.passed, "skipped": self.skipped, "failed": self.failed}


@dataclass(frozen=True, slots=True)
class ManifestFields:
    """Every field council D-22's manifest schema names.

    Optional fields default to ``None`` (recorded as such, never simply
    absent) rather than being left off the dataclass -- the same "the KEY
    is always present" discipline ``tests/acceptance/evidence.py`` already
    established for its narrower subset.
    """

    run_id: str
    date: str
    repo_sha: str
    dirty: bool
    harness: str
    actor_backend: str
    platform: str
    patch_identity: str | None = None
    harness_version: str | None = None
    auth_mode: str | None = None
    actor_model: str | None = None
    rubric_version: str | None = None
    rubric_hash: str | None = None
    seeds: Mapping[str, int] = field(default_factory=dict)
    counts: RunCounts = field(default_factory=lambda: RunCounts(0, 0, 0))
    failure_artifacts: tuple[str, ...] = ()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: Path) -> str:
    return sha256_of_bytes(path.read_bytes())


def _assert_within_run_dir(run_dir: Path, relative: str) -> Path:
    """Reject any relative path that could escape ``run_dir``.

    Absolute paths and any ``..`` component are rejected before the
    filesystem is ever touched -- a resolved-path check alone would still
    let a symlink already sitting inside ``run_dir`` redirect the write
    elsewhere, so both the syntactic check AND the resolved-path check run.
    """
    rel_path = Path(relative)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise BundlePathEscapesRunDirError(
            f"refusing to write {relative!r}: not a safe relative path under the run dir {run_dir}"
        )
    resolved_run_dir = run_dir.resolve()
    dest = (run_dir / rel_path).resolve()
    if dest != resolved_run_dir and not dest.is_relative_to(resolved_run_dir):
        raise BundlePathEscapesRunDirError(
            f"refusing to write {relative!r}: resolves to {dest}, outside run "
            f"dir {resolved_run_dir}"
        )
    return dest


def build_file_inventory(run_dir: Path) -> dict[str, str]:
    """Map every regular file under ``run_dir`` to its sha256 (D-22)."""
    inventory: dict[str, str] = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            rel = path.relative_to(run_dir).as_posix()
            inventory[rel] = sha256_of_file(path)
    return inventory


def write_bundle(
    run_dir: Path,
    fields: ManifestFields,
    *,
    files: Mapping[str, bytes] | None = None,
) -> Path:
    """Write ``files`` (each keyed by a path relative to ``run_dir``) then
    ``manifest.json``, and return the manifest's path.

    The file inventory is built AFTER every named file is written but
    BEFORE ``manifest.json`` itself exists -- so the manifest can embed a
    hash of every OTHER artefact in the run without needing to hash (or
    exclude) itself.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    for relative, content in (files or {}).items():
        dest = _assert_within_run_dir(run_dir, relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    inventory = build_file_inventory(run_dir)
    manifest: dict[str, object] = {
        "run_id": fields.run_id,
        "date": fields.date,
        "repo_sha": fields.repo_sha,
        "dirty": fields.dirty,
        "patch_identity": fields.patch_identity,
        "harness": fields.harness,
        "harness_version": fields.harness_version,
        "platform": fields.platform,
        "auth_mode": fields.auth_mode,
        "actor_backend": fields.actor_backend,
        "actor_model": fields.actor_model,
        "rubric_version": fields.rubric_version,
        "rubric_hash": fields.rubric_hash,
        "seeds": dict(fields.seeds),
        "counts": fields.counts.as_dict(),
        "failure_artifacts": list(fields.failure_artifacts),
        "file_inventory": inventory,
    }
    manifest_path = run_dir / _MANIFEST_NAME
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(rendered, encoding="utf-8")
    return manifest_path


__all__ = [
    "DURABLE_ROOT_ENV",
    "BundlePathEscapesRunDirError",
    "DurableRootUnresolvedError",
    "ManifestFields",
    "RunCounts",
    "build_file_inventory",
    "resolve_durable_root",
    "sha256_of_bytes",
    "sha256_of_file",
    "write_bundle",
]
