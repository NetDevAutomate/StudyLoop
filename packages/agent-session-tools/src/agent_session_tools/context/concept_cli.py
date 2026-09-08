"""session-context wind-down/concept verbs over the ConceptService seam.

Lifted from the SessionWeaver reference CLI's bounded-input, safe-filesystem
handlers: input files are regular non-symlink files read through descriptors
with the wind-down request byte bound; report targets are opened relative to
a pinned parent descriptor and written atomically; every payload is one
deterministic JSON document, errors to stderr, exit code 2 for validation
failures and 1 for runtime/write failures.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, TextIO
from uuid import uuid4

from .concepts import BatchResult, BindResult, TransitionResult
from .safe_fs import _FILE_CREATE_FLAGS, _open_directory_nofollow
from .scope import ScopeError
from .winddown import MAX_REQUEST_BYTES, _Issue

DEFAULT_WINDDOWN_ACTOR = "session-context/winddown"
DEFAULT_OPERATOR_ACTOR = "session-context/operator"
DEFAULT_IMPORT_ACTOR = "session-context/import-okf"


class _InputFailure(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class _ReportTarget:
    parent_descriptor: int
    name: str


def _emit_json(payload: dict[str, Any], *, error: bool = False) -> None:
    print(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        file=sys.stderr if error else sys.stdout,
    )


def _issue_payload(issue: _Issue) -> dict[str, str]:
    return {"path": issue.path, "code": issue.code, "message": issue.message}


def _input_error_payload(command: str, failure: _InputFailure) -> dict[str, Any]:
    return {
        "command": command,
        "errors": [{"path": "/", "code": failure.code, "message": failure.message}],
        "writes": 0,
    }


def _runtime_failure(command: str) -> int:
    _emit_json(
        {"command": command, "error": "operation failed", "writes": 0},
        error=True,
    )
    return 1


def _scope_failure(command: str, *, project: str | None) -> int:
    code = "project_unavailable" if project is not None else "scope_unavailable"
    path = "/project" if project is not None else "/scope"
    _emit_json(
        {
            "command": command,
            "errors": [
                {
                    "path": path,
                    "code": code,
                    "message": "Configured scope is unavailable",
                }
            ],
            "writes": 0,
        },
        error=True,
    )
    return 2


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAX_REQUEST_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(8192, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) > MAX_REQUEST_BYTES:
        raise _InputFailure(
            "input_too_large", "Input exceeds the bounded request limit"
        )
    return payload


def _read_input_file(value: str) -> bytes:
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise _InputFailure("unsafe_input", "Input must be a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise _InputFailure("unsafe_input", "Input could not be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise _InputFailure("unsafe_input", "Input must be a regular file")
        if metadata.st_size > MAX_REQUEST_BYTES:
            raise _InputFailure(
                "input_too_large", "Input exceeds the bounded request limit"
            )
        return _read_descriptor(descriptor)
    finally:
        os.close(descriptor)


def _read_stdin() -> bytes:
    source: BinaryIO | TextIO = getattr(sys.stdin, "buffer", sys.stdin)
    value = source.read(MAX_REQUEST_BYTES + 1)
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    if len(payload) > MAX_REQUEST_BYTES:
        raise _InputFailure(
            "input_too_large", "Input exceeds the bounded request limit"
        )
    return payload


def _safe_import_directory(value: str) -> Path:
    root = Path(value).expanduser()
    if root.is_symlink():
        raise _InputFailure(
            "unsafe_directory", "Directory must be a non-symlink directory"
        )
    try:
        descriptor = _open_directory_nofollow(root)
    except OSError as exc:
        raise _InputFailure(
            "unsafe_directory", "Directory must be a non-symlink directory"
        ) from exc
    os.close(descriptor)
    return root


def _safe_report_target(value: str | None) -> _ReportTarget | None:
    if value in (None, "-"):
        return None
    target = Path(value).expanduser()
    if target.name in ("", ".", ".."):
        raise _InputFailure("unsafe_report_target", "Report target is unsafe")
    try:
        parent_descriptor = _open_directory_nofollow(target.parent)
    except OSError as exc:
        raise _InputFailure("unsafe_report_target", "Report target is unsafe") from exc
    try:
        try:
            metadata = os.stat(
                target.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(metadata.st_mode):
                raise _InputFailure("unsafe_report_target", "Report target is unsafe")
        return _ReportTarget(parent_descriptor=parent_descriptor, name=target.name)
    except Exception:
        os.close(parent_descriptor)
        raise


def _write_report_atomic(target: _ReportTarget, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    descriptor: int | None = None
    temporary_name = ""
    for _ in range(16):
        temporary_name = f".session-context-{uuid4().hex}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                _FILE_CREATE_FLAGS,
                0o600,
                dir_fd=target.parent_descriptor,
            )
            break
        except FileExistsError:
            continue
    if descriptor is None:
        raise OSError("Unable to allocate a private report temporary file")

    descriptor_open = True
    temporary_exists = True
    try:
        os.fchmod(descriptor, 0o600)
        stream = os.fdopen(descriptor, "wb")
        descriptor_open = False
        with stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            metadata = os.stat(
                target.name,
                dir_fd=target.parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(metadata.st_mode):
                raise _InputFailure(
                    "unsafe_report_target", "Report target became unsafe"
                )
        os.replace(
            temporary_name,
            target.name,
            src_dir_fd=target.parent_descriptor,
            dst_dir_fd=target.parent_descriptor,
        )
        temporary_exists = False
        os.fsync(target.parent_descriptor)
    finally:
        if descriptor_open:
            os.close(descriptor)
        if temporary_exists:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=target.parent_descriptor)


def _batch_payload(result: BatchResult) -> dict[str, Any]:
    return {
        "command": "winddown",
        "writes": result.writes,
        "concept_ids": list(result.concept_ids),
        "errors": [_issue_payload(issue) for issue in result.errors],
    }


def _transition_payload(command: str, result: TransitionResult) -> dict[str, Any]:
    return {
        "command": command,
        "writes": result.writes,
        "concept_id": result.concept_id,
        "standing": result.standing,
        "event_id": result.event_id,
        "errors": [_issue_payload(issue) for issue in result.errors],
    }


def _bind_payload(result: BindResult) -> dict[str, Any]:
    return {
        "command": "concept bind",
        "writes": result.writes,
        "legacy_concept_id": result.legacy_concept_id,
        "concept_id": result.concept_id,
        "assertion_id": result.assertion_id,
        "errors": [_issue_payload(issue) for issue in result.errors],
    }


def _service(db: Path | None):
    from .concepts import ConceptService

    return ConceptService(db, prepare_schema=False)


def run_winddown(
    *,
    session: str,
    input_file: str | None,
    use_stdin: bool,
    actor: str,
    project: str | None,
    db: Path | None,
) -> int:
    try:
        document = _read_stdin() if use_stdin else _read_input_file(input_file or "")
    except _InputFailure as failure:
        _emit_json(_input_error_payload("winddown", failure), error=True)
        return 2
    try:
        result = _service(db).winddown(session, document, actor=actor, project=project)
    except ScopeError:
        return _scope_failure("winddown", project=project)
    except Exception:
        return _runtime_failure("winddown")
    _emit_json(_batch_payload(result), error=bool(result.errors))
    return 2 if result.errors else 0


def run_transition(
    *,
    verb: str,
    concept_id: str,
    actor: str,
    reason: str,
    project: str | None,
    db: Path | None,
) -> int:
    command = f"concept {verb}"
    try:
        result = _service(db).transition(
            concept_id,
            "accepted" if verb == "accept" else "retired",
            actor=actor,
            reason=reason,
            project=project,
        )
    except ScopeError:
        return _scope_failure(command, project=project)
    except Exception:
        return _runtime_failure(command)
    _emit_json(_transition_payload(command, result), error=bool(result.errors))
    return 2 if result.errors else 0


def run_bind(
    *,
    concept_id: str,
    input_file: str,
    actor: str,
    reason: str,
    project: str | None,
    db: Path | None,
) -> int:
    try:
        document = _read_input_file(input_file)
    except _InputFailure as failure:
        _emit_json(_input_error_payload("concept bind", failure), error=True)
        return 2
    try:
        result = _service(db).bind_legacy(
            concept_id, document, actor=actor, reason=reason, project=project
        )
    except ScopeError:
        return _scope_failure("concept bind", project=project)
    except Exception:
        return _runtime_failure("concept bind")
    _emit_json(_bind_payload(result), error=bool(result.errors))
    return 2 if result.errors else 0


def run_import_okf(
    *,
    directory: str,
    report: str | None,
    dry_run: bool,
    actor: str,
    project: str | None,
    db: Path | None,
) -> int:
    report_target: _ReportTarget | None = None
    try:
        root = _safe_import_directory(directory)
        report_target = _safe_report_target(report)
    except _InputFailure as failure:
        _emit_json(_input_error_payload("concept import-okf", failure), error=True)
        return 2
    try:
        okf_report = _service(db).import_okf(
            root, actor=actor, project=project, dry_run=dry_run
        )
        payload = okf_report.to_dict()
        if report_target is not None:
            try:
                _write_report_atomic(report_target, payload)
            except Exception:
                operation_error = any(
                    error.relative_path == "" for error in okf_report.errors
                )
                partial = {
                    **payload,
                    "committed": bool(
                        not dry_run
                        and not okf_report.write_failures
                        and not operation_error
                    ),
                    "error": "operation failed",
                    "report_error": "report_delivery_failed",
                }
                _emit_json(partial, error=True)
                return 1
    except _InputFailure as failure:
        _emit_json(_input_error_payload("concept import-okf", failure), error=True)
        return 2
    except Exception:
        return _runtime_failure("concept import-okf")
    finally:
        if report_target is not None:
            with suppress(OSError):
                os.close(report_target.parent_descriptor)
    if okf_report.write_failures:
        _emit_json(payload, error=True)
        return 1
    if any(error.relative_path == "" for error in okf_report.errors):
        _emit_json(payload, error=True)
        return 2
    _emit_json(payload)
    return 0


def run_project(
    *,
    out: str,
    project: str | None,
    as_json: bool,
    db: Path | None,
) -> int:
    try:
        report = _service(db).project(Path(out).expanduser(), project=project)
    except ScopeError:
        return _scope_failure("concept project", project=project)
    except Exception:
        return _runtime_failure("concept project")
    payload = {"command": "concept project", "out": out, **report.to_dict()}
    failed = report.status != "ok"
    if as_json:
        _emit_json(payload, error=failed)
    else:
        print(
            " ".join(
                f"{key}={json.dumps(value, ensure_ascii=False, sort_keys=True)}"
                for key, value in payload.items()
            ),
            file=sys.stderr if failed else sys.stdout,
        )
    return 1 if failed else 0
