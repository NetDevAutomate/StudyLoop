"""Locked, journalled repository for canonical planning mutations.

The repository is intentionally the only module that combines validation,
capacity, idempotency, crash recovery, and durable Markdown replacement. Slow
model work belongs outside this root-wide transaction boundary.
"""

from __future__ import annotations

import base64
import copy
import fcntl
import json
import os
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, TypeVar

from .digests import compute_document_digest, compute_structure_digest
from .journal import (
    JournalEvent,
    append_event,
    fsync_directory,
    read_events,
    repair_torn_tail,
    validate_event_sequence,
)
from .markdown import parse_plan, render_plan
from .models import StudyPlan
from .store import validate_plan_id

CURRENT_PLAN_STATUSES = frozenset({"draft", "active", "paused"})
MAX_CURRENT_PLANS = 3
SUPPORTED_PLAN_SCHEMA_VERSIONS = frozenset({1, 2})

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---(?:\s*\n?)", re.DOTALL)
_PRIVATE_COMPONENT_RE = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}\Z")

MutationOperation = Literal["create", "update", "upsert", "record", "journal"]
CrashInjector = Callable[[str], None]
IndexRefresher = Callable[[StudyPlan], None]
TransactionGuard = Callable[["PlanSnapshot", tuple[JournalEvent, ...], "MutationIntent"], None]
ProjectionT = TypeVar("ProjectionT")
_DEFAULT_INDEX_REFRESHER = object()


class PlanningRepositoryError(RuntimeError):
    """Base class for repository failures that must not be coerced into writes."""


class PlanScanError(PlanningRepositoryError):
    """Raised when the root cannot be classified safely for mutation."""


class PlanCapacityError(PlanningRepositoryError):
    """Raised when a mutation would exceed three current plans."""


class PlanConflictError(PlanningRepositoryError):
    """Raised when the target changed or the requested operation is invalid."""


class IdempotencyConflictError(PlanConflictError):
    """Raised when a caller reuses an idempotency key with changed input."""


class RecoveryError(PlanningRepositoryError):
    """Raised when a pending intent cannot be classified without guessing."""


class PathContainmentError(PlanScanError):
    """Raised when configured or discovered state escapes the planning root."""


@dataclass(frozen=True)
class PlanningPaths:
    """Every durable path governed by one root-wide lock."""

    root: Path
    plans: Path
    journal: Path
    private_runs: Path
    lock_file: Path

    @classmethod
    def in_root(cls, root: Path) -> PlanningPaths:
        """Build the conventional repository layout below ``root``."""
        return cls(
            root=root,
            plans=root / "plans",
            journal=root / "planning-journal.jsonl",
            private_runs=root / "private-runs",
            lock_file=root / ".planning.lock",
        )


@dataclass(frozen=True)
class PlanningRef:
    """Opaque canonical plan identity accepted by repository callers."""

    plan_id: str


@dataclass(frozen=True)
class PlanningView:
    """A validated canonical plan plus its exact persisted bytes."""

    ref: PlanningRef
    plan: StudyPlan
    canonical_text: str
    document_digest: str
    structure_digest: str


@dataclass(frozen=True)
class PlanSnapshot:
    """A fail-closed, root-wide view captured under the mutation lock."""

    plans: tuple[PlanningView, ...]
    current_plan_ids: tuple[str, ...]
    active_goal_ids: tuple[str, ...]

    @property
    def current_count(self) -> int:
        return len(self.current_plan_ids)


@dataclass(frozen=True)
class PrivateRunArtifact:
    """One private run artifact written mode 0600 below a run directory."""

    run_id: str
    name: str
    content: str | bytes


@dataclass(frozen=True)
class MutationIntent:
    """Typed input to one root-wide repository transaction."""

    intent_id: str
    caller: str
    idempotency_key: str
    operation: MutationOperation = "create"
    plan: StudyPlan | None = None
    ref: PlanningRef | None = None
    expected_document_digest: str = ""
    expected_structure_digest: str = ""
    expected_document_revision: int | None = None
    expected_structure_revision: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def plan_id(self) -> str:
        if self.plan is not None:
            return self.plan.plan_id
        return self.ref.plan_id if self.ref is not None else ""


@dataclass(frozen=True)
class CommitResult:
    """Stable outcome persisted in the journal for idempotent replay."""

    status: Literal["committed", "replayed"]
    intent_id: str
    plan_id: str
    document_digest: str | None
    structure_digest: str | None
    document_revision: int | None
    structure_revision: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object], *, replayed: bool) -> CommitResult:
        try:
            return cls(
                status="replayed" if replayed else "committed",
                intent_id=str(payload["intent_id"]),
                plan_id=str(payload.get("plan_id", "")),
                document_digest=_optional_str(payload.get("document_digest")),
                structure_digest=_optional_str(payload.get("structure_digest")),
                document_revision=_optional_int(payload.get("document_revision")),
                structure_revision=_optional_int(payload.get("structure_revision")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RecoveryError(f"journal contains an invalid commit result: {error}") from error


@dataclass(frozen=True)
class RecoveredIntent:
    """One pending transaction classified during recovery."""

    intent_id: str
    plan_id: str
    classification: Literal["before", "after"]


@dataclass(frozen=True)
class RecoveryReport:
    """Deterministic classifications made during one recovery pass."""

    recovered: tuple[RecoveredIntent, ...] = ()

    @property
    def recovered_count(self) -> int:
        return len(self.recovered)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _payload_digest(intent: MutationIntent) -> str:
    plan_payload = asdict(intent.plan) if intent.plan is not None else None
    if isinstance(plan_payload, dict):
        plan_payload["document_digest"] = ""
        plan_payload["structure_digest"] = ""
    payload = {
        "payload_version": 1,
        "operation": intent.operation,
        "plan": plan_payload,
        "plan_id": intent.plan_id,
        "expected_document_digest": intent.expected_document_digest,
        "expected_structure_digest": intent.expected_structure_digest,
        "expected_document_revision": intent.expected_document_revision,
        "expected_structure_revision": intent.expected_structure_revision,
        "metadata": intent.metadata,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:v1:{sha256(encoded).hexdigest()}"


class PlanningRepository:
    """Own fail-closed scanning and recoverable canonical plan writes."""

    def __init__(
        self,
        paths: PlanningPaths,
        *,
        crash_injector: CrashInjector | None = None,
        index_refresher: IndexRefresher | None | object = _DEFAULT_INDEX_REFRESHER,
    ) -> None:
        self.paths = paths
        self._crash_injector = crash_injector
        self._index_refresher = (
            self._refresh_index if index_refresher is _DEFAULT_INDEX_REFRESHER else index_refresher
        )
        self._validate_configured_paths()
        self._ensure_layout()

    def scan_for_mutation(self) -> PlanSnapshot:
        """Return a complete validated snapshot while holding the root lock."""
        with self._root_lock():
            self._recover_locked()
            return self._scan_locked()

    def inspect(self, ref: PlanningRef) -> PlanningView:
        """Read one plan and verify any repository-issued digests."""
        plan_id = validate_plan_id(ref.plan_id)
        path = self._plan_path(plan_id)
        if not path.is_file():
            raise PlanConflictError(f"no study plan with id {plan_id!r}")
        return self._read_view(path)

    def project(
        self,
        projector: Callable[[PlanSnapshot, tuple[JournalEvent, ...]], ProjectionT],
    ) -> ProjectionT:
        """Fold a validated snapshot and journal while holding the root lock.

        This is intentionally generic: application policy lives in a caller's
        pure projection rather than becoming a second policy layer in the
        repository.
        """
        with self._root_lock():
            self._recover_locked()
            snapshot = self._scan_locked()
            events = tuple(self._read_journal_locked())
            return projector(snapshot, events)

    def commit(
        self,
        intent: MutationIntent,
        *,
        guard: TransactionGuard | None = None,
    ) -> CommitResult:
        """Apply one idempotent mutation under the root-wide filesystem lock."""
        self._validate_intent(intent)
        payload_digest = _payload_digest(intent)
        committed_plan: StudyPlan | None = None
        with self._root_lock():
            self._recover_locked()
            snapshot = self._scan_locked()
            events = self._read_journal_locked()
            replay = self._idempotent_replay(intent, payload_digest, events)
            if replay is not None:
                return replay

            if guard is not None:
                guard(snapshot, tuple(events), intent)

            before = self._find_view(snapshot, intent.plan_id)
            after_text: str | None
            after_plan: StudyPlan | None
            if intent.operation in {"record", "journal"}:
                after_plan = copy.deepcopy(before.plan) if before is not None else None
                if after_plan is not None and before is not None:
                    after_plan.document_digest = before.document_digest
                    after_plan.structure_digest = before.structure_digest
                after_text = before.canonical_text if before is not None else None
            else:
                after_plan, after_text = self._prepare_plan(intent, before, snapshot)
                committed_plan = after_plan

            before_text = before.canonical_text if before is not None else None
            temporary_name = (
                f".{validate_plan_id(intent.plan_id)}.{uuid.uuid4().hex}.tmp"
                if after_text is not None and intent.operation not in {"record", "journal"}
                else ""
            )
            result = self._result(intent, after_plan)
            recovery_payload: dict[str, object] = {
                "recovery_version": 1,
                "before_bytes_b64": _encode_optional(before_text),
                "after_bytes_b64": _encode_optional(after_text),
                "temporary_name": temporary_name,
            }
            event_fields = self._event_fields(
                intent=intent,
                payload_digest=payload_digest,
                before=before,
                after=after_plan,
            )
            append_event(
                self.paths.journal,
                JournalEvent(
                    event="intent",
                    occurred_at=_utc_now(),
                    payload=dict(intent.metadata),
                    recovery=recovery_payload,
                    result=result.to_dict(),
                    **event_fields,
                ),
            )
            self._inject("after_journal_intent")

            if after_text is not None and intent.operation not in {"record", "journal"}:
                target = self._plan_path(intent.plan_id)
                temporary = target.parent / temporary_name
                self._write_temporary(temporary, after_text.encode("utf-8"))
                self._inject("after_temp_fsync")
                os.replace(temporary, target)
                self._inject("after_replace")
                fsync_directory(target.parent)
                self._inject("after_directory_fsync")

            append_event(
                self.paths.journal,
                JournalEvent(
                    event="committed",
                    occurred_at=_utc_now(),
                    payload=dict(intent.metadata),
                    recovery={"classification": "after"},
                    result=result.to_dict(),
                    **event_fields,
                ),
            )
            self._inject("after_commit_event")

        if committed_plan is not None and self._index_refresher is not None:
            self._index_refresher(committed_plan)
        return result

    def recover(self) -> RecoveryReport:
        """Classify pending intents from canonical bytes; never infer a third state."""
        with self._root_lock():
            return self._recover_locked()

    def write_private_artifact(self, artifact: PrivateRunArtifact) -> Path:
        """Durably write a private brain dump/brief with mode 0600."""
        run_id = self._private_component(artifact.run_id, "run id")
        name = self._private_component(artifact.name, "artifact name")
        content = (
            artifact.content.encode("utf-8")
            if isinstance(artifact.content, str)
            else artifact.content
        )
        with self._root_lock():
            run_dir = self.paths.private_runs / run_id
            run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            if run_dir.resolve().parent != self.paths.private_runs.resolve():
                raise PathContainmentError("private run directory escapes planning root")
            os.chmod(run_dir, 0o700)
            path = run_dir / name
            if path.is_symlink():
                raise PathContainmentError("private run artifact cannot be a symlink")
            if path.exists():
                if not path.is_file() or path.resolve().parent != run_dir.resolve():
                    raise PathContainmentError("private run artifact escapes planning root")
                try:
                    existing = path.read_bytes()
                except OSError as error:
                    raise PlanConflictError(
                        f"cannot verify immutable private run artifact: {error}"
                    ) from error
                if existing == content:
                    return path
                raise PlanConflictError(
                    f"immutable private run artifact {name!r} already has different content"
                )
            temporary = run_dir / f".{name}.{uuid.uuid4().hex}.tmp"
            self._write_temporary(temporary, content)
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            fsync_directory(run_dir)
            return path

    def _validate_configured_paths(self) -> None:
        root = self.paths.root.expanduser().resolve(strict=False)
        for name, path in (
            ("plans", self.paths.plans),
            ("journal", self.paths.journal),
            ("private_runs", self.paths.private_runs),
            ("lock_file", self.paths.lock_file),
        ):
            resolved = path.expanduser().resolve(strict=False)
            if not resolved.is_relative_to(root):
                raise PathContainmentError(f"configured {name} path escapes planning root")

    def _ensure_layout(self) -> None:
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.plans.mkdir(parents=True, exist_ok=True)
        self.paths.private_runs.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.paths.private_runs, 0o700)
        descriptor = os.open(self.paths.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)

    @contextmanager
    def _root_lock(self) -> Iterator[None]:
        self._validate_configured_paths()
        descriptor = os.open(self.paths.lock_file, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._validate_configured_paths()
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _scan_locked(self) -> PlanSnapshot:
        views: list[PlanningView] = []
        try:
            candidates = sorted(
                (entry for entry in self.paths.plans.iterdir() if entry.name.endswith(".md")),
                key=lambda entry: entry.name,
            )
        except OSError as error:
            raise PlanScanError(f"cannot scan planning root: {error}") from error
        for candidate in candidates:
            if not candidate.is_file():
                raise PlanScanError(f"candidate plan is not a regular file: {candidate.name}")
            views.append(self._read_view(candidate))
        current = tuple(
            view.plan.plan_id for view in views if view.plan.status in CURRENT_PLAN_STATUSES
        )
        active_goals = tuple(
            goal.goal_id
            for view in views
            if view.plan.status == "active"
            for goal in view.plan.goals
            if goal.status == "active"
        )
        return PlanSnapshot(tuple(views), current, active_goals)

    def _read_view(self, path: Path) -> PlanningView:
        resolved_plans = self.paths.plans.resolve()
        try:
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise PlanScanError(f"cannot resolve candidate plan {path.name}: {error}") from error
        if resolved.parent != resolved_plans:
            raise PathContainmentError(f"candidate plan escapes planning root: {path.name}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise PlanScanError(f"cannot read candidate plan {path.name}: {error}") from error
        self._validate_frontmatter(text, path.name)
        try:
            plan = parse_plan(text, plan_id=path.stem)
        except Exception as error:
            raise PlanScanError(f"cannot parse candidate plan {path.name}: {error}") from error
        if plan.schema_version not in SUPPORTED_PLAN_SCHEMA_VERSIONS:
            raise PlanScanError(f"unsupported schema version {plan.schema_version} in {path.name}")
        if plan.plan_id != path.stem:
            raise PlanScanError(
                f"plan id {plan.plan_id!r} does not match candidate filename {path.name!r}"
            )
        computed_document = compute_document_digest(text)
        computed_structure = compute_structure_digest(plan)
        if bool(plan.document_digest) != bool(plan.structure_digest):
            raise PlanScanError(f"incomplete digest metadata in {path.name}")
        if plan.schema_version >= 2 and not plan.document_digest:
            raise PlanScanError(f"schema v2 plan requires versioned digests in {path.name}")
        if plan.document_digest and plan.document_digest != computed_document:
            raise PlanScanError(f"document digest mismatch in {path.name}")
        if plan.structure_digest and plan.structure_digest != computed_structure:
            raise PlanScanError(f"structure digest mismatch in {path.name}")
        return PlanningView(
            ref=PlanningRef(plan.plan_id),
            plan=plan,
            canonical_text=text,
            document_digest=computed_document,
            structure_digest=computed_structure,
        )

    @staticmethod
    def _validate_frontmatter(text: str, name: str) -> None:
        match = _FRONTMATTER_RE.match(text)
        if match is None:
            if text.startswith("---"):
                raise PlanScanError(f"unterminated frontmatter in {name}")
            return  # tolerant legacy plan; parse_plan applies conservative defaults
        try:
            import yaml

            metadata = yaml.safe_load(match.group("body"))
        except Exception as error:
            raise PlanScanError(f"malformed YAML frontmatter in {name}: {error}") from error
        if not isinstance(metadata, dict):
            raise PlanScanError(f"frontmatter must be a mapping in {name}")
        schema_version = metadata.get("schema_version", 1)
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise PlanScanError(f"schema_version must be an integer in {name}")
        for field_name in ("document_revision", "structure_revision"):
            value = metadata.get(field_name, 1)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PlanScanError(f"{field_name} must be a positive integer in {name}")
        status = metadata.get("status", "draft")
        if status not in {"draft", "active", "paused", "complete", "abandoned"}:
            raise PlanScanError(f"unsupported plan status {status!r} in {name}")

    def _plan_path(self, plan_id: str) -> Path:
        candidate = self.paths.plans / f"{validate_plan_id(plan_id)}.md"
        resolved_parent = candidate.parent.resolve()
        resolved_candidate = candidate.resolve(strict=False)
        if (
            resolved_parent != self.paths.plans.resolve()
            or resolved_candidate.parent != resolved_parent
        ):
            raise PathContainmentError(f"plan path escapes planning root: {plan_id!r}")
        return candidate

    @staticmethod
    def _find_view(snapshot: PlanSnapshot, plan_id: str) -> PlanningView | None:
        return next((view for view in snapshot.plans if view.plan.plan_id == plan_id), None)

    @staticmethod
    def _validate_intent(intent: MutationIntent) -> None:
        if not intent.intent_id.strip():
            raise PlanConflictError("intent_id is required")
        if not intent.caller.strip() or not intent.idempotency_key.strip():
            raise PlanConflictError("caller and idempotency_key are required")
        if intent.operation not in {"create", "update", "upsert", "record", "journal"}:
            raise PlanConflictError(f"unsupported mutation operation: {intent.operation!r}")
        if intent.operation not in {"record", "journal"} and intent.plan is None:
            raise PlanConflictError("plan content is required for a plan mutation")
        if not intent.plan_id:
            raise PlanConflictError("plan reference is required")
        if (
            intent.plan is not None
            and intent.ref is not None
            and intent.plan.plan_id != intent.ref.plan_id
        ):
            raise PlanConflictError("plan and reference identities do not match")
        validate_plan_id(intent.plan_id)

    def _prepare_plan(
        self,
        intent: MutationIntent,
        before: PlanningView | None,
        snapshot: PlanSnapshot,
    ) -> tuple[StudyPlan, str]:
        if intent.operation == "create" and before is not None:
            raise PlanConflictError(f"study plan {intent.plan_id!r} already exists")
        if intent.operation == "update" and before is None:
            raise PlanConflictError(f"study plan {intent.plan_id!r} does not exist")
        self._check_expected_state(intent, before)
        assert intent.plan is not None
        plan = copy.deepcopy(intent.plan)
        plan.plan_id = validate_plan_id(plan.plan_id)
        plan.schema_version = 2

        new_structure = compute_structure_digest(plan)
        if before is None:
            plan.document_revision = 1
            plan.structure_revision = 1
        else:
            plan.document_revision = before.plan.document_revision + 1
            plan.structure_revision = before.plan.structure_revision + (
                new_structure != before.structure_digest
            )
        plan.structure_digest = compute_structure_digest(plan)
        plan.document_digest = ""
        plan.document_digest = compute_document_digest(render_plan(plan))
        canonical_text = render_plan(plan)
        self._validate_frontmatter(canonical_text, f"{plan.plan_id}.md")

        old_is_current = before is not None and before.plan.status in CURRENT_PLAN_STATUSES
        new_is_current = plan.status in CURRENT_PLAN_STATUSES
        resulting_count = snapshot.current_count - int(old_is_current) + int(new_is_current)
        if resulting_count > MAX_CURRENT_PLANS:
            raise PlanCapacityError(
                f"mutation would create {resulting_count} current plans; "
                f"maximum is {MAX_CURRENT_PLANS}"
            )
        return plan, canonical_text

    @staticmethod
    def _check_expected_state(intent: MutationIntent, before: PlanningView | None) -> None:
        if before is None:
            if any(
                (
                    intent.expected_document_digest,
                    intent.expected_structure_digest,
                    intent.expected_document_revision is not None,
                    intent.expected_structure_revision is not None,
                )
            ):
                raise PlanConflictError("expected existing plan state, but target is absent")
            return
        supplied = (
            intent.expected_document_digest,
            intent.expected_structure_digest,
            intent.expected_document_revision,
            intent.expected_structure_revision,
        )
        if any(value in {"", None} for value in supplied):
            raise PlanConflictError(
                "complete expected state is required for an existing plan update"
            )
        checks = (
            (intent.expected_document_digest, before.document_digest, "document digest"),
            (intent.expected_structure_digest, before.structure_digest, "structure digest"),
            (intent.expected_document_revision, before.plan.document_revision, "document revision"),
            (
                intent.expected_structure_revision,
                before.plan.structure_revision,
                "structure revision",
            ),
        )
        for expected, actual, label in checks:
            if expected not in {"", None} and expected != actual:
                raise PlanConflictError(f"stale {label}: expected {expected!r}, found {actual!r}")

    @staticmethod
    def _result(intent: MutationIntent, plan: StudyPlan | None) -> CommitResult:
        return CommitResult(
            status="committed",
            intent_id=intent.intent_id,
            plan_id=intent.plan_id,
            document_digest=plan.document_digest if plan is not None else None,
            structure_digest=plan.structure_digest if plan is not None else None,
            document_revision=plan.document_revision if plan is not None else None,
            structure_revision=plan.structure_revision if plan is not None else None,
        )

    @staticmethod
    def _event_fields(
        *,
        intent: MutationIntent,
        payload_digest: str,
        before: PlanningView | None,
        after: StudyPlan | None,
    ) -> dict[str, object]:
        return {
            "intent_id": intent.intent_id,
            "caller": intent.caller,
            "idempotency_key": intent.idempotency_key,
            "payload_digest": payload_digest,
            "operation": intent.operation,
            "plan_id": intent.plan_id,
            "before_document_digest": before.document_digest if before is not None else None,
            "after_document_digest": after.document_digest if after is not None else None,
            "before_structure_digest": before.structure_digest if before is not None else None,
            "after_structure_digest": after.structure_digest if after is not None else None,
        }

    @staticmethod
    def _idempotent_replay(
        intent: MutationIntent,
        payload_digest: str,
        events: list[JournalEvent],
    ) -> CommitResult | None:
        matching_intents: dict[str, JournalEvent] = {}
        terminal_after: dict[str, JournalEvent] = {}
        for event in events:
            same_tuple = (
                event.caller == intent.caller and event.idempotency_key == intent.idempotency_key
            )
            if same_tuple and event.payload_digest != payload_digest:
                raise IdempotencyConflictError(
                    "idempotency key was already used with a different payload"
                )
            if (
                event.intent_id == intent.intent_id
                and event.event == "intent"
                and (event.payload_digest != payload_digest or not same_tuple)
            ):
                raise IdempotencyConflictError(
                    "intent_id was already used for a different transaction"
                )
            if same_tuple and event.event == "intent":
                matching_intents[event.intent_id] = event
            if same_tuple and event.event == "committed":
                terminal_after[event.intent_id] = event
            if (
                same_tuple
                and event.event == "recovered"
                and event.recovery.get("classification") == "after"
            ):
                terminal_after[event.intent_id] = event
        for intent_id in matching_intents:
            terminal = terminal_after.get(intent_id)
            if terminal is not None:
                return CommitResult.from_dict(terminal.result, replayed=True)
        return None

    def _recover_locked(self) -> RecoveryReport:
        events = self._read_journal_locked(repair_tail=True)
        pending: dict[str, JournalEvent] = {}
        for event in events:
            if event.event == "intent":
                pending[event.intent_id] = event
            else:
                pending.pop(event.intent_id, None)
        recovered: list[RecoveredIntent] = []
        for event in pending.values():
            before_bytes = _decode_optional(event.recovery.get("before_bytes_b64"))
            after_bytes = _decode_optional(event.recovery.get("after_bytes_b64"))
            current_bytes = self._current_bytes(event.plan_id)
            if _state_matches(current_bytes, before_bytes, event.before_document_digest):
                classification: Literal["before", "after"] = "before"
            elif _state_matches(current_bytes, after_bytes, event.after_document_digest):
                classification = "after"
            else:
                raise RecoveryError(
                    f"pending intent {event.intent_id!r} is neither its before nor after state"
                )
            self._cleanup_recovery_temporary(event)
            if (
                classification == "after"
                and event.operation in {"create", "update", "upsert"}
                and after_bytes is not None
            ):
                fsync_directory(self.paths.plans)
            append_event(
                self.paths.journal,
                JournalEvent(
                    event="recovered",
                    intent_id=event.intent_id,
                    caller=event.caller,
                    idempotency_key=event.idempotency_key,
                    payload_digest=event.payload_digest,
                    operation=event.operation,
                    plan_id=event.plan_id,
                    before_document_digest=event.before_document_digest,
                    after_document_digest=event.after_document_digest,
                    before_structure_digest=event.before_structure_digest,
                    after_structure_digest=event.after_structure_digest,
                    occurred_at=_utc_now(),
                    payload=event.payload,
                    recovery={"classification": classification},
                    result=event.result if classification == "after" else {},
                ),
            )
            recovered.append(RecoveredIntent(event.intent_id, event.plan_id, classification))
        return RecoveryReport(tuple(recovered))

    def _read_journal_locked(self, *, repair_tail: bool = False) -> list[JournalEvent]:
        if repair_tail:
            repair_torn_tail(self.paths.journal)
        events = read_events(self.paths.journal)
        validate_event_sequence(events)
        return events

    def _current_bytes(self, plan_id: str) -> bytes | None:
        if not plan_id:
            return None
        path = self._plan_path(plan_id)
        try:
            return path.read_bytes() if path.is_file() else None
        except OSError as error:
            raise RecoveryError(f"cannot read recovery target {plan_id!r}: {error}") from error

    def _cleanup_recovery_temporary(self, event: JournalEvent) -> None:
        temporary_name = event.recovery.get("temporary_name")
        if not isinstance(temporary_name, str) or not temporary_name:
            return
        expected_prefix = f".{validate_plan_id(event.plan_id)}."
        if (
            Path(temporary_name).name != temporary_name
            or not temporary_name.startswith(expected_prefix)
            or not temporary_name.endswith(".tmp")
            or len(temporary_name) != len(expected_prefix) + 32 + len(".tmp")
            or any(
                character not in "0123456789abcdef"
                for character in temporary_name[len(expected_prefix) : -len(".tmp")]
            )
        ):
            raise RecoveryError(f"unsafe recovery temporary path for {event.intent_id!r}")
        temporary = self.paths.plans / temporary_name
        if temporary.exists():
            temporary.unlink()
            fsync_directory(self.paths.plans)

    def _write_temporary(self, path: Path, payload: bytes) -> None:
        resolved_parent = path.parent.resolve()
        plans_root = self.paths.plans.resolve()
        private_root = self.paths.private_runs.resolve()
        if resolved_parent != plans_root and not resolved_parent.is_relative_to(private_root):
            raise PathContainmentError("temporary path escapes planning root")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:  # pragma: no cover - defensive OS failure
                    raise OSError("short write while writing planning temporary")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _private_component(value: str, label: str) -> str:
        if not _PRIVATE_COMPONENT_RE.fullmatch(value) or ".." in value:
            raise PathContainmentError(f"invalid private {label}: {value!r}")
        return value

    def _inject(self, point: str) -> None:
        if self._crash_injector is not None:
            self._crash_injector(point)

    @staticmethod
    def _refresh_index(plan: StudyPlan) -> None:
        try:
            from .index import index_plan

            index_plan(plan)
        except Exception:
            # Markdown + journal are authoritative; the index is rebuildable.
            return


def _encode_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _decode_optional(value: object) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecoveryError("recovery bytes must be base64 text or null")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as error:
        raise RecoveryError("invalid base64 recovery payload") from error


def _state_matches(
    current: bytes | None,
    expected: bytes | None,
    expected_digest: str | None,
) -> bool:
    if current is None or expected is None:
        return current is expected and expected_digest is None
    return current == expected and compute_document_digest(current) == expected_digest
