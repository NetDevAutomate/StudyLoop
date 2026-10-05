"""The persona failure bundle (design.md §6, lane U1).

On any phase failure the bundle under the run's evidence directory must carry, beside what
``acceptance/evidence.py`` wrote before this lane (``manifest.json`` + ``turns.json``):

- the subprocess server's log (``server-log.txt`` -- ``*.log`` is gitignored, U1-review F1),
- the transcript of every ``studyloop`` call the persona made (``cli-transcript.txt``),
- a before/after unified diff of ``modules.lock.json`` (``modules.lock.diff``),
- the attempt envelope JSON when a drill was started (``attempt-envelope.json``),

plus the browser artefacts the e2e world writes on failure (screenshot, HTML, console).

Everything textual is REDACTED before it is written -- the known run secrets (the ``--lan``
password, the practice-check capability token), every absolute home path, LAN addresses and
full sha256 digests -- and then VERIFIED with the UAT tier's detector
(:func:`acceptance.uat.redaction.contains_forbidden_content`, imported, never copied). The
verification result travels with the bundle (``redaction-violations.txt`` exists only when
something slipped through), so a bundle that is about to be committed under
``evidence/U1/forced-failure-bundle/`` carries its own proof.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..evidence import EvidenceBundle, write_evidence_bundle
from ..uat.redaction import contains_forbidden_content

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

SCREENSHOT_NAME = "screenshot.png"
PAGE_HTML_NAME = "page.html"
CONSOLE_NAME = "console.json"
VIOLATIONS_NAME = "redaction-violations.txt"

#: The seven artefacts tasks.md names for a forced failure, by file name.
EXPECTED_MEMBERS: tuple[str, ...] = (
    SCREENSHOT_NAME,
    PAGE_HTML_NAME,
    CONSOLE_NAME,
    "server-log.txt",
    "cli-transcript.txt",
    "modules.lock.diff",
    "attempt-envelope.json",
)

#: sha256 (64 hex) and git (40 hex) digests keep their first 12 characters: still a handle,
#: no longer a high-entropy string for a secrets scanner to trip on.
_HEX_DIGEST = re.compile(r"\b([0-9a-f]{12})(?:[0-9a-f]{52}|[0-9a-f]{28})\b")
_LAN_IPV4 = re.compile(r"\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}\b")


@dataclass(frozen=True, slots=True)
class CliRecord:
    """One ``studyloop`` call the persona made, exactly as the learner would have seen it."""

    argv: tuple[str, ...]
    stdin: str
    returncode: int
    stdout: str
    stderr: str
    duration_s: float

    def render(self) -> str:
        shown = " ".join(("studyloop", *self.argv))
        head = f"$ {shown}"
        if self.stdin:
            head += f"\n  (stdin: {self.stdin!r})"
        body = self.stdout.rstrip("\n")
        err = self.stderr.rstrip("\n")
        parts = [head]
        if body:
            parts.append(body)
        if err:
            parts.append("--- stderr ---\n" + err)
        parts.append(f"[exit {self.returncode} in {self.duration_s:.2f}s]")
        return "\n".join(parts)


def render_cli_transcript(records: Iterable[CliRecord]) -> str:
    rendered = [record.render() for record in records]
    return "\n\n".join(rendered) + ("\n" if rendered else "(no studyloop call was made)\n")


def lockfile_diff(before: str | None, after: str | None) -> str:
    """Unified diff of ``modules.lock.json`` between two readings; absent files are empty."""
    diff = list(
        difflib.unified_diff(
            (before or "").splitlines(keepends=True),
            (after or "").splitlines(keepends=True),
            fromfile="modules.lock.json (before)",
            tofile="modules.lock.json (after)",
        )
    )
    if not diff:
        state = "absent" if before is None and after is None else "unchanged"
        return f"modules.lock.json {state}: no difference between the two readings\n"
    return "".join(diff)


def redact_text(text: str, *, homes: Sequence[Path], secrets: Mapping[str, str]) -> str:
    """Known secrets first (longest first), then roots, LAN addresses and digests.

    ``homes[0]`` is the persona's world root (``<WORLD>``), ``homes[1]`` the repository the
    tests run from (``<REPO>``); every later entry is a real home directory (``<HOME>``).
    Longest match first, so a world or a checkout under a home is named as itself.
    """
    for name, value in sorted(secrets.items(), key=lambda item: -len(item[1])):
        if value:
            text = text.replace(value, f"<REDACTED:{name}>")
    labels = ("<WORLD>", "<REPO>")
    labelled = [
        (str(h), labels[i] if i < len(labels) else "<HOME>") for i, h in enumerate(homes) if str(h)
    ]
    for root, label in sorted(labelled, key=lambda item: -len(item[0])):
        text = text.replace(root, label)
    text = _LAN_IPV4.sub("<LAN-IP>", text)
    return _HEX_DIGEST.sub(lambda m: m.group(1) + "…", text)


def _redact_json(value: object, *, homes: Sequence[Path], secrets: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return redact_text(value, homes=homes, secrets=secrets)
    if isinstance(value, dict):
        return {k: _redact_json(v, homes=homes, secrets=secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(v, homes=homes, secrets=secrets) for v in value]
    return value


def verify_redacted(run_dir: Path, *, secrets: Mapping[str, str]) -> list[str]:
    """Every textual member re-read and scanned: the UAT detector plus the known secrets."""
    violations: list[str] = []
    for path in sorted(run_dir.iterdir()):
        if path.suffix == ".png" or path.name == VIOLATIONS_NAME:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        violations.extend(f"{path.name}: {v}" for v in contains_forbidden_content(text))
        violations.extend(
            f"{path.name}: known secret {name!r} present"
            for name, v in secrets.items()
            if v in text
        )
    return violations


def write_persona_failure_bundle(
    evidence_root: Path,
    *,
    run_id: str,
    persona: str,
    outcome: str,
    phases: list[dict],
    harness: str = "fake-agent",
    server_log: str,
    cli_records: Sequence[CliRecord],
    lockfile_before: str | None,
    lockfile_after: str | None,
    attempt_envelope: dict | None,
    screenshot_png: bytes | None,
    page_html: str | None,
    console: Mapping[str, object],
    homes: Sequence[Path],
    secrets: Mapping[str, str],
) -> tuple[EvidenceBundle, list[str]]:
    """Write one persona's failure bundle and return it with its redaction verdict.

    ``harness`` is who played the mentor -- the selected RELEASE_HARNESSES name or ``fake-agent``
    (design.md §6, ruled at U1-review). ``attempt_envelope`` is written even when ``None`` (as
    ``null``) so a reader of a failure
    before any drill started still finds the file and learns that nothing was recorded, rather
    than wondering whether the member was forgotten. The verdict is the list of violations
    :func:`verify_redacted` found -- empty is the only acceptable value for a committed bundle.
    """
    redact = {"homes": homes, "secrets": secrets}
    envelope = _redact_json(attempt_envelope, **redact) if attempt_envelope is not None else None
    bundle = write_evidence_bundle(
        evidence_root,
        run_id=run_id,
        harness=harness,
        actor="scripted",
        outcome=outcome,
        turns=[dict(_redact_json(p, **redact)) for p in phases],  # type: ignore[arg-type]
        platform=None,
        auth_mode="presence-only",
        harness_version=None,
        server_log=redact_text(server_log, **redact),
        cli_transcript=redact_text(render_cli_transcript(cli_records), **redact),
        lockfile_diff=redact_text(lockfile_diff(lockfile_before, lockfile_after), **redact),
        attempt_envelope={"persona": persona, "envelope": envelope},
    )
    run_dir = bundle.run_dir
    if screenshot_png is not None:
        (run_dir / SCREENSHOT_NAME).write_bytes(screenshot_png)
    if page_html is not None:
        (run_dir / PAGE_HTML_NAME).write_text(redact_text(page_html, **redact), encoding="utf-8")
    (run_dir / CONSOLE_NAME).write_text(
        json.dumps(_redact_json(dict(console), **redact), indent=2) + "\n", encoding="utf-8"
    )
    violations = verify_redacted(run_dir, secrets=secrets)
    if violations:
        (run_dir / VIOLATIONS_NAME).write_text("\n".join(violations) + "\n", encoding="utf-8")
    return bundle, violations


__all__ = [
    "CONSOLE_NAME",
    "EXPECTED_MEMBERS",
    "PAGE_HTML_NAME",
    "SCREENSHOT_NAME",
    "VIOLATIONS_NAME",
    "CliRecord",
    "lockfile_diff",
    "redact_text",
    "render_cli_transcript",
    "verify_redacted",
    "write_persona_failure_bundle",
]
