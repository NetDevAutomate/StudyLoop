"""The documented `studyloop module` contract, parsed, and the comparison B9 runs (U1-review F7).

Persona B's step (6) is "assert the docs' commands and the observed output agree". The static
half -- every fenced ``studyloop ...`` line resolves against the real CLI -- is
``test_docs_drift.py``'s. This module is the OBSERVED half: what the two pages promise about the
output of ``module new``, ``module check``, ``module list`` and ``module add`` is parsed into a
:class:`DocumentedModuleContract`, and :func:`compare_observed` names every disagreement with
what the persona actually saw.

Where the promises live, because the pages carry no fenced OUTPUT blocks (they fence the commands
and describe the output in prose, and the ``--help`` docstrings ARE the shipped output contract):

- ``docs/module-contract.md``: the fenced ``studyloop module ...`` commands; "prints `ready` and
  exits 0" (the scaffold's check script); the finding template ``MCnnn <file>:<line>: <message>``;
  "the snapshot lands under ... `modules/snapshots/<digest>` and `modules.lock.json` records the
  id, version and content digest"; the documented drill ref.
- ``docs/cli-reference.md``: the fenced commands and their trailing comments -- "exit 0 conforming,
  1 findings, 2 not a dir".
- the Click help of ``studyloop module new|check|list`` (``studyloop.cli._module``): the files
  ``new`` writes; "One line per module: id, version, the first 12 hex digits of the content digest
  and the snapshot directory"; ``--json``'s ``{ok, findings[{rule_id,message,path,line}]}``.

Normalisation (no receipt-audit code exists to borrow; the rules are stated here): a path
argument is ``<path>``, a slug argument ``<id>``, a sha256 digest ``<digest>`` -- command SHAPES
are compared, never literal paths, so a doc that says ``./my-drills`` and a persona that ran
``/tmp/.../my-drills`` agree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_FENCE_RE = re.compile(r"^\s*(?:`{3,}|~{3,})\s*([A-Za-z0-9_+-]*)")
_MODULE_CMD_RE = re.compile(r"^\$?\s*(studyloop module \S.*?)(?:\s+#.*)?$")
_EXIT_CODES_RE = re.compile(r"exit (\d) conforming, (\d) findings, (\d) not a dir", re.IGNORECASE)
_FINDING_TEMPLATE_RE = re.compile(r"`(MCnnn <file>:<line>: <message>)`")
_PRINTS_RE = re.compile(r"prints `([^`]+)` and exits (\d)")
_SNAPSHOT_RE = re.compile(r"`(modules/snapshots/<digest>)`")
_LOCKFILE_FIELDS_RE = re.compile(
    r"`modules\.lock\.json` records the id, version and content digest", re.IGNORECASE
)
_DRILL_REF_RE = re.compile(r"studyloop drill check (my-drills/\S+)")
_HEX_DIGITS_RE = re.compile(r"first (\d+) hex digits of the content digest")
_JSON_SHAPE_RE = re.compile(r"\{(\w+), (\w+)\[\{([\w,]+)\}\]\}")
_SCAFFOLD_FILE_RE = re.compile(r"\b((?:[a-z]+/)?[A-Za-z][\w.-]*\.(?:yaml|md|sh|json)|LICENSE)\b")
_DIGEST_HEX_RE = re.compile(r"\b[0-9a-f]{64}\b")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class DocumentedModuleContract:
    """Everything the pages and the help promise about the module commands' output."""

    documented_commands: tuple[str, ...]
    finding_template: str
    check_exit_codes: dict[str, int]
    json_report_keys: tuple[str, ...]
    json_finding_keys: tuple[str, ...]
    list_digest_hex: int
    scaffold_files: tuple[str, ...]
    check_script_prints: str
    check_script_exit: int
    snapshot_dir_template: str
    lockfile_fields: tuple[str, ...]
    drill_ref: str


@dataclass(frozen=True)
class ObservedModuleOutputs:
    """What the persona saw. ``None``/empty members are skipped by the comparison, so a persona
    that did not run a command is not blamed for it -- except the documented commands, which it
    must have run."""

    commands_run: tuple[str, ...]
    check_finding_lines: tuple[str, ...]
    check_exit_codes: dict[str, int]
    json_report: Mapping[str, object] | None
    list_lines: tuple[str, ...]
    lockfile_entries: tuple[Mapping[str, object], ...]
    add_stdout: str
    scaffold_dir: Path | None
    check_script_stdout: str | None
    check_script_exit: int | None


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def fenced_shell_lines(text: str) -> list[str]:
    """Lines inside ```bash / ```sh / ``` fences, comments kept (the parsers read them)."""
    out: list[str] = []
    lang: str | None = None
    for line in text.splitlines():
        match = _FENCE_RE.match(line)
        if match:
            lang = match.group(1).lower() if lang is None else None
            continue
        if lang is not None and lang in {"bash", "sh", "shell", "console", ""}:
            out.append(line)
    return out


def documented_module_commands(text: str) -> list[str]:
    """Every fenced ``studyloop module ...`` command on a page, trailing comment dropped."""
    found: list[str] = []
    for line in fenced_shell_lines(text):
        match = _MODULE_CMD_RE.match(line)
        if match:
            found.append(match.group(1).strip())
    return found


def command_shape(command: str) -> str:
    """``studyloop module check --json ./my-drills`` -> ``check --json <path>``; ids -> ``<id>``.

    Also accepts an argv tail (``check --json /abs/my-drills``) so observed calls normalise the
    same way the documented ones do.
    """
    tokens = command.split()
    if tokens[:1] == ["studyloop"]:
        tokens = tokens[1:]
    if tokens[:1] == ["module"]:
        tokens = tokens[1:]
    if not tokens:
        return ""
    shaped = [tokens[0]]
    for token in tokens[1:]:
        if token.startswith("-"):
            shaped.append(token)
        elif "/" in token or token.startswith("."):
            shaped.append("<path>")
        elif _SLUG_RE.match(token):
            shaped.append("<id>")
        else:
            shaped.append(token)
    return " ".join(shaped)


def template_to_regex(template: str) -> re.Pattern[str]:
    """``MCnnn <file>:<line>: <message>`` -> an anchored regex; literal text is escaped."""
    parts: list[str] = []
    for piece in re.split(r"(MCnnn|<file>|<line>|<message>|<digest>)", template):
        if piece == "MCnnn":
            parts.append(r"MC\d{3}")
        elif piece == "<file>":
            parts.append(r"[^\s:]+")
        elif piece == "<line>":
            parts.append(r"\d+")
        elif piece == "<message>":
            parts.append(r".+")
        elif piece == "<digest>":
            # The snapshot directory is the bare content hash (modules/store.py); a prefixed
            # spelling is accepted too so a doc example or a fixture may carry `sha256:`.
            parts.append(r"(?:sha256[-:])?[0-9a-f]{64}")
        else:
            parts.append(re.escape(piece))
    return re.compile("^" + "".join(parts) + "$")


def _help_text(command: str) -> tuple[str, str]:
    """``(help, --json help)`` of ``studyloop module <command>`` from the real Click objects."""
    from studyloop.cli._module import module_group

    cmd = module_group.commands[command]
    json_help = ""
    for param in cmd.params:
        if "--json" in (getattr(param, "opts", None) or ()):
            json_help = str(getattr(param, "help", "") or "")
    return cmd.help or "", json_help


def load_documented_contract(docs_dir: Path) -> DocumentedModuleContract:
    """Parse the two pages under ``docs_dir`` and the shipped ``--help`` texts."""
    contract_page = (docs_dir / "module-contract.md").read_text(encoding="utf-8")
    reference_page = (docs_dir / "cli-reference.md").read_text(encoding="utf-8")
    pages = contract_page + "\n" + reference_page

    commands = tuple(
        dict.fromkeys(
            documented_module_commands(contract_page) + documented_module_commands(reference_page)
        )
    )
    finding = _FINDING_TEMPLATE_RE.search(pages)
    exits = _EXIT_CODES_RE.search(pages)
    prints = _PRINTS_RE.search(contract_page)
    snapshot = _SNAPSHOT_RE.search(contract_page)
    drill_ref = _DRILL_REF_RE.search(contract_page)
    for name, match in (
        ("finding template", finding),
        ("exit codes", exits),
        ("check script output", prints),
        ("snapshot dir template", snapshot),
        ("drill ref", drill_ref),
    ):
        if match is None:
            raise ValueError(f"docs no longer state the {name} the module personas compare against")
    assert finding and exits and prints and snapshot and drill_ref  # for the type checker
    lockfile_fields = ("id", "version", "digest") if _LOCKFILE_FIELDS_RE.search(pages) else ()

    new_help, _ = _help_text("new")
    _check_help, check_json_help = _help_text("check")
    list_help, _ = _help_text("list")
    hex_digits = _HEX_DIGITS_RE.search(list_help)
    json_shape = _JSON_SHAPE_RE.search(check_json_help)
    if hex_digits is None or json_shape is None:
        raise ValueError(
            "`studyloop module list/check --help` no longer state the documented shapes"
        )
    writes = new_help.split("Writes", 1)[1].split("into", 1)[0] if "Writes" in new_help else ""
    scaffold_files = tuple(dict.fromkeys(_SCAFFOLD_FILE_RE.findall(writes)))

    return DocumentedModuleContract(
        documented_commands=commands,
        finding_template=finding.group(1),
        check_exit_codes={
            "conforming": int(exits.group(1)),
            "findings": int(exits.group(2)),
            "not a dir": int(exits.group(3)),
        },
        json_report_keys=(json_shape.group(1), json_shape.group(2)),
        json_finding_keys=tuple(json_shape.group(3).split(",")),
        list_digest_hex=int(hex_digits.group(1)),
        scaffold_files=scaffold_files,
        check_script_prints=prints.group(1),
        check_script_exit=int(prints.group(2)),
        snapshot_dir_template=snapshot.group(1),
        lockfile_fields=lockfile_fields,
        drill_ref=drill_ref.group(1),
    )


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------


def _digest_hex(digest: object) -> str:
    text = str(digest)
    match = _DIGEST_HEX_RE.search(text)
    return match.group(0) if match else ""


def compare_observed(
    contract: DocumentedModuleContract, observed: ObservedModuleOutputs
) -> list[str]:
    """Every way the observed output disagrees with the documented contract; empty when none."""
    mismatches: list[str] = []

    # 1. Every documented `studyloop module` command was run, by shape.
    run_shapes = {command_shape(c) for c in observed.commands_run}
    for command in contract.documented_commands:
        shape = command_shape(command)
        if shape not in run_shapes:
            mismatches.append(
                f"documented command `{command}` (shape {shape!r}) was not run by the persona; "
                f"run: {sorted(run_shapes)}"
            )

    # 2. `module check`: each finding line has the documented shape; exit codes as documented.
    finding_re = template_to_regex(contract.finding_template)
    for line in observed.check_finding_lines:
        if not finding_re.match(line):
            mismatches.append(
                f"`module check` finding {line!r} does not match the documented template "
                f"{contract.finding_template!r}"
            )
    for case, documented in contract.check_exit_codes.items():
        seen = observed.check_exit_codes.get(case)
        if seen is not None and seen != documented:
            mismatches.append(
                f"`module check` exit for {case!r}: documented {documented}, saw {seen}"
            )
    if observed.json_report is not None:
        keys = tuple(observed.json_report)
        if set(keys) != set(contract.json_report_keys):
            mismatches.append(
                f"`module check --json` keys {sorted(keys)} != documented "
                f"{sorted(contract.json_report_keys)}"
            )
        findings = observed.json_report.get(contract.json_report_keys[1], [])
        for finding in findings if isinstance(findings, list) else []:
            if set(finding) != set(contract.json_finding_keys):
                mismatches.append(
                    f"`module check --json` finding keys {sorted(finding)} != documented "
                    f"{sorted(contract.json_finding_keys)}"
                )

    # 3. `module list`: id, version, the first N hex digits, the snapshot directory.
    by_id = {str(entry.get("id")): entry for entry in observed.lockfile_entries}
    for line in observed.list_lines:
        columns = line.split()
        if len(columns) != 4:
            mismatches.append(
                f"`module list` line {line!r} has {len(columns)} columns; documented: id, version, "
                f"digest, snapshot directory"
            )
            continue
        module_id, version, digest12, snapshot = columns
        entry = by_id.get(module_id)
        if entry is None:
            mismatches.append(f"`module list` names {module_id!r}, which the lockfile does not")
            continue
        full = _digest_hex(entry.get("digest"))
        want = full[: contract.list_digest_hex]
        if len(digest12) != contract.list_digest_hex or digest12 != want:
            mismatches.append(
                f"`module list` digest column {digest12!r} is not the first "
                f"{contract.list_digest_hex} hex digits of the lockfile digest ({want!r})"
            )
        if str(entry.get("version")) != version:
            mismatches.append(
                f"`module list` version {version!r} != lockfile {entry.get('version')!r}"
            )
        if not snapshot.endswith(f"snapshots/{Path(str(entry.get('snapshot'))).name}"):
            mismatches.append(
                f"`module list` snapshot column {snapshot!r} is not the lockfile's snapshot "
                "directory"
            )

    # 4. `module add`: the snapshot lands under modules/snapshots/<digest>; the lockfile records
    #    id, version and content digest.
    if observed.add_stdout:
        snapshot_re = template_to_regex(contract.snapshot_dir_template)
        snapshot_lines = [
            line.split(":", 1)[1].strip()
            for line in observed.add_stdout.splitlines()
            if line.startswith("snapshot:")
        ]
        if not snapshot_lines:
            mismatches.append("`module add` printed no `snapshot:` line")
        for path in snapshot_lines:
            # The template names the tail of the path: `modules/snapshots/<digest>`.
            tail = "/".join(path.rstrip("/").split("/")[-3:])
            if not snapshot_re.match(tail):
                mismatches.append(
                    f"`module add` snapshot {path!r} is not under the documented "
                    f"{contract.snapshot_dir_template!r}"
                )
    for entry in observed.lockfile_entries:
        missing = [field for field in contract.lockfile_fields if not entry.get(field)]
        if missing:
            mismatches.append(f"lockfile entry {entry.get('id')!r} lacks documented {missing}")

    # 5. `module new`: the files the help says it writes exist; the scaffold's check script
    #    prints what module-contract.md says and exits as documented.
    if observed.scaffold_dir is not None:
        for rel in contract.scaffold_files:
            if not (observed.scaffold_dir / rel).is_file():
                mismatches.append(f"`module new` did not write documented {rel}")
    if (
        observed.check_script_stdout is not None
        and observed.check_script_stdout.strip() != contract.check_script_prints
    ):
        mismatches.append(
            f"the scaffold's check script printed {observed.check_script_stdout!r}; "
            f"documented `{contract.check_script_prints}`"
        )
    if (
        observed.check_script_exit is not None
        and observed.check_script_exit != contract.check_script_exit
    ):
        mismatches.append(
            f"the scaffold's check script exited {observed.check_script_exit}; documented "
            f"{contract.check_script_exit}"
        )
    return mismatches


def observed_commands(records: Iterable[Sequence[str]]) -> tuple[str, ...]:
    """The persona's ``studyloop module ...`` calls as command tails, from its CLI records."""
    found: list[str] = []
    for argv in records:
        tokens = list(argv)
        if tokens[:1] == ["module"]:
            found.append(" ".join(tokens))
    return tuple(found)


__all__ = [
    "DocumentedModuleContract",
    "ObservedModuleOutputs",
    "command_shape",
    "compare_observed",
    "documented_module_commands",
    "fenced_shell_lines",
    "load_documented_contract",
    "observed_commands",
    "template_to_regex",
]
