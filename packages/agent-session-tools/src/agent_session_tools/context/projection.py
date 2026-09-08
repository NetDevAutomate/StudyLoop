"""Disposable scope-aware Markdown projection from authoritative concept state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from .public import AgentContext, open_context
from .response import read_boundary
from .scope import ScopeError

from .authorization import _current_standings, authorized_concepts
from .concept_schema import verify_installed_schema
from .safe_fs import (
    _DIRECTORY_OPEN_FLAGS,
    _FILE_CREATE_FLAGS,
    _FILE_READ_FLAGS,
    _open_directory_nofollow,
)

PROJECTION_SCHEMA_VERSION = 1
_MARKER_NAME = ".session-weaver-projection.json"
_MANIFEST_NAME = ".session-weaver-projection-manifest.json"


class _FilenameCollision(RuntimeError):
    """Two authorized concepts would claim the same generated filename."""


class _StaleSnapshot(RuntimeError):
    """The authorized DB state changed while projection bytes were being published."""


@dataclass(frozen=True)
class ProjectionReport:
    """Content-free receipt for one projection attempt."""

    status: str
    selected: int
    rendered: int
    unchanged: int
    created: int
    replaced: int
    deleted: int
    conflicts: int
    skipped_unavailable: int
    skipped_retired: int
    writes: int
    scope: str
    project: str | None
    policy_digest: str
    access_instance: str
    access_revision: int
    logical_state_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selected": self.selected,
            "rendered": self.rendered,
            "unchanged": self.unchanged,
            "created": self.created,
            "replaced": self.replaced,
            "deleted": self.deleted,
            "conflicts": self.conflicts,
            "skipped_unavailable": self.skipped_unavailable,
            "skipped_retired": self.skipped_retired,
            "writes": self.writes,
            "scope": self.scope,
            "project": self.project,
            "policy_digest": self.policy_digest,
            "access_instance": self.access_instance,
            "access_revision": self.access_revision,
            "logical_state_hash": self.logical_state_hash,
        }


@dataclass(frozen=True)
class _ProjectedConcept:
    concept_id: str
    assertion_id: str | None
    binding_state: str
    kind: str
    title: str
    statement: str
    tags: tuple[str, ...]
    confidence: float
    source_uri: str
    standing: str
    legacy_file_sha256: str | None


@dataclass(frozen=True)
class _Snapshot:
    concepts: tuple[_ProjectedConcept, ...]
    skipped_unavailable: int
    skipped_retired: int
    scope: str
    project: str | None
    policy_digest: str
    access_instance: str
    access_revision: int
    logical_state_hash: str


@dataclass(frozen=True)
class _OutputDirectory:
    parent_descriptor: int
    descriptor: int
    name: str
    path: Path
    identity: tuple[int, int]


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int
    sha256: str


@dataclass
class _Mutation:
    kind: str
    name: str
    written: _FileIdentity | None = None
    backup_name: str | None = None
    backup_identity: _FileIdentity | None = None


@dataclass(frozen=True)
class _Rendered:
    concept_id: str
    payload: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True)
class _Preflight:
    unchanged: tuple[str, ...] = ()
    created: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    conflicts: int = 0
    marker_present: bool = False
    manifest_payload: bytes | None = None
    previous_manifest: dict[str, dict[str, str]] = field(default_factory=dict)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_concept_schema(conn: sqlite3.Connection) -> None:
    verify_installed_schema(conn)


def _capture_snapshot(context: AgentContext) -> _Snapshot:
    _require_concept_schema(context.conn)
    concepts: list[_ProjectedConcept] = []
    skipped_unavailable = 0
    skipped_retired = 0
    logical_rows: list[object] = []
    authorized_by_id = {
        authorized.concept_id: authorized
        for authorized in authorized_concepts(context, project=context.project)
    }
    for concept_id, standing in _current_standings(context):
        if standing == "retired":
            skipped_retired += 1
            logical_rows.append((concept_id, standing, "retired"))
            continue
        authorized = authorized_by_id.get(concept_id)
        if authorized is None:
            skipped_unavailable += 1
            logical_rows.append((concept_id, standing, "unavailable"))
            continue
        root = authorized.root
        concept = _ProjectedConcept(
            concept_id=concept_id,
            assertion_id=cast(str | None, root["assertion_id"]),
            binding_state=cast(str, root["binding_state"]),
            kind=cast(str, root["kind"]),
            title=cast(str, root["title"]),
            statement=cast(str, root["statement"]),
            tags=tuple(json.loads(cast(str, root["canonical_tags"]))),
            confidence=float(root["confidence"]),
            source_uri=cast(str, root["source_uri"]),
            standing=standing,
            legacy_file_sha256=cast(str | None, root["legacy_file_sha256"]),
        )
        concepts.append(concept)
        logical_rows.append(
            (
                concept.concept_id,
                concept.assertion_id,
                concept.binding_state,
                concept.kind,
                concept.title,
                concept.statement,
                concept.tags,
                concept.confidence,
                concept.source_uri,
                concept.standing,
                concept.legacy_file_sha256,
            )
        )
    access = context.conn.execute(
        "SELECT instance,revision FROM context_access_state WHERE id=1"
    ).fetchone()
    if access is None or type(access[1]) is not int:
        raise RuntimeError("Context access generation is unavailable")
    logical_hash = hashlib.sha256(
        _canonical_json(logical_rows).encode("utf-8")
    ).hexdigest()
    return _Snapshot(
        concepts=tuple(concepts),
        skipped_unavailable=skipped_unavailable,
        skipped_retired=skipped_retired,
        scope=context.scope.value,
        project=context.project,
        policy_digest=context.policy.digest,
        access_instance=cast(str, access[0]),
        access_revision=cast(int, access[1]),
        logical_state_hash=logical_hash,
    )


def _slug(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title).casefold()
    parts: list[str] = []
    current: list[str] = []
    for character in normalized:
        if character.isalnum():
            current.append(character)
        elif current:
            parts.append("".join(current))
            current = []
    if current:
        parts.append("".join(current))
    slug = "-".join(parts)[:80].strip("-")
    return slug or "concept"


def _filename(concept: _ProjectedConcept) -> str:
    if concept.binding_state == "bound":
        if concept.assertion_id is None:
            raise RuntimeError("Bound projection lost its assertion identity")
        prefix = concept.assertion_id[:12]
    else:
        if concept.legacy_file_sha256 is None:
            raise RuntimeError("Legacy projection lost its immutable byte identity")
        prefix = "legacy-" + concept.legacy_file_sha256[:12]
    return f"{prefix}-{_slug(concept.title)}.md"


def _render(concept: _ProjectedConcept) -> bytes:
    citation_binding = (
        "machine-confirmed" if concept.binding_state == "bound" else "absent"
    )
    provenance = (
        "scope-visible-citation-closure"
        if concept.binding_state == "bound"
        else "scope-visible-stored-session"
    )
    lines = [
        "---",
        f"session_weaver_projection: {PROJECTION_SCHEMA_VERSION}",
        f"concept_id: {json.dumps(concept.concept_id, ensure_ascii=False)}",
        f"concept_kind: {json.dumps(concept.kind, ensure_ascii=False)}",
        f"binding_state: {json.dumps(concept.binding_state)}",
        f"standing: {json.dumps(concept.standing)}",
        'model_authorship: "model-proposed"',
        f"citation_binding: {json.dumps(citation_binding)}",
        f"title: {json.dumps(concept.title, ensure_ascii=False)}",
        f"tags: {_canonical_json(list(concept.tags))}",
        f"confidence: {_canonical_json(concept.confidence)}",
        f"source_uri: {json.dumps(concept.source_uri, ensure_ascii=False)}",
        f"source_provenance: {json.dumps(provenance)}",
        "---",
        (
            "<!-- session-weaver-projection owner=session-weaver "
            f"schema={PROJECTION_SCHEMA_VERSION} concept={concept.concept_id} -->"
        ),
        "",
        concept.statement,
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _render_all(snapshot: _Snapshot) -> dict[str, _Rendered]:
    rendered: dict[str, _Rendered] = {}
    for concept in snapshot.concepts:
        name = _filename(concept)
        if name in rendered:
            raise _FilenameCollision("Projection filename collision")
        rendered[name] = _Rendered(
            concept_id=concept.concept_id, payload=_render(concept)
        )
    return dict(sorted(rendered.items()))


@contextmanager
def _open_output_directory(path: Path) -> Iterator[_OutputDirectory]:
    raw = path.expanduser()
    if any(part in (".", "..") for part in raw.parts):
        raise OSError("Unsafe output directory component")
    absolute = Path(os.path.abspath(os.fspath(raw)))
    if absolute.name in ("", ".", ".."):
        raise OSError("Output directory must name a leaf directory")
    # Resolve ancestor symlinks (e.g. macOS's /tmp -> /private/tmp) up front so the
    # O_NOFOLLOW walk below only ever guards the leaf itself, not benign OS-level
    # indirections in every ancestor. The leaf name is kept unresolved: it is still
    # opened with O_NOFOLLOW, so a symlinked leaf is refused exactly as before.
    resolved_parent = Path(os.path.realpath(os.fspath(absolute.parent)))
    resolved = resolved_parent / absolute.name
    parent = _open_directory_nofollow(resolved_parent)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(resolved.name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent)
        except FileNotFoundError:
            os.mkdir(resolved.name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
            descriptor = os.open(resolved.name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("Output path is not a directory")
        yield _OutputDirectory(
            parent_descriptor=parent,
            descriptor=descriptor,
            name=resolved.name,
            path=resolved,
            identity=(metadata.st_dev, metadata.st_ino),
        )
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def _checkpoint(_name: str) -> None:
    """No-op fault boundary monkeypatched by filesystem interruption tests."""


def _recheck_output(output: _OutputDirectory) -> None:
    metadata = os.stat(
        output.name, dir_fd=output.parent_descriptor, follow_symlinks=False
    )
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or (metadata.st_dev, metadata.st_ino) != output.identity
    ):
        raise OSError("Projection output directory identity changed")
    reopened = _open_directory_nofollow(output.path)
    try:
        current = os.fstat(reopened)
        if (current.st_dev, current.st_ino) != output.identity:
            raise OSError("Projection output directory containment changed")
    finally:
        os.close(reopened)


def _write_atomic(
    directory: _OutputDirectory | int,
    name: str,
    payload: bytes,
) -> _FileIdentity:
    directory_descriptor = (
        directory.descriptor if isinstance(directory, _OutputDirectory) else directory
    )
    temporary = f".session-weaver-projection-{uuid4().hex}.tmp"
    descriptor = os.open(
        temporary, _FILE_CREATE_FLAGS, 0o600, dir_fd=directory_descriptor
    )
    descriptor_open = True
    temporary_exists = True
    try:
        _checkpoint("after_temp_open")
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "wb")
        descriptor_open = False
        with stream:
            stream.write(payload)
            stream.flush()
            _checkpoint("after_temp_write")
            os.fsync(stream.fileno())
            _checkpoint("after_temp_fsync")
        if isinstance(directory, _OutputDirectory):
            _recheck_output(directory)
        _checkpoint("before_replace")
        os.replace(
            temporary,
            name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        temporary_exists = False
        _checkpoint("after_replace")
        os.fsync(directory_descriptor)
        _checkpoint("after_directory_fsync")
        return _file_identity(directory_descriptor, name)
    finally:
        if descriptor_open:
            os.close(descriptor)
        if temporary_exists:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=directory_descriptor)


def _read_regular(directory_descriptor: int, name: str) -> bytes:
    metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    if not stat.S_ISREG(metadata.st_mode):
        raise OSError("Projection entry is not a regular file")
    descriptor = os.open(name, _FILE_READ_FLAGS, dir_fd=directory_descriptor)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise OSError("Projection entry changed while opening")
        chunks: list[bytes] = []
        remaining = 16 * 1024 * 1024 + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > 16 * 1024 * 1024:
            raise OSError("Projection entry exceeds the bounded reader limit")
        return payload
    finally:
        os.close(descriptor)


def _file_identity(directory_descriptor: int, name: str) -> _FileIdentity:
    metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    payload = _read_regular(directory_descriptor, name)
    return _FileIdentity(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _matching_identity(
    directory_descriptor: int,
    name: str,
    expected: _FileIdentity,
) -> bool:
    try:
        return _file_identity(directory_descriptor, name) == expected
    except (FileNotFoundError, OSError):
        return False


_HEX64 = re.compile(r"[0-9a-f]{64}")
_CONCEPT_ID = re.compile(r"[0-9a-f]{32,64}")


def _generated_name(name: str) -> bool:
    if not name.endswith(".md") or "/" in name or "\\" in name:
        return False
    stem = name[:-3]
    if stem.startswith("legacy-"):
        stem = stem.removeprefix("legacy-")
    if len(stem) < 14 or not re.fullmatch(r"[0-9a-f]{12}-.*", stem):
        return False
    slug = stem[13:]
    return bool(slug) and all(
        part and all(character.isalnum() for character in part)
        for part in slug.split("-")
    )


def _owned_bytes(payload: bytes, concept_id: str, sha256: str) -> bool:
    marker = (
        "<!-- session-weaver-projection owner=session-weaver "
        f"schema={PROJECTION_SCHEMA_VERSION} concept={concept_id} -->"
    ).encode()
    return hashlib.sha256(payload).hexdigest() == sha256 and marker in payload


def _parse_manifest(payload: bytes) -> dict[str, dict[str, str]]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Projection manifest is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("Projection manifest must be a mapping")
    result: dict[str, dict[str, str]] = {}
    for name, entry in value.items():
        if (
            not isinstance(name, str)
            or not _generated_name(name)
            or not isinstance(entry, dict)
            or set(entry) != {"concept_id", "sha256"}
            or not isinstance(entry["concept_id"], str)
            or not isinstance(entry["sha256"], str)
            or _HEX64.fullmatch(entry["sha256"]) is None
        ):
            raise ValueError("Projection manifest entry is invalid")
        concept_id = entry["concept_id"]
        if not (
            _CONCEPT_ID.fullmatch(concept_id)
            or (concept_id.startswith("legacy:") and _HEX64.fullmatch(concept_id[7:]))
        ):
            raise ValueError("Projection manifest concept identity is invalid")
        result[name] = {"concept_id": concept_id, "sha256": entry["sha256"]}
    if payload != (_canonical_json(result) + "\n").encode():
        raise ValueError("Projection manifest is not canonical")
    return result


def _preflight(
    descriptor: int,
    names: set[str],
    rendered: dict[str, _Rendered],
    marker_payload: bytes,
) -> _Preflight:
    if not names:
        return _Preflight(created=tuple(rendered))
    if _MARKER_NAME not in names:
        return _Preflight(conflicts=len(names))
    manifest_payload: bytes | None = None
    try:
        if _read_regular(descriptor, _MARKER_NAME) != marker_payload:
            return _Preflight(conflicts=1)
        if _MANIFEST_NAME in names:
            manifest_payload = _read_regular(descriptor, _MANIFEST_NAME)
            previous = _parse_manifest(manifest_payload)
        else:
            previous = {}
    except (OSError, ValueError):
        return _Preflight(conflicts=1)

    unchanged: list[str] = []
    created: list[str] = []
    replaced: list[str] = []
    deleted: list[str] = []
    conflicts = 0
    accounted = {_MARKER_NAME, _MANIFEST_NAME}
    for name, entry in previous.items():
        accounted.add(name)
        try:
            payload = _read_regular(descriptor, name)
        except FileNotFoundError:
            payload = None
        except OSError:
            conflicts += 1
            continue
        if payload is not None and not _owned_bytes(
            payload, entry["concept_id"], entry["sha256"]
        ):
            conflicts += 1
            continue
        desired = rendered.get(name)
        if desired is None:
            if payload is not None:
                deleted.append(name)
        elif payload is None:
            created.append(name)
        elif payload == desired.payload and entry == {
            "concept_id": desired.concept_id,
            "sha256": desired.sha256,
        }:
            unchanged.append(name)
        else:
            replaced.append(name)

    for name, desired in rendered.items():
        if name in previous:
            continue
        accounted.add(name)
        if name not in names:
            created.append(name)
            continue
        try:
            payload = _read_regular(descriptor, name)
        except OSError:
            conflicts += 1
            continue
        if payload == desired.payload and _owned_bytes(
            payload, desired.concept_id, desired.sha256
        ):
            unchanged.append(name)
        else:
            conflicts += 1

    conflicts += len(names - accounted)
    return _Preflight(
        unchanged=tuple(sorted(unchanged)),
        created=tuple(sorted(created)),
        replaced=tuple(sorted(replaced)),
        deleted=tuple(sorted(deleted)),
        conflicts=conflicts,
        marker_present=True,
        manifest_payload=manifest_payload,
        previous_manifest=previous,
    )


def _entry_exists(descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


class _Publisher:
    """Descriptor-anchored publication transaction with identity-guarded rollback."""

    def __init__(
        self,
        output: _OutputDirectory,
        names: set[str],
        rendered: dict[str, _Rendered],
        preflight: _Preflight,
        marker_payload: bytes,
        manifest_payload: bytes,
    ) -> None:
        self.output = output
        self.names = names
        self.rendered = rendered
        self.preflight = preflight
        self.marker_payload = marker_payload
        self.manifest_payload = manifest_payload
        self.mutations: list[_Mutation] = []

    @property
    def descriptor(self) -> int:
        return self.output.descriptor

    def _verify_exact(self, name: str, payload: bytes) -> _FileIdentity:
        if _read_regular(self.descriptor, name) != payload:
            raise OSError("Projection entry changed after preflight")
        return _file_identity(self.descriptor, name)

    def _verify_owned(self, name: str, entry: dict[str, str]) -> _FileIdentity:
        payload = _read_regular(self.descriptor, name)
        if not _owned_bytes(payload, entry["concept_id"], entry["sha256"]):
            raise OSError("Managed projection entry changed after preflight")
        return _file_identity(self.descriptor, name)

    def _create(self, name: str, payload: bytes) -> None:
        _recheck_output(self.output)
        if _entry_exists(self.descriptor, name):
            raise OSError("Projection create target appeared after preflight")
        try:
            identity = _write_atomic(self.output, name, payload)
        except BaseException:
            try:
                identity = _file_identity(self.descriptor, name)
            except OSError:
                pass
            else:
                if identity.sha256 == hashlib.sha256(payload).hexdigest():
                    self.mutations.append(_Mutation("created", name, written=identity))
            raise
        self.mutations.append(_Mutation("created", name, written=identity))

    def _backup(
        self,
        kind: str,
        name: str,
        identity: _FileIdentity,
    ) -> _Mutation:
        _recheck_output(self.output)
        if _file_identity(self.descriptor, name) != identity:
            raise OSError("Projection entry changed before replacement")
        backup_name = f".session-weaver-projection-{uuid4().hex}.bak"
        os.replace(
            name,
            backup_name,
            src_dir_fd=self.descriptor,
            dst_dir_fd=self.descriptor,
        )
        mutation = _Mutation(
            kind,
            name,
            backup_name=backup_name,
            backup_identity=identity,
        )
        self.mutations.append(mutation)
        _checkpoint("after_backup")
        os.fsync(self.descriptor)
        return mutation

    def _replace_exact(self, name: str, old: bytes, new: bytes) -> None:
        mutation = self._backup("replaced", name, self._verify_exact(name, old))
        try:
            mutation.written = _write_atomic(self.output, name, new)
        except BaseException:
            try:
                identity = _file_identity(self.descriptor, name)
            except OSError:
                pass
            else:
                if identity.sha256 == hashlib.sha256(new).hexdigest():
                    mutation.written = identity
            raise

    def _replace_owned(self, name: str, entry: dict[str, str], new: bytes) -> None:
        mutation = self._backup("replaced", name, self._verify_owned(name, entry))
        try:
            mutation.written = _write_atomic(self.output, name, new)
        except BaseException:
            try:
                identity = _file_identity(self.descriptor, name)
            except OSError:
                pass
            else:
                if identity.sha256 == hashlib.sha256(new).hexdigest():
                    mutation.written = identity
            raise

    def _delete_owned(self, name: str, entry: dict[str, str]) -> None:
        self._backup("deleted", name, self._verify_owned(name, entry))

    def apply(self) -> None:
        _recheck_output(self.output)
        if set(os.listdir(self.descriptor)) != self.names:
            raise OSError("Projection directory changed after preflight")
        if self.preflight.marker_present:
            self._verify_exact(_MARKER_NAME, self.marker_payload)
        else:
            self._create(_MARKER_NAME, self.marker_payload)

        for name in self.preflight.created:
            self._create(name, self.rendered[name].payload)
        for name in self.preflight.replaced:
            self._replace_owned(
                name,
                self.preflight.previous_manifest[name],
                self.rendered[name].payload,
            )
        for name in self.preflight.deleted:
            self._delete_owned(name, self.preflight.previous_manifest[name])
        for name in self.preflight.unchanged:
            desired = self.rendered[name]
            payload = _read_regular(self.descriptor, name)
            if payload != desired.payload or not _owned_bytes(
                payload, desired.concept_id, desired.sha256
            ):
                raise OSError("Unchanged projection entry changed before manifest")

        changed = bool(
            self.preflight.created
            or self.preflight.replaced
            or self.preflight.deleted
            or self.preflight.manifest_payload is None
        )
        if changed:
            _checkpoint("before_manifest")
            if self.preflight.manifest_payload is None:
                self._create(_MANIFEST_NAME, self.manifest_payload)
            else:
                self._replace_exact(
                    _MANIFEST_NAME,
                    self.preflight.manifest_payload,
                    self.manifest_payload,
                )
            _checkpoint("after_manifest")

    def validate_published(self) -> None:
        _recheck_output(self.output)
        self._verify_exact(_MARKER_NAME, self.marker_payload)
        self._verify_exact(_MANIFEST_NAME, self.manifest_payload)
        for name, desired in self.rendered.items():
            payload = _read_regular(self.descriptor, name)
            if payload != desired.payload or not _owned_bytes(
                payload, desired.concept_id, desired.sha256
            ):
                raise OSError("Published projection entry changed before validation")
        backups = {
            cast(str, mutation.backup_name)
            for mutation in self.mutations
            if mutation.backup_name is not None
        }
        expected = {*self.rendered, _MARKER_NAME, _MANIFEST_NAME, *backups}
        if set(os.listdir(self.descriptor)) != expected:
            raise OSError("Projection directory changed during publication")

    def rollback(self) -> int:
        """Best-effort unwind of every recorded mutation through the held descriptor.

        Every filesystem call is contained per-mutation: one failure is counted as
        a conflict and the unwind continues for the remaining mutations rather than
        aborting (F4). A backup is only trusted, and the live content only touched,
        after its identity is confirmed (F6) -- never delete published content before
        confirming it can be restored. A failed leading identity recheck no longer
        aborts the unwind outright (F7): the descriptor itself is unaffected by an
        external rename/symlink of the *path*, so the unwind still runs through it,
        and the recheck failure is folded in as one extra conflict.
        """
        conflicts = 0
        try:
            _recheck_output(self.output)
        except OSError:
            conflicts += 1
        for mutation in reversed(self.mutations):
            try:
                final_exists = _entry_exists(self.descriptor, mutation.name)
                current_matches_written = (
                    mutation.written is not None
                    and final_exists
                    and _matching_identity(
                        self.descriptor, mutation.name, mutation.written
                    )
                )
                if (
                    mutation.written is not None
                    and final_exists
                    and not current_matches_written
                ):
                    conflicts += 1
                if mutation.kind == "created":
                    if current_matches_written:
                        os.unlink(mutation.name, dir_fd=self.descriptor)
                    continue
                assert mutation.backup_name is not None
                assert mutation.backup_identity is not None
                backup_matches = _matching_identity(
                    self.descriptor,
                    mutation.backup_name,
                    mutation.backup_identity,
                )
                if not backup_matches:
                    conflicts += 1
                    continue
                if current_matches_written or not final_exists:
                    os.replace(
                        mutation.backup_name,
                        mutation.name,
                        src_dir_fd=self.descriptor,
                        dst_dir_fd=self.descriptor,
                    )
                else:
                    os.unlink(mutation.backup_name, dir_fd=self.descriptor)
            except OSError:
                conflicts += 1
                continue
        with suppress(OSError):
            os.fsync(self.descriptor)
        self.mutations.clear()
        return conflicts

    def commit(self) -> int:
        """Idempotently drop obsolete backups; never touch the live published tree.

        Never raises: a backup that is already gone is a no-op, a tampered backup
        or a failed unlink is recorded as a conflict and skipped, but the published
        content itself is never inspected or removed here (F2).
        """
        conflicts = 0
        backups = [
            mutation
            for mutation in self.mutations
            if mutation.backup_name is not None and mutation.backup_identity is not None
        ]
        to_unlink: list[str] = []
        for mutation in backups:
            name = cast(str, mutation.backup_name)
            identity = cast(_FileIdentity, mutation.backup_identity)
            try:
                exists = _entry_exists(self.descriptor, name)
            except OSError:
                conflicts += 1
                continue
            if not exists:
                continue
            if not _matching_identity(self.descriptor, name, identity):
                conflicts += 1
                continue
            to_unlink.append(name)
        for name in to_unlink:
            try:
                os.unlink(name, dir_fd=self.descriptor)
            except OSError:
                conflicts += 1
        if to_unlink:
            with suppress(OSError):
                os.fsync(self.descriptor)
        self.mutations.clear()
        return conflicts


def _marker_payload(snapshot: _Snapshot) -> bytes:
    return (
        _canonical_json(
            {
                "owner": "session-weaver",
                "project": snapshot.project,
                "schema": PROJECTION_SCHEMA_VERSION,
                "scope": snapshot.scope,
            }
        )
        + "\n"
    ).encode("utf-8")


def _same_snapshot(left: _Snapshot, right: _Snapshot) -> bool:
    return (
        left.scope,
        left.project,
        left.policy_digest,
        left.access_instance,
        left.access_revision,
        left.logical_state_hash,
    ) == (
        right.scope,
        right.project,
        right.policy_digest,
        right.access_instance,
        right.access_revision,
        right.logical_state_hash,
    )


def _require_fresh_snapshot(db: Path, project: str | None, expected: _Snapshot) -> None:
    with open_context(db, project=project) as context:
        observed = _capture_snapshot(context)
    if not _same_snapshot(expected, observed):
        raise _StaleSnapshot("Projection source snapshot changed")


def _report(
    snapshot: _Snapshot,
    *,
    unchanged: int = 0,
    created: int = 0,
    replaced: int = 0,
    deleted: int = 0,
    conflicts: int = 0,
    status: str = "ok",
) -> ProjectionReport:
    return ProjectionReport(
        status=status,
        selected=len(snapshot.concepts),
        rendered=len(snapshot.concepts),
        unchanged=unchanged,
        created=created,
        replaced=replaced,
        deleted=deleted,
        conflicts=conflicts,
        skipped_unavailable=snapshot.skipped_unavailable,
        skipped_retired=snapshot.skipped_retired,
        writes=created + replaced + deleted,
        scope=snapshot.scope,
        project=snapshot.project,
        policy_digest=snapshot.policy_digest,
        access_instance=snapshot.access_instance,
        access_revision=snapshot.access_revision,
        logical_state_hash=snapshot.logical_state_hash,
    )


def project_concepts(
    db: Path, out: Path, *, project: str | None = None
) -> ProjectionReport:
    """Build one disposable projection without mutating authoritative database state."""
    snapshot: _Snapshot | None = None
    preflight: _Preflight | None = None
    publisher: _Publisher | None = None
    output_manager: Any | None = None
    output_open = False
    try:
        with read_boundary() as boundary:
            with open_context(db, project=project) as context:
                snapshot = _capture_snapshot(context)
            try:
                rendered = _render_all(snapshot)
            except _FilenameCollision:
                return _report(snapshot, conflicts=1, status="conflict")
            manifest = {
                name: {"concept_id": item.concept_id, "sha256": item.sha256}
                for name, item in rendered.items()
            }
            manifest_payload = (_canonical_json(manifest) + "\n").encode("utf-8")
            marker_payload = _marker_payload(snapshot)
            try:
                output_manager = _open_output_directory(out)
                output = output_manager.__enter__()
                output_open = True
            except OSError:
                return _report(snapshot, conflicts=1, status="conflict")
            names = set(os.listdir(output.descriptor))
            preflight = _preflight(output.descriptor, names, rendered, marker_payload)
            if preflight.conflicts:
                return _report(
                    snapshot, conflicts=preflight.conflicts, status="conflict"
                )
            publisher = _Publisher(
                output,
                names,
                rendered,
                preflight,
                marker_payload,
                manifest_payload,
            )
            _checkpoint("before_prepublication_recheck")
            _require_fresh_snapshot(db, project, snapshot)
            boundary.validate()
            publisher.apply()
            _checkpoint("before_postpublication_recheck")
            _require_fresh_snapshot(db, project, snapshot)
            boundary.validate()
            publisher.validate_published()
    except (ScopeError, _StaleSnapshot):
        if snapshot is None:
            raise
        rollback_conflicts = publisher.rollback() if publisher is not None else 0
        return _report(
            snapshot,
            conflicts=rollback_conflicts,
            status="stale_snapshot",
        )
    except (OSError, RuntimeError):
        if snapshot is None:
            raise
        rollback_conflicts = publisher.rollback() if publisher is not None else 0
        return _report(
            snapshot,
            conflicts=rollback_conflicts,
            status="storage_failure",
        )
    else:
        assert snapshot is not None and preflight is not None and publisher is not None
        commit_conflicts = publisher.commit()
        return _report(
            snapshot,
            unchanged=len(preflight.unchanged),
            created=len(preflight.created),
            replaced=len(preflight.replaced),
            deleted=len(preflight.deleted),
            conflicts=commit_conflicts,
        )
    finally:
        if output_open and output_manager is not None:
            with suppress(OSError):
                output_manager.__exit__(None, None, None)
