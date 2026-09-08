"""Strict, privacy-safe parsing for the frozen legacy OKF writer shape."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, cast

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from .safe_fs import _DIRECTORY_OPEN_FLAGS, _FILE_READ_FLAGS, _open_directory_nofollow

MAX_OKF_BYTES: Final = 64 * 1024
MAX_ERROR_ENTRIES: Final = 100

_FIELDS: Final = frozenset(
    {
        "type",
        "title",
        "description",
        "tags",
        "sources",
        "verified",
        "confidence",
        "actor",
    }
)
_SOURCE_FIELDS: Final = frozenset({"resource", "role"})
_VERIFIED_FIELDS: Final = frozenset({"status", "by"})
_KINDS: Final = frozenset({"Decision", "Finding", "Problem", "Preference", "Procedure"})
_TAG: Final = re.compile(r"[a-z0-9][a-z0-9._/-]{0,63}\Z")
_SESSION_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SESSION_URI_PREFIX: Final = "sessionweaver://session/"
_COUNTER_NAMES: Final = (
    "scanned",
    "parsed",
    "invalid_yaml",
    "invalid_schema",
    "unsafe_path",
    "duplicate_content",
    "already_present",
    "bound",
    "legacy_unbound",
    "missing_session",
    "no_visible_evidence",
    "no_exact_match",
    "ambiguous_match",
    "oversized_evidence",
    "body_description_mismatch",
    "imported",
    "write_failures",
    "writes",
)


@dataclass(frozen=True)
class ImportError:
    """One bounded, content-free error tied only to a relative source path."""

    relative_path: str
    code: str
    field: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.relative_path, "code": self.code, "field": self.field}


@dataclass(frozen=True)
class ImportReport:
    """Deterministic legacy-import counters and bounded structural errors.

    ``scanned`` partitions into ``parsed + invalid_yaml + invalid_schema + unsafe_path``.
    Parsed includes duplicate records; body/description mismatch is an orthogonal
    observation made after safe YAML parsing, including otherwise invalid schemas.

    ``legacy_unbound`` partitions into ``missing_session + no_visible_evidence +
    no_exact_match + ambiguous_match + oversized_evidence``. ``oversized_evidence``
    counts records whose claimed session had at least one evidence body over the
    upstream bounded reader's ``MAX_BODY_CHARS`` limit that was excluded from
    exact-match search rather than aborting the record (or the batch); see the
    exact classification precedence documented on
    ``ConceptService.import_okf``.
    """

    scanned: int = 0
    parsed: int = 0
    invalid_yaml: int = 0
    invalid_schema: int = 0
    unsafe_path: int = 0
    duplicate_content: int = 0
    already_present: int = 0
    bound: int = 0
    legacy_unbound: int = 0
    missing_session: int = 0
    no_visible_evidence: int = 0
    no_exact_match: int = 0
    ambiguous_match: int = 0
    oversized_evidence: int = 0
    body_description_mismatch: int = 0
    imported: int = 0
    write_failures: int = 0
    writes: int = 0
    errors: tuple[ImportError, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            name: cast(int, getattr(self, name)) for name in _COUNTER_NAMES
        }
        payload["errors"] = [error.to_dict() for error in self.errors]
        return payload


@dataclass(frozen=True)
class _OKFRecord:
    """One validated immutable legacy record; values are never emitted in reports."""

    relative_path: str
    original_bytes: bytes
    legacy_id: str
    kind: str
    title: str
    description: str
    statement: str
    tags: tuple[str, ...]
    normalized_tag_indexes: tuple[int, ...]
    confidence: float
    session_id: str
    source_uri: str
    actor: str
    verified_status: str

    def content_fingerprint(self) -> str:
        payload = [
            self.kind,
            self.title,
            self.description,
            self.statement,
            list(self.tags),
            self.confidence,
            self.session_id,
            self.source_uri,
            self.actor,
            self.verified_status,
        ]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class _OKFScan:
    records: tuple[_OKFRecord, ...]
    report: ImportReport


class _UnsafeYAML(yaml.YAMLError):
    pass


class _StrictSafeLoader(yaml.SafeLoader):
    """SafeLoader that also rejects duplicate and merge keys."""

    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        if not isinstance(node, MappingNode):
            raise _UnsafeYAML("mapping required")
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge" or key_node.value == "<<":
                raise _UnsafeYAML("merge keys are forbidden")
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in result
            except TypeError as exc:
                raise _UnsafeYAML("mapping keys must be scalar") from exc
            if duplicate:
                raise _UnsafeYAML("duplicate mapping key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


@dataclass
class _Counters:
    scanned: int = 0
    parsed: int = 0
    invalid_yaml: int = 0
    invalid_schema: int = 0
    unsafe_path: int = 0
    duplicate_content: int = 0
    already_present: int = 0
    bound: int = 0
    legacy_unbound: int = 0
    missing_session: int = 0
    no_visible_evidence: int = 0
    no_exact_match: int = 0
    ambiguous_match: int = 0
    oversized_evidence: int = 0
    body_description_mismatch: int = 0
    imported: int = 0
    write_failures: int = 0
    writes: int = 0

    def report(self, errors: list[ImportError]) -> ImportReport:
        return ImportReport(**asdict(self), errors=tuple(errors))


@dataclass(frozen=True)
class _SourceCandidate:
    relative_path: str
    unsafe: bool = False


def _byte_key(relative_path: str) -> bytes:
    return relative_path.encode("utf-8", "surrogateescape")


def _append_error(
    errors: list[ImportError],
    *,
    relative_path: str,
    code: str,
    field: str,
) -> None:
    if len(errors) < MAX_ERROR_ENTRIES:
        errors.append(ImportError(relative_path=relative_path, code=code, field=field))


def _candidate_paths(root_descriptor: int) -> list[_SourceCandidate]:
    candidates: list[_SourceCandidate] = []

    def walk(descriptor: int, prefix: str) -> None:
        names = os.listdir(descriptor)
        for name in sorted(
            names, key=lambda value: value.encode("utf-8", "surrogateescape")
        ):
            relative_path = f"{prefix}/{name}" if prefix else name
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                candidates.append(_SourceCandidate(relative_path, unsafe=True))
            elif stat.S_ISDIR(mode):
                child = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                try:
                    walk(child, relative_path)
                finally:
                    os.close(child)
            elif name.endswith(".md"):
                candidates.append(
                    _SourceCandidate(relative_path, unsafe=not stat.S_ISREG(mode))
                )

    walk(root_descriptor, "")
    return sorted(candidates, key=lambda candidate: _byte_key(candidate.relative_path))


def _read_bounded(
    root_descriptor: int,
    relative_path: str,
) -> tuple[bytes | None, str | None]:
    parts = relative_path.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        return None, "unsafe_path"
    try:
        parent = os.dup(root_descriptor)
        try:
            for component in parts[:-1]:
                child = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=parent)
                os.close(parent)
                parent = child
            descriptor = os.open(parts[-1], _FILE_READ_FLAGS, dir_fd=parent)
        finally:
            os.close(parent)
    except OSError:
        return None, "unsafe_path"
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            return None, "unsafe_path"
        if metadata.st_size > MAX_OKF_BYTES:
            return None, "file_too_large"
        chunks: list[bytes] = []
        remaining = MAX_OKF_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > MAX_OKF_BYTES:
            return None, "file_too_large"
        return payload, None
    finally:
        os.close(descriptor)


def _split_document(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise yaml.YAMLError("frontmatter opener required")
    end = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n") == "---"
        ),
        None,
    )
    if end is None:
        raise yaml.YAMLError("frontmatter closer required")
    frontmatter = "".join(lines[1:end])
    body_lines = lines[end + 1 :]
    if body_lines and body_lines[0] in ("\n", "\r\n"):
        body_lines = body_lines[1:]
    return frontmatter, "".join(body_lines)


def _load_frontmatter(value: str) -> Any:
    for token in yaml.scan(value):
        if isinstance(token, (AnchorToken, AliasToken, TagToken)):
            raise _UnsafeYAML("anchors, aliases, and explicit tags are forbidden")
    # _StrictSafeLoader subclasses yaml.SafeLoader and only *narrows* it
    # (rejecting merge keys, duplicates, anchors/aliases/tags), so this is
    # not an unsafe load; bandit cannot see through the subclass.
    return yaml.load(value, Loader=_StrictSafeLoader)  # nosec B506


def _field_sets(
    value: dict[object, Any],
    expected: frozenset[str],
    path: str,
) -> list[tuple[str, str]]:
    raw_keys = set(value)
    issues: list[tuple[str, str]] = []
    if any(not isinstance(key, str) for key in raw_keys):
        issues.append(("invalid_field_name", path or "/"))
    keys = {key for key in raw_keys if isinstance(key, str)}
    issues.extend(("missing_field", f"{path}/{key}") for key in sorted(expected - keys))
    issues.extend(("extra_field", f"{path}/{key}") for key in sorted(keys - expected))
    return issues


def _text(
    value: object,
    *,
    field: str,
    maximum: int,
) -> tuple[str | None, list[tuple[str, str]]]:
    if not isinstance(value, str):
        return None, [("invalid_type", field)]
    try:
        canonical = value.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeDecodeError:
        return None, [("invalid_unicode", field)]
    if not canonical.strip():
        return None, [("blank", field)]
    if len(canonical) > maximum:
        return None, [("too_long", field)]
    return canonical, []


def _schema_record(
    value: object,
    *,
    relative_path: str,
    original_bytes: bytes,
    body: str,
) -> tuple[_OKFRecord | None, list[tuple[str, str]]]:
    if not isinstance(value, dict):
        return None, [("invalid_type", "/")]
    issues = _field_sets(value, _FIELDS, "")

    raw_kind = value.get("type")
    kind: str | None = None
    if not isinstance(raw_kind, str):
        issues.append(("invalid_type", "/type"))
    elif raw_kind not in _KINDS:
        issues.append(("invalid_choice", "/type"))
    else:
        kind = raw_kind

    title, title_issues = _text(value.get("title"), field="/title", maximum=120)
    issues.extend(title_issues)
    description, description_issues = _text(
        value.get("description"), field="/description", maximum=500
    )
    issues.extend(description_issues)
    if not body.strip():
        issues.append(("blank", "/body"))

    raw_tags = value.get("tags")
    tags: tuple[str, ...] = ()
    normalized_tag_indexes: tuple[int, ...] = ()
    if not isinstance(raw_tags, list):
        issues.append(("invalid_type", "/tags"))
    elif not 2 <= len(raw_tags) <= 5:
        issues.append(("invalid_count", "/tags"))
    else:
        seen_tags: set[str] = set()
        parsed_tags: list[str] = []
        normalized_indexes: list[int] = []
        for index, tag in enumerate(raw_tags):
            if not isinstance(tag, str):
                issues.append(("invalid_type", f"/tags/{index}"))
                continue
            canonical_tag = tag.lower()
            if not _TAG.fullmatch(canonical_tag):
                issues.append(("invalid_format", f"/tags/{index}"))
            elif canonical_tag in seen_tags:
                issues.append(("duplicate_item", f"/tags/{index}"))
            else:
                seen_tags.add(canonical_tag)
                parsed_tags.append(canonical_tag)
                if canonical_tag != tag:
                    normalized_indexes.append(index)
        tags = tuple(sorted(parsed_tags))
        normalized_tag_indexes = tuple(normalized_indexes)

    raw_confidence = value.get("confidence")
    confidence: float | None = None
    if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
        issues.append(("invalid_type", "/confidence"))
    elif (
        not math.isfinite(float(raw_confidence))
        or not 0.5 <= float(raw_confidence) <= 1.0
    ):
        issues.append(("out_of_range", "/confidence"))
    else:
        confidence = float(raw_confidence)

    actor, actor_issues = _text(value.get("actor"), field="/actor", maximum=128)
    issues.extend(actor_issues)

    source_uri: str | None = None
    session_id: str | None = None
    raw_sources = value.get("sources")
    if not isinstance(raw_sources, list):
        issues.append(("invalid_type", "/sources"))
    elif len(raw_sources) != 1:
        issues.append(("invalid_count", "/sources"))
    elif not isinstance(raw_sources[0], dict):
        issues.append(("invalid_type", "/sources/0"))
    else:
        source = raw_sources[0]
        issues.extend(_field_sets(source, _SOURCE_FIELDS, "/sources/0"))
        resource = source.get("resource")
        if not isinstance(resource, str):
            issues.append(("invalid_type", "/sources/0/resource"))
        elif not resource.startswith(_SESSION_URI_PREFIX):
            issues.append(("invalid_format", "/sources/0/resource"))
        else:
            possible_id = resource.removeprefix(_SESSION_URI_PREFIX)
            if not _SESSION_ID.fullmatch(possible_id):
                issues.append(("invalid_format", "/sources/0/resource"))
            else:
                source_uri = resource
                session_id = possible_id
        if source.get("role") != "transcript":
            issues.append(("invalid_choice", "/sources/0/role"))

    verified_status: str | None = None
    verifier: str | None = None
    raw_verified = value.get("verified")
    if not isinstance(raw_verified, dict):
        issues.append(("invalid_type", "/verified"))
    else:
        issues.extend(_field_sets(raw_verified, _VERIFIED_FIELDS, "/verified"))
        raw_status = raw_verified.get("status")
        if raw_status != "machine-confirmed":
            issues.append(("invalid_choice", "/verified/status"))
        else:
            verified_status = raw_status
        verifier, verifier_issues = _text(
            raw_verified.get("by"), field="/verified/by", maximum=128
        )
        issues.extend(verifier_issues)
    if actor is not None and verifier is not None and actor != verifier:
        issues.append(("actor_mismatch", "/verified/by"))

    if issues or None in (
        kind,
        title,
        description,
        confidence,
        actor,
        source_uri,
        session_id,
        verified_status,
    ):
        return None, issues
    digest = hashlib.sha256(original_bytes).hexdigest()
    return (
        _OKFRecord(
            relative_path=relative_path,
            original_bytes=original_bytes,
            legacy_id="legacy:" + digest,
            kind=cast(str, kind),
            title=cast(str, title),
            description=cast(str, description),
            statement=body,
            tags=tags,
            normalized_tag_indexes=normalized_tag_indexes,
            confidence=cast(float, confidence),
            session_id=cast(str, session_id),
            source_uri=cast(str, source_uri),
            actor=cast(str, actor),
            verified_status=cast(str, verified_status),
        ),
        [],
    )


def _scan_open_okf(root_descriptor: int) -> _OKFScan:
    counters = _Counters()
    errors: list[ImportError] = []
    records: list[_OKFRecord] = []
    seen_ids: set[str] = set()
    seen_content: set[str] = set()

    for candidate in _candidate_paths(root_descriptor):
        counters.scanned += 1
        relative_path = candidate.relative_path
        if candidate.unsafe:
            counters.unsafe_path += 1
            _append_error(
                errors,
                relative_path=relative_path,
                code="unsafe_path",
                field="/",
            )
            continue
        original_bytes, read_error = _read_bounded(root_descriptor, relative_path)
        if read_error is not None or original_bytes is None:
            if read_error == "unsafe_path":
                counters.unsafe_path += 1
            else:
                counters.invalid_schema += 1
            _append_error(
                errors,
                relative_path=relative_path,
                code=read_error or "unsafe_path",
                field="/",
            )
            continue
        try:
            text = original_bytes.decode("utf-8")
        except UnicodeDecodeError:
            counters.invalid_schema += 1
            _append_error(
                errors,
                relative_path=relative_path,
                code="invalid_utf8",
                field="/",
            )
            continue
        try:
            frontmatter, body = _split_document(text)
            loaded = _load_frontmatter(frontmatter)
        except _UnsafeYAML:
            counters.invalid_yaml += 1
            _append_error(
                errors,
                relative_path=relative_path,
                code="unsafe_yaml",
                field="/",
            )
            continue
        except yaml.YAMLError:
            counters.invalid_yaml += 1
            _append_error(
                errors,
                relative_path=relative_path,
                code="invalid_yaml",
                field="/",
            )
            continue
        if isinstance(loaded, dict):
            observed_description, _ = _text(
                loaded.get("description"), field="/description", maximum=500
            )
            if observed_description is not None and body != observed_description:
                counters.body_description_mismatch += 1
        record, schema_issues = _schema_record(
            loaded,
            relative_path=relative_path,
            original_bytes=original_bytes,
            body=body,
        )
        if record is None:
            counters.invalid_schema += 1
            for code, field in schema_issues:
                _append_error(
                    errors,
                    relative_path=relative_path,
                    code=code,
                    field=field,
                )
            continue
        counters.parsed += 1
        for index in record.normalized_tag_indexes:
            _append_error(
                errors,
                relative_path=relative_path,
                code="normalized_tag",
                field=f"/tags/{index}",
            )
        content_fingerprint = record.content_fingerprint()
        if record.legacy_id in seen_ids or content_fingerprint in seen_content:
            counters.duplicate_content += 1
            _append_error(
                errors,
                relative_path=relative_path,
                code="duplicate_content",
                field="/",
            )
            continue
        seen_ids.add(record.legacy_id)
        seen_content.add(content_fingerprint)
        records.append(record)

    return _OKFScan(records=tuple(records), report=counters.report(errors))


def _scan_okf(root: Path) -> _OKFScan:
    """Parse an OKF tree through descriptors without opening any database."""
    try:
        root_descriptor = _open_directory_nofollow(root.expanduser())
    except OSError as exc:
        raise ValueError("OKF root must be a non-symlink directory") from exc
    try:
        try:
            return _scan_open_okf(root_descriptor)
        except OSError:
            raise ValueError("OKF tree could not be enumerated safely") from None
    finally:
        os.close(root_descriptor)
