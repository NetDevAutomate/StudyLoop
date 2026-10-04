"""The module store: ``module add <path>`` / ``list`` / ``remove`` and ``modules.lock.json``.

Module-contract v1 (proposal §7, spec "optional-modules"), lane C. A module is installed from
a **local path only**. ``add`` is STAGE -> CHECK -> DIGEST -> PUBLISH, every step reading the
same private copy, so the bytes that were checked are the bytes whose digest is recorded are
the bytes the runner later executes (lane R's consent is digest-bound):

1. **stage** -- copy the source into a private directory under ``snapshots/`` (``.staging-*``).
   Only regular files and directories are copied; a symlink, hard link (``st_nlink != 1``),
   device, socket or FIFO *anywhere* in the module is refused with :class:`StoreError` naming
   the path -- never skipped, because a skipped ``module.yaml`` symlink would pass the check on
   the source and fail MC003 in the snapshot. ``.git/`` directories are not module content and
   are left out (they also carry hard links after ``git clone --local``).
2. **check** -- ``check_module`` on the staged tree; any finding -> :class:`ModuleCheckError`,
   staging removed, lockfile byte-identical.
3. **digest** -- ``content_digest`` on the staged tree.
4. **publish** -- atomic rename of the staging directory to ``snapshots/<hex>``. When that path
   already exists it is re-digested and a mismatch is refused with :class:`StoreError`; a
   match reuses it.

``list`` and ``remove`` operate on the lockfile alone. No network access occurs anywhere here; the
only subprocess is ``git`` reading local provenance (``rev-parse HEAD``, ``remote get-url
origin``) when ``<path>`` is inside a git checkout, and that never fetches.

Layout under the store root (default ``<config dir>/modules``, i.e. ``$STUDYLOOP_CONFIG``'s
directory -- proposal §7 puts snapshots in StudyLoop's config dir)::

    modules/
      modules.lock.json          # the lockfile (schema below)
      snapshots/<sha256 hex>/    # one immutable snapshot per content digest

Lockfile schema (``"version": 1``)::

    {
      "version": 1,
      "modules": [
        {
          "id": "kubernetes-drills",          # module.yaml id; one entry per id
          "version": "0.1.0",                 # module.yaml version
          "digest": "sha256:<hex>",           # content digest, see content_digest()
          "snapshot": "/abs/path/snapshots/<hex>",
          "source": "/abs/path/given/to/module add",
          "git_remote": "https://github.com/x/y.git",   # null when no remote / not a checkout
          "git_sha": "<40 hex>",                        # null when not a checkout
          "installed_at": "2026-10-04T19:30:00+00:00"
        }
      ]
    }

Content digest: SHA-256 over every regular file under the module (``.git/`` excluded,
symlinks and other non-regular entries skipped), in sorted relative-POSIX-path order, each
contributing ``"<rel>\\0<x|->\\0<size>\\0"`` (``x`` when the file is executable) followed by its
bytes. Two trees with the same files, bytes and exec bits share one digest and one snapshot.

Snapshot files are read-only: ``0o444``, or ``0o555`` for files that were executable in the
source (the drill scripts). Lane R's drill runner reads :func:`load_lockfile`,
:class:`LockEntry` and :func:`snapshot_dir`; the snapshot is the tree it executes from.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from studyloop.modules.check import CheckReport, check_module

if TYPE_CHECKING:
    from collections.abc import Iterator

LOCKFILE_NAME = "modules.lock.json"
LOCKFILE_VERSION = 1
SNAPSHOTS_DIRNAME = "snapshots"


class ModuleCheckError(Exception):
    """``module add`` refused: the module fails conformance. Nothing was written."""

    def __init__(self, source: Path, report: CheckReport) -> None:
        self.source = source
        self.report = report
        rules = ", ".join(sorted({f.rule_id for f in report.findings}))
        super().__init__(f"{source} fails module check ({rules}); not installed")


class StoreError(Exception):
    """The store itself is unusable (bad lockfile, unreadable source)."""


@dataclass(frozen=True, slots=True)
class LockEntry:
    """One installed module as recorded in ``modules.lock.json``.

    ``digest`` is ``"sha256:<hex>"``; ``snapshot`` is the absolute snapshot directory
    (:func:`snapshot_dir` returns it as a :class:`~pathlib.Path`); ``git_remote`` and
    ``git_sha`` are ``None`` unless the source path was inside a git checkout (``git_remote``
    is also ``None`` for a checkout with no ``origin``).
    """

    id: str
    version: str
    digest: str
    snapshot: str
    source: str
    git_remote: str | None
    git_sha: str | None
    installed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LockEntry:
        try:
            return cls(
                id=str(raw["id"]),
                version=str(raw["version"]),
                digest=str(raw["digest"]),
                snapshot=str(raw["snapshot"]),
                source=str(raw.get("source", "")),
                git_remote=raw.get("git_remote"),
                git_sha=raw.get("git_sha"),
                installed_at=str(raw.get("installed_at", "")),
            )
        except KeyError as exc:
            raise StoreError(f"lockfile entry lacks {exc}") from exc


def default_store_root() -> Path:
    """``<config dir>/modules`` -- honours ``STUDYLOOP_CONFIG`` like every other path."""
    from studyloop.settings import get_config_dir

    return get_config_dir() / "modules"


def lockfile_path(root: Path | None = None) -> Path:
    """Where ``modules.lock.json`` lives for ``root`` (default store root)."""
    return (root if root is not None else default_store_root()) / LOCKFILE_NAME


def load_lockfile(root: Path | None = None) -> list[LockEntry]:
    """Read the lockfile under ``root`` (default store root); an absent file is no modules.

    Raises :class:`StoreError` for a lockfile that is not the documented shape, rather than
    guessing -- the lockfile is the one record of what is installed.
    """
    path = lockfile_path(root)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != LOCKFILE_VERSION:
        raise StoreError(f"{path} is not a version-{LOCKFILE_VERSION} modules lockfile")
    modules = raw.get("modules")
    if not isinstance(modules, list):
        raise StoreError(f"{path}: 'modules' must be a list")
    return [LockEntry.from_dict(entry) for entry in modules if isinstance(entry, dict)]


def snapshot_dir(entry: LockEntry) -> Path:
    """The immutable snapshot directory an entry was installed into."""
    return Path(entry.snapshot)


# ---------------------------------------------------------------------------
# content digest
# ---------------------------------------------------------------------------


def _module_files(source: Path) -> Iterator[tuple[str, Path]]:
    """``(relative posix path, absolute path)`` for every regular file, sorted, ``.git`` skipped."""
    found: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        for name in filenames:
            path = Path(dirpath) / name
            try:
                mode = path.lstat().st_mode
            except OSError:
                continue
            if not stat.S_ISREG(mode):
                continue
            found.append((path.relative_to(source).as_posix(), path))
    yield from sorted(found)


def _is_executable(path: Path) -> bool:
    return bool(path.lstat().st_mode & stat.S_IXUSR)


def content_digest(source: Path) -> str:
    """``"sha256:<hex>"`` over the module's files, paths, sizes and exec bits (see module doc)."""
    digest = hashlib.sha256()
    for relative, path in _module_files(source):
        data = path.read_bytes()
        flag = "x" if _is_executable(path) else "-"
        digest.update(f"{relative}\0{flag}\0{len(data)}\0".encode())
        digest.update(data)
    return f"sha256:{digest.hexdigest()}"


def _stage_tree(source: Path, staging: Path) -> None:
    """Copy ``source`` into ``staging`` as regular files (0o444, 0o555 when executable).

    Walks with ``os.scandir`` and ``lstat`` only. Anything that is not a regular file with a
    single link or a directory is refused with :class:`StoreError` naming the relative path.
    ``.git`` directories are skipped (not module content).
    """
    stack: list[tuple[Path, Path]] = [(source, staging)]
    while stack:
        src_dir, dst_dir = stack.pop()
        with os.scandir(src_dir) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                rel = (Path(entry.path)).relative_to(source).as_posix()
                info = entry.stat(follow_symlinks=False)
                mode = info.st_mode
                if stat.S_ISLNK(mode):
                    raise StoreError(f"{rel} is a symlink; a module holds regular files only")
                if stat.S_ISDIR(mode):
                    if entry.name == ".git":
                        continue
                    child = dst_dir / entry.name
                    child.mkdir()
                    stack.append((Path(entry.path), child))
                    continue
                if not stat.S_ISREG(mode):
                    kind = (
                        "a FIFO"
                        if stat.S_ISFIFO(mode)
                        else "a socket"
                        if stat.S_ISSOCK(mode)
                        else "a device"
                    )
                    raise StoreError(f"{rel} is {kind}; a module holds regular files only")
                if info.st_nlink != 1:
                    raise StoreError(
                        f"{rel} is a hard link ({info.st_nlink} links); a module holds regular "
                        "files only"
                    )
                destination = dst_dir / entry.name
                shutil.copyfile(entry.path, destination, follow_symlinks=False)
                destination.chmod(0o555 if mode & stat.S_IXUSR else 0o444)


# ---------------------------------------------------------------------------
# git provenance -- local reads only, never a fetch
# ---------------------------------------------------------------------------


def _git_read(source: Path, *args: str) -> str | None:
    """One local, read-only git query; ``None`` when git or the checkout is absent."""
    try:
        result = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def git_provenance(source: Path) -> tuple[str | None, str | None]:
    """``(remote url, HEAD sha)`` read with ``git -C <path> rev-parse HEAD`` and
    ``git -C <path> remote get-url origin`` only. Both ``None`` outside a checkout; the remote
    alone ``None`` when the checkout has no ``origin``."""
    sha = _git_read(source, "rev-parse", "HEAD")
    if sha is None:
        return None, None
    return _git_read(source, "remote", "get-url", "origin"), sha


# ---------------------------------------------------------------------------
# the store
# ---------------------------------------------------------------------------


class ModuleStore:
    """Lockfile + snapshots under one root. ``ModuleStore()`` uses the default root."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_store_root()
        self.lockfile = self.root / LOCKFILE_NAME
        self.snapshots = self.root / SNAPSHOTS_DIRNAME

    # -- reads ------------------------------------------------------------------

    def entries(self) -> list[LockEntry]:
        return load_lockfile(self.root)

    def get(self, module_id: str) -> LockEntry | None:
        return next((e for e in self.entries() if e.id == module_id), None)

    # -- add ----------------------------------------------------------------------

    def add(self, source: Path) -> LockEntry:
        """Install the module at ``source``: stage, check, digest, publish (module docstring).

        Raises :class:`StoreError` for a source that is not a directory or holds anything but
        regular files and directories, and :class:`ModuleCheckError` when the staged copy
        fails conformance. In both cases nothing reaches the lockfile or ``snapshots/``.
        """
        source = Path(source).resolve()
        if not source.is_dir():
            raise StoreError(f"{source} is not a directory")
        self.snapshots.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.snapshots))
        try:
            _stage_tree(source, staging)
            report = check_module(staging)
            if not report.ok:
                raise ModuleCheckError(source, report)
            manifest = yaml.safe_load((staging / "module.yaml").read_text(encoding="utf-8"))
            module_id = str(manifest["id"])
            version = str(manifest["version"])
            digest = content_digest(staging)
            snapshot = self._publish(staging, digest)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        remote, sha = git_provenance(source)
        entry = LockEntry(
            id=module_id,
            version=version,
            digest=digest,
            snapshot=str(snapshot),
            source=str(source),
            git_remote=remote,
            git_sha=sha,
            installed_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
        entries = self.entries()
        previous = next((e for e in entries if e.id == module_id), None)
        entries = [e for e in entries if e.id != module_id]
        entries.append(entry)
        self._write_lockfile(entries)
        if previous is not None and previous.digest != digest:
            self._drop_orphaned_snapshot(previous, entries)
        return entry

    def _publish(self, staging: Path, digest: str) -> Path:
        """Atomically rename the staged tree to ``snapshots/<hex>``; verify an existing one."""
        target = self.snapshots / digest.removeprefix("sha256:")
        staging.chmod(0o755)
        if not target.exists():
            try:
                os.rename(staging, target)
            except OSError:
                if not target.is_dir():
                    raise
            else:
                return target
        # The path exists (an earlier add, or a concurrent one won the rename): the published
        # bytes must be the bytes the digest names, or the lockfile would lie about them.
        existing = content_digest(target)
        if existing != digest:
            raise StoreError(
                f"snapshot {target} does not match its digest ({existing} != {digest}); "
                "refusing to record it -- remove the snapshot directory and add again"
            )
        return target

    # -- remove -------------------------------------------------------------------

    def remove(self, module_id: str) -> bool:
        """Drop ``module_id`` from the lockfile and delete its snapshot if nothing else uses it.

        Idempotent: an id that is not installed returns ``False`` and leaves the lockfile
        byte-identical.
        """
        entries = self.entries()
        target = next((e for e in entries if e.id == module_id), None)
        if target is None:
            return False
        remaining = [e for e in entries if e.id != module_id]
        self._write_lockfile(remaining)
        self._drop_orphaned_snapshot(target, remaining)
        return True

    # -- internals ----------------------------------------------------------------

    def _write_lockfile(self, entries: list[LockEntry]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": LOCKFILE_VERSION,
            "modules": [e.to_dict() for e in sorted(entries, key=lambda e: e.id)],
        }
        staging = self.lockfile.with_suffix(".json.tmp")
        staging.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(staging, self.lockfile)

    def _drop_orphaned_snapshot(self, entry: LockEntry, remaining: list[LockEntry]) -> None:
        if any(e.digest == entry.digest for e in remaining):
            return
        snapshot = snapshot_dir(entry)
        try:
            snapshot.resolve().relative_to(self.snapshots.resolve())
        except (OSError, ValueError):
            return  # never delete outside our own snapshots directory
        if snapshot.is_dir():
            shutil.rmtree(snapshot)
