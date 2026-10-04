"""Conformance checks for optional modules: ``studyloop module check <path>``.

Module-contract v1, lane C. :func:`check_module` evaluates the sixteen rules of proposal §6
(MC001-MC016) against one module directory and returns a :class:`CheckReport`. It reads
files only: nothing a module ships is imported, executed or evaluated, and no symlink is
followed out of the module directory. Fixtures under ``tests/fixtures/modules/`` pin one
fault per rule (``mcNNN/broken``) with a repaired twin (``mcNNN/repaired``).

Report contract
---------------
- ``CheckReport.ok`` is ``True`` exactly when ``findings`` is empty.
- Every ``Finding.rule_id`` is one of :data:`RULE_IDS`.
- A module that breaks exactly one rule yields findings carrying exactly one distinct
  ``rule_id``; several findings may share it (two tasks each missing an ``id``).
- ``Finding.path`` is the module-root-relative POSIX path of the offending file, or the
  name of the file that is *missing* (MC003); ``""`` only when no file applies.
- ``Finding.line`` is the 1-based line of the fault in that file, ``None`` when the fault is
  file-level (a missing file, a missing heading, a forbidden file's existence).
- ``Finding.message`` is one quotable sentence suitable for a PR comment. It never echoes a
  detected secret (MC009 names the keyword and the line, not the value).

Most-specific-rule-wins (spec, "optional-modules"): a bad ``contract`` is MC002 and a bad
``prerequisites[].id`` is MC005, never MC001; anything ``PracticeDeck`` rejects (missing
field, malformed or duplicate id, unknown key, bad JSON) is MC004; MC010 fires only for a
``solution`` without a ``scaffolding`` level; a referenced script that does not exist is MC007,
one that exists but is not a regular file inside the module is MC013, and a command that is
not one ``scripts/`` executable plus literal arguments is MC015.

``--json`` shape (``CheckReport.to_dict()``, emitted by ``studyloop module check --json``)::

    {
      "ok": false,
      "findings": [
        {"rule_id": "MC002", "message": "...", "path": "module.yaml", "line": 2}
      ]
    }

``line`` is an integer or ``null``. The CLI exits 0 when ``ok`` is true, 1 otherwise, 2 when
``<path>`` is not a directory.

MC009 reuses the *keyword* detector family core already runs in pre-commit (detect-secrets'
``KeywordDetector`` denylist) with its heuristic filters disabled, so a sequential or
low-entropy value that the commit hook ignores is still caught. detect-secrets itself is a
pre-commit tool, not a runtime dependency of StudyLoop, so the denylist is mirrored here
rather than imported.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from studyloop.content.schemas import PracticeDeck
from studyloop.modules.manifest import (
    PHASE_CAPABILITIES,
    PREREQUISITE_IDS,
    SUPPORTED_CONTRACTS,
    ModuleManifest,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

RULE_IDS: tuple[str, ...] = tuple(f"MC{n:03d}" for n in range(1, 17))
"""The sixteen conformance rule ids of proposal §6, in table order."""

REQUIRED_FILES: tuple[str, ...] = ("module.yaml", "README.md", "LICENSE", "CHANGELOG.md")
"""MC003, plus at least one ``decks/*.json``."""

REQUIRED_README_HEADINGS: tuple[str, ...] = (
    "Prerequisites",
    "What runs",
    "Data collected",
    "Limits",
)
"""MC011: the ``##`` headings proposal §5.1 lists, in any order."""

FORBIDDEN_CODE_FILES: frozenset[str] = frozenset(
    {"pyproject.toml", "package.json", "setup.py", "setup.cfg"}
)
"""MC012 by filename; see also :data:`FORBIDDEN_CODE_SUFFIXES`, ``__pycache__`` and shebangs."""

FORBIDDEN_CODE_SUFFIXES: frozenset[str] = frozenset({".py", ".pyc", ".pyo", ".pyd", ".pyw"})
"""MC012 by suffix: Python source, byte-compiled and extension files."""

_PYCACHE_DIRNAME = "__pycache__"
_PYTHON_SHEBANG = re.compile(
    r"^#!\s*(?:\S*/)?(?:env\s+(?:-\S+\s+)*)?python[0-9.]*(?:\s|$)", flags=re.ASCII
)
"""MC012 by shebang: ``#!/usr/bin/python``, ``#!/usr/bin/env python3``, ``#!/usr/bin/env -S python``
(the last two are what ``_PYTHON_SHEBANG`` accepts after ``env`` and its flags)."""

_SHELL_OPERATOR_TOKENS: frozenset[str] = frozenset(
    {"&&", "||", "|", ";", "&", ">", ">>", "<", "<<", "2>", "2>&1", "1>", "&>", "|&"}
)
_SHELL_SPECIAL_CHARS = re.compile(r"[$`|&;<>(){}*?\[\]!]")
_INTERPRETERS: frozenset[str] = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "fish", "env", "python", "python3", "perl", "ruby", "node"}
)
_CONTEXT_OVERRIDES: tuple[str, ...] = ("--context", "--kubeconfig")

# detect-secrets KeywordDetector denylist (plugins/keyword.py), mirrored: the keyword, an
# optional index/attribute tail, an assignment operator, then a non-empty literal value.
# No heuristic filter is applied (spec: a fixture secret the commit hook ignores is caught).
_SECRET_KEYWORDS = (
    r"api_?key|auth_?key|service_?key|account_?key|db_?key|database_?key|priv_?key|"
    r"private_?key|client_?key|db_?pass|database_?pass|key_?pass|password|passwd|pwd|"
    r"secret|secrete|token|contrase[nñ]a"
)
_SECRET_ASSIGNMENT = re.compile(
    rf"(?i)(?P<keyword>[\w.-]*(?:{_SECRET_KEYWORDS})[\w.-]*)"
    r"\s*(?:\[[^\]]*\])?\s*(?::=|=>|==|=|:)\s*"
    r"(?P<quote>[\"'])?(?P<value>[^\s\"']{4,})(?P=quote)?"
)
_SECRET_PLACEHOLDER_VALUES: frozenset[str] = frozenset({"true", "false", "null", "none"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation: which rule, where (file and line), and a quotable sentence."""

    rule_id: str
    message: str
    path: str
    line: int | None = None


@dataclass(frozen=True, slots=True)
class CheckReport:
    """The outcome of checking one module directory."""

    ok: bool
    findings: list[Finding]

    def to_dict(self) -> dict[str, Any]:
        """The ``--json`` payload: ``{"ok": bool, "findings": [...]}``."""
        return {"ok": self.ok, "findings": [asdict(finding) for finding in self.findings]}


def check_module(path: Path) -> CheckReport:
    """Check the module at ``path`` against MC001-MC016 and report every violation."""
    checker = _ModuleChecker(Path(path))
    findings = checker.run()
    return CheckReport(ok=not findings, findings=findings)


# ---------------------------------------------------------------------------
# Line locators: YAML (module.yaml) and JSON (decks) key paths -> 1-based line
# ---------------------------------------------------------------------------

_KeyPath = tuple[str | int, ...]


def _yaml_key_lines(text: str) -> dict[_KeyPath, int]:
    """Map every key path in a YAML document to the line its key (or item) starts on."""
    lines: dict[_KeyPath, int] = {}
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        return lines

    def walk(node: yaml.Node | None, prefix: _KeyPath) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                key = getattr(key_node, "value", None)
                if not isinstance(key, str):
                    continue
                lines[(*prefix, key)] = key_node.start_mark.line + 1
                walk(value_node, (*prefix, key))
        elif isinstance(node, yaml.SequenceNode):
            for index, item in enumerate(node.value):
                lines[(*prefix, index)] = item.start_mark.line + 1
                walk(item, (*prefix, index))

    walk(root, ())
    return lines


def _json_key_lines(text: str) -> dict[_KeyPath, int]:
    """Map every key path in an already-valid JSON document to its 1-based start line.

    Objects and arrays are recorded at their opening bracket, keys at the opening quote of
    the key, so a *missing* key can be reported at the line of the object that lacks it.
    """
    lines: dict[_KeyPath, int] = {}
    whitespace = re.compile(r"\s*")
    decoder = json.JSONDecoder()

    def line_of(index: int) -> int:
        return text.count("\n", 0, index) + 1

    def skip(index: int) -> int:
        match = whitespace.match(text, index)
        return match.end() if match else index

    def value(index: int, prefix: _KeyPath) -> int:
        index = skip(index)
        char = text[index]
        if char == "{":
            lines[prefix] = line_of(index)
            index = skip(index + 1)
            if text[index] == "}":
                return index + 1
            while True:
                index = skip(index)
                key_start = index
                key, index = decoder.raw_decode(text, index)
                lines[(*prefix, str(key))] = line_of(key_start)
                index = skip(index)  # at ':'
                index = value(index + 1, (*prefix, str(key)))
                index = skip(index)
                if text[index] == ",":
                    index += 1
                    continue
                return index + 1  # '}'
        if char == "[":
            lines[prefix] = line_of(index)
            index = skip(index + 1)
            if text[index] == "]":
                return index + 1
            position = 0
            while True:
                index = skip(index)
                lines[(*prefix, position)] = line_of(index)
                index = value(index, (*prefix, position))
                index = skip(index)
                if text[index] == ",":
                    index += 1
                    position += 1
                    continue
                return index + 1  # ']'
        _, end = decoder.raw_decode(text, index)
        return end

    try:
        value(0, ())
    except (ValueError, IndexError, StopIteration):
        return {}
    return lines


def _nearest_line(lines: dict[_KeyPath, int], loc: _KeyPath) -> int | None:
    """The line of ``loc`` or of its deepest located ancestor; ``None`` when nothing matches."""
    for end in range(len(loc), -1, -1):
        line = lines.get(tuple(loc[:end]))
        if line is not None:
            return line
    return None


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


def _phase_fields(verification: dict[str, Any]) -> list[tuple[str, str, str]]:
    """``(field, capability, command)`` for each non-empty phase command of a verification."""
    phases: list[tuple[str, str, str]] = []
    for field, capability in PHASE_CAPABILITIES.items():
        command = verification.get(field)
        if isinstance(command, str) and command.strip():
            phases.append((field, capability, command))
    return phases


def _shebang_interpreter(path: Path) -> str | None:
    """The first line of ``path`` when it is a ``#!`` line, else ``None``. Reads 256 bytes."""
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None
        with path.open("rb") as handle:
            head = handle.read(256)
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    return head.split(b"\n", 1)[0].decode("utf-8", errors="replace")


def _is_text_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


class _ModuleChecker:
    """One run of the rules over one module directory. Not reusable."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.findings: list[Finding] = []
        self.manifest: ModuleManifest | None = None
        self.manifest_lines: dict[_KeyPath, int] = {}
        self.used_capabilities: set[str] = set()
        # A deck that could not be read or validated has unknown phase usage; MC016 would
        # then blame the manifest for the deck's fault, so it stays silent for that module.
        self.deck_usage_unknown = False

    # -- helpers ------------------------------------------------------------

    def add(self, rule_id: str, message: str, path: str, line: int | None = None) -> None:
        self.findings.append(Finding(rule_id, message, path, line))

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def walk_files(self) -> Iterator[Path]:
        """Every file under the module (``.git/`` excluded), without following symlinks."""
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name != ".git")
            for name in sorted(filenames):
                yield Path(dirpath) / name

    # -- entry point ----------------------------------------------------------

    def run(self) -> list[Finding]:
        if not self.root.is_dir():
            self.add("MC003", f"{self.root} is not a directory", "")
            return self.findings
        self.check_required_files()  # MC003
        self.check_manifest()  # MC001, MC002, MC005
        self.check_decks()  # MC004, MC006, MC007, MC008, MC010, MC013, MC014, MC015
        self.check_unused_capabilities()  # MC016
        self.check_secrets()  # MC009
        self.check_readme_headings()  # MC011
        self.check_no_code()  # MC012
        return self.findings

    # -- MC003 ------------------------------------------------------------------

    def check_required_files(self) -> None:
        for name in REQUIRED_FILES:
            if not (self.root / name).is_file():
                self.add("MC003", f"required file {name} is missing", name)
        if not self.deck_paths():
            self.add("MC003", "no deck found: at least one decks/*.json is required", "decks")

    def deck_paths(self) -> list[Path]:
        decks_dir = self.root / "decks"
        if not decks_dir.is_dir():
            return []
        return sorted(p for p in decks_dir.iterdir() if p.name.endswith(".json"))

    # -- MC001 / MC002 / MC005 ---------------------------------------------------

    def check_manifest(self) -> None:
        manifest_path = self.root / "module.yaml"
        if not manifest_path.is_file():
            return  # MC003 already said so
        text = manifest_path.read_text(encoding="utf-8", errors="replace")
        self.manifest_lines = _yaml_key_lines(text)
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark is not None else None
            self.add("MC001", "module.yaml is not valid YAML", "module.yaml", line)
            return
        if not isinstance(raw, dict):
            self.add("MC001", "module.yaml must be a mapping of manifest keys", "module.yaml", 1)
            return
        try:
            manifest = ModuleManifest.model_validate(raw)
        except ValidationError as exc:
            for error in exc.errors():
                self.add_manifest_error(error)
            return
        self.manifest = manifest
        if manifest.contract not in SUPPORTED_CONTRACTS:
            speaks = ", ".join(str(v) for v in SUPPORTED_CONTRACTS)
            self.add(
                "MC002",
                f"contract {manifest.contract} is not one this StudyLoop speaks "
                f"(supported: {speaks})",
                "module.yaml",
                self.manifest_lines.get(("contract",)),
            )
        for index, prerequisite in enumerate(manifest.prerequisites):
            if prerequisite.id not in PREREQUISITE_IDS:
                known = ", ".join(PREREQUISITE_IDS)
                self.add(
                    "MC005",
                    f"prerequisite id {prerequisite.id!r} is not in core's enum ({known})",
                    "module.yaml",
                    _nearest_line(self.manifest_lines, ("prerequisites", index, "id")),
                )

    def add_manifest_error(self, error: Mapping[str, Any]) -> None:
        loc: _KeyPath = tuple(error.get("loc", ()))
        line = _nearest_line(self.manifest_lines, loc)
        dotted = ".".join(str(part) for part in loc) or "module.yaml"
        if loc[:1] == ("contract",):
            speaks = ", ".join(str(v) for v in SUPPORTED_CONTRACTS)
            self.add(
                "MC002",
                f"contract must be an integer version this StudyLoop speaks (supported: {speaks})",
                "module.yaml",
                line,
            )
        elif len(loc) == 3 and loc[0] == "prerequisites" and loc[2] == "id":
            known = ", ".join(PREREQUISITE_IDS)
            self.add(
                "MC005", f"{dotted}: prerequisite id must be one of {known}", "module.yaml", line
            )
        elif error.get("type") == "extra_forbidden":
            self.add("MC001", f"module.yaml has an unknown key {dotted!r}", "module.yaml", line)
        else:
            self.add(
                "MC001",
                f"module.yaml: {dotted}: {error.get('msg', 'invalid')}",
                "module.yaml",
                line,
            )

    # -- decks: MC004, MC006, MC007, MC008, MC010, MC013, MC014, MC015 -----------

    def check_decks(self) -> None:
        seen_deck_ids: dict[str, str] = {}
        for deck_path in self.deck_paths():
            rel = self.rel(deck_path)
            if not self.is_regular_inside(deck_path):
                self.add("MC013", f"{rel} is not a regular file inside the module", rel)
                self.deck_usage_unknown = True
                continue
            text = deck_path.read_text(encoding="utf-8", errors="replace")
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                self.add("MC004", f"{rel} is not valid JSON: {exc.msg}", rel, exc.lineno)
                self.deck_usage_unknown = True
                continue
            lines = _json_key_lines(text)
            try:
                deck = PracticeDeck.model_validate(raw)
            except ValidationError as exc:
                for error in exc.errors():
                    loc: _KeyPath = tuple(error.get("loc", ()))
                    dotted = ".".join(str(part) for part in loc)
                    self.add(
                        "MC004",
                        f"{rel} does not validate as a PracticeDeck: {dotted}: "
                        f"{error.get('msg', 'invalid')}",
                        rel,
                        _nearest_line(lines, loc),
                    )
                self.deck_usage_unknown = True
                continue
            if not isinstance(raw, dict):
                continue  # PracticeDeck.model_validate would have rejected it
            # MC014 -- deck id present and unique within the module
            if deck.id is None:
                self.add("MC014", f"{rel} has no deck id", rel, lines.get(()))
            elif deck.id in seen_deck_ids:
                self.add(
                    "MC014",
                    f"deck id {deck.id!r} is already used by {seen_deck_ids[deck.id]}",
                    rel,
                    lines.get(("id",)),
                )
            else:
                seen_deck_ids[deck.id] = rel
            raw_tasks = raw.get("tasks") or []
            for index, task in enumerate(deck.tasks):
                raw_task = raw_tasks[index] if index < len(raw_tasks) else {}
                task_loc: _KeyPath = ("tasks", index)
                label = task.id or f"tasks[{index}]"
                if task.id is None:
                    self.add(
                        "MC014", f"{rel}: tasks[{index}] has no task id", rel, lines.get(task_loc)
                    )
                # MC010 -- solution needs a scaffolding level (the rest is schema, MC004)
                if task.solution and task.scaffolding is None:
                    self.add(
                        "MC010",
                        f"{rel}: task {label} has a solution but no scaffolding level",
                        rel,
                        _nearest_line(lines, (*task_loc, "solution")),
                    )
                verification = raw_task.get("verification") if isinstance(raw_task, dict) else None
                if not isinstance(verification, dict):
                    continue
                for field, capability, command in _phase_fields(verification):
                    self.used_capabilities.add(capability)
                    line = _nearest_line(lines, (*task_loc, "verification", field))
                    self.check_phase_command(rel, label, field, capability, command, line)

    def check_phase_command(
        self, rel: str, label: str, field: str, capability: str, command: str, line: int | None
    ) -> None:
        where = f"{rel}: task {label} {field}"
        # MC006 -- the phase's capability must be declared
        if (
            self.manifest is not None
            and capability not in self.manifest.declared_phase_capabilities()
        ):
            self.add(
                "MC006",
                f"{where} needs capability {capability!r}, which module.yaml does not declare",
                rel,
                line,
            )
        # MC015 -- tokenise; one scripts/ executable plus literal arguments
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError as exc:
            self.add("MC015", f"{where} is not a plain argv ({exc})", rel, line)
            return
        if not tokens:
            self.add("MC015", f"{where} is empty", rel, line)
            return
        shell_tokens = [
            t for t in tokens if t in _SHELL_OPERATOR_TOKENS or _SHELL_SPECIAL_CHARS.search(t)
        ]
        if shell_tokens:
            self.add(
                "MC015",
                f"{where} contains shell syntax ({', '.join(repr(t) for t in shell_tokens)}); "
                "a phase is one scripts/ executable plus literal arguments",
                rel,
                line,
            )
            return
        executable = tokens[0]
        # MC007 -- no absolute or home-relative paths anywhere in the command
        bad_paths = [t for t in tokens if t.startswith(("/", "~"))]
        if bad_paths:
            self.add(
                "MC007",
                f"{where} uses an absolute or home-relative path "
                f"({', '.join(repr(t) for t in bad_paths)})",
                rel,
                line,
            )
            return
        if PurePosixPath(executable).name in _INTERPRETERS:
            self.add(
                "MC015",
                f"{where} invokes an interpreter ({executable!r}) instead of a scripts/ executable",
                rel,
                line,
            )
            return
        script = PurePosixPath(executable)
        parts = [p for p in script.parts if p != "."]
        if ".." in parts:
            self.add("MC013", f"{where} escapes the module directory ({executable!r})", rel, line)
            return
        if not parts or parts[0] != "scripts" or len(parts) < 2:
            self.add(
                "MC015",
                f"{where} must name an executable under scripts/ (got {executable!r})",
                rel,
                line,
            )
            return
        target = self.root.joinpath(*parts)
        if not target.exists() and not target.is_symlink():
            self.add("MC007", f"{where} references {executable!r}, which does not exist", rel, line)
            return
        if not self.is_regular_inside(target):
            self.add(
                "MC013",
                f"{where} references {executable!r}, which is not a regular file inside the module "
                "(symlink, hardlink, device or path escape)",
                rel,
                line,
            )
            return
        if not os.access(target, os.X_OK):
            self.add(
                "MC015", f"{where} references {executable!r}, which is not executable", rel, line
            )
            return
        # MC008 -- no context override on a kubeconfig-context target
        if self.manifest is not None and self.manifest.target.kind == "kubeconfig-context":
            overrides = [
                t
                for t in tokens[1:]
                if t in _CONTEXT_OVERRIDES
                or t.startswith(tuple(f"{o}=" for o in _CONTEXT_OVERRIDES))
                or t == "use-context"
            ]
            if overrides:
                self.add(
                    "MC008",
                    f"{where} overrides the injected context "
                    f"({', '.join(repr(t) for t in overrides)})",
                    rel,
                    line,
                )

    def is_regular_inside(self, path: Path) -> bool:
        """A regular, non-hardlinked file whose real location is inside the module."""
        try:
            info = path.lstat()
        except OSError:
            return False
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            return False
        try:
            path.resolve(strict=True).relative_to(self.root.resolve(strict=True))
        except (OSError, ValueError):
            return False
        return True

    # -- MC016 ------------------------------------------------------------------

    def check_unused_capabilities(self) -> None:
        if self.manifest is None or self.deck_usage_unknown:
            return
        unused = sorted(self.manifest.declared_phase_capabilities() - self.used_capabilities)
        for capability in unused:
            self.add(
                "MC016",
                f"module.yaml declares capability {capability!r} but no deck phase uses it",
                "module.yaml",
                self.manifest_lines.get(("capabilities",)),
            )

    # -- MC009 ------------------------------------------------------------------

    def check_secrets(self) -> None:
        for path in self.walk_files():
            if not _is_text_file(path):
                continue
            try:
                text = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            rel = self.rel(path)
            for number, content in enumerate(text.splitlines(), start=1):
                # Every assignment on the line is a candidate: `PASSWORD=true TOKEN=<real>`
                # must not pass because the first match happened to be a placeholder.
                flagged = [
                    match.group("keyword")
                    for match in _SECRET_ASSIGNMENT.finditer(content)
                    if match.group("value").lower().strip("\"'") not in _SECRET_PLACEHOLDER_VALUES
                ]
                if not flagged:
                    continue
                self.add(
                    "MC009",
                    f"{rel}:{number} assigns a literal value to "
                    f"{', '.join(repr(k) for k in flagged)}; "
                    "no secret patterns may ship in a module",
                    rel,
                    number,
                )

    # -- MC011 ------------------------------------------------------------------

    def check_readme_headings(self) -> None:
        readme = self.root / "README.md"
        if not readme.is_file():
            return  # MC003
        text = readme.read_text(encoding="utf-8", errors="replace")
        headings = {
            match.group(1).strip().rstrip("#").strip().casefold()
            for match in re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
        }
        for heading in REQUIRED_README_HEADINGS:
            if heading.casefold() not in headings:
                self.add(
                    "MC011", f"README.md lacks the required heading '## {heading}'", "README.md"
                )

    # -- MC012 ------------------------------------------------------------------

    def check_no_code(self) -> None:
        for dirpath, dirnames, _ in os.walk(self.root, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name != ".git")
            if _PYCACHE_DIRNAME in dirnames:
                rel = self.rel(Path(dirpath) / _PYCACHE_DIRNAME)
                self.add(
                    "MC012", f"{rel}/ is a Python bytecode cache; a module ships data only", rel
                )
        for path in self.walk_files():
            rel = self.rel(path)
            if path.parent.name == _PYCACHE_DIRNAME:
                continue  # reported once, on the directory
            if path.name in FORBIDDEN_CODE_FILES or path.suffix.lower() in FORBIDDEN_CODE_SUFFIXES:
                self.add("MC012", f"{rel} is importable code; a module ships data only", rel)
                continue
            interpreter = _shebang_interpreter(path)
            if interpreter is not None and _PYTHON_SHEBANG.match(interpreter):
                self.add(
                    "MC012",
                    f"{rel} is a Python script ({interpreter.strip()}); a module ships data only",
                    rel,
                    1,
                )
