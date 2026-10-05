"""Minimal per-run evidence bundle writer (council D-14 / astra QC1).

B4 owns the FULL bundle-writer schema -- ``manifest.json`` with run id,
repo sha + dirty-tree identity, harness/actor versions, platform, auth
mode, rubric version+hash, full pass/fail/skip counts, file inventory with
sha256s, all captured into a DURABLE evidence root resolved from the real
environment BEFORE scratch substitution -- that writer now exists in-tree
(``tests/acceptance/uat/bundle.py``) but is not yet wired into this lane's
call sites, and this lane (B2) needs somewhere to put its per-run evidence
NOW so a harness-matrix run is not silently unrecorded.

Until the callers migrate, this module writes the NARROWEST bundle this
lane's own validators need: a plain directory per run holding the turn
records (pane text is EVIDENCE here, never an assertion target -- D-17)
and a small ``manifest.json`` naming the harness, actor, outcome, turn
count, and -- council D-21(7) -- the harness version, platform, and auth
mode (each optional, recorded as ``null`` when unknown, never simply
absent). The shape is deliberately close to a SUBSET of B4's described
schema (same field names: ``run_id``, ``harness``, ``actor``, ``outcome``)
so that swapping this module out for a call into B4's real writer stays
CLOSE to a rename. It is not a pure rename, though: B4's landed writer
(``tests/acceptance/uat/bundle.py``) names the corresponding fields
``actor_backend``/``actor_model``/nested ``counts`` rather than this
module's flat ``actor``/``outcome``/``turn_count``, so the eventual swap is
a small field-mapping change (see docs/acceptance-testing.md's "Coverage
inventory" tracked-exclusions list for the exact mapping and its owner).

LEFT OUT (tracked, not silently skipped): the DURABLE evidence root (its
own env var, default ``~/.local/share/studyloop/uat/<run-id>/``, resolved
BEFORE scratch substitution) is B4's contract, not this module's -- callers
here pass whatever root they have (typically a pytest ``tmp_path``), and
migrating to the durable root is B4's job once its writer exists.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: A run id becomes a directory name directly below the evidence root --
#: reject anything that could escape it (path separators, `..`) rather than
#: relying on the filesystem to reject a bad path AFTER partial writes.
_SAFE_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class UnsafeRunIdError(ValueError):
    """Raised for a run id that could not safely become a directory name."""


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Where one run's minimal evidence bundle landed.

    The four optional paths are the module-contract v1 persona additions (design.md §6, lane
    U1): ``None`` when the caller did not supply that member, so an older caller's bundle
    reads exactly as it did before.
    """

    run_dir: Path
    manifest_path: Path
    turns_path: Path
    server_log_path: Path | None = None
    cli_transcript_path: Path | None = None
    lockfile_diff_path: Path | None = None
    attempt_envelope_path: Path | None = None


#: File names of the optional members, beside ``manifest.json`` / ``turns.json``. The server
#: log is ``.txt``, not ``.log``: a bundle is committed under ``evidence/`` as proof, and the
#: repository ignores ``*.log`` (U1-review F1 -- the manifest named a member the tree lacked).
SERVER_LOG_NAME = "server-log.txt"
CLI_TRANSCRIPT_NAME = "cli-transcript.txt"
LOCKFILE_DIFF_NAME = "modules.lock.diff"
ATTEMPT_ENVELOPE_NAME = "attempt-envelope.json"


def write_evidence_bundle(
    evidence_root: Path,
    *,
    run_id: str,
    harness: str,
    actor: str,
    outcome: str,
    turns: list[dict],
    platform: str | None = None,
    auth_mode: str | None = None,
    harness_version: str | None = None,
    server_log: str | None = None,
    cli_transcript: str | None = None,
    lockfile_diff: str | None = None,
    attempt_envelope: dict | None = None,
) -> EvidenceBundle:
    """Write ``manifest.json`` + ``turns.json`` for one acceptance run.

    ``platform``/``auth_mode``/``harness_version`` are council D-21(7)'s
    "harness version, platform, auth mode" -- optional (default ``None``,
    recorded as such) because not every caller knows all three yet (a
    presence-only probe has no version to report), but the KEYS are always
    present in the manifest so a reader never has to guess whether "not
    recorded" means "empty string" or "key absent".

    ``server_log`` / ``cli_transcript`` / ``lockfile_diff`` / ``attempt_envelope`` are the
    four members design.md §6 adds for the persona journeys (lane U1): the subprocess
    server's captured output, the transcript of every ``studyloop`` call the persona made,
    the before/after diff of ``modules.lock.json`` and the attempt envelope recorded when a
    drill was started. Each is written as its own file (``server-log.txt``,
    ``cli-transcript.txt``, ``modules.lock.diff``, ``attempt-envelope.json``) and named in
    the manifest under ``artifacts`` -- a key that appears ONLY when at least one member was
    supplied, so a caller that passes none gets the pre-U1 manifest byte for byte.

    Raises :class:`UnsafeRunIdError` for a ``run_id`` that is empty or could
    escape ``evidence_root`` (a leading ``.``/``/`` or an embedded path
    separator). Raises ``FileExistsError`` if ``run_id`` was already used
    under this root -- a bundle is written once, never silently merged into
    a prior run's directory.
    """
    if not run_id or not _SAFE_RUN_ID_PATTERN.match(run_id):
        raise UnsafeRunIdError(
            f"unsafe run_id {run_id!r}: must be non-empty and match "
            f"{_SAFE_RUN_ID_PATTERN.pattern!r}"
        )

    run_dir = evidence_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    manifest: dict[str, object] = {
        "run_id": run_id,
        "harness": harness,
        "actor": actor,
        "outcome": outcome,
        "turn_count": len(turns),
        "platform": platform,
        "auth_mode": auth_mode,
        "harness_version": harness_version,
    }

    members: dict[str, Path | None] = {
        "server_log": None,
        "cli_transcript": None,
        "lockfile_diff": None,
        "attempt_envelope": None,
    }
    if server_log is not None:
        members["server_log"] = run_dir / SERVER_LOG_NAME
        members["server_log"].write_text(server_log, encoding="utf-8")
    if cli_transcript is not None:
        members["cli_transcript"] = run_dir / CLI_TRANSCRIPT_NAME
        members["cli_transcript"].write_text(cli_transcript, encoding="utf-8")
    if lockfile_diff is not None:
        members["lockfile_diff"] = run_dir / LOCKFILE_DIFF_NAME
        members["lockfile_diff"].write_text(lockfile_diff, encoding="utf-8")
    if attempt_envelope is not None:
        members["attempt_envelope"] = run_dir / ATTEMPT_ENVELOPE_NAME
        members["attempt_envelope"].write_text(
            json.dumps(attempt_envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if any(path is not None for path in members.values()):
        manifest["artifacts"] = {
            name: (path.name if path is not None else None) for name, path in members.items()
        }

    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    turns_path = run_dir / "turns.json"
    turns_path.write_text(json.dumps(turns, indent=2) + "\n", encoding="utf-8")

    return EvidenceBundle(
        run_dir=run_dir,
        manifest_path=manifest_path,
        turns_path=turns_path,
        server_log_path=members["server_log"],
        cli_transcript_path=members["cli_transcript"],
        lockfile_diff_path=members["lockfile_diff"],
        attempt_envelope_path=members["attempt_envelope"],
    )
