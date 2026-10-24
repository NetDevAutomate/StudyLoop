#!/usr/bin/env python3
"""check-openspec-split — a split may change the shape of a spec, never what it requires.

Plan 7 (reviews/2026-10-21-full-repo-review/REMEDIATION-PLAN-7.md, ARBITRATION-pass9.md §3 and
§8.2) splits every OpenSpec requirement whose body exceeds the validator's 500-character limit.
OpenSpec itself checks only shape (length, SHALL/MUST present, at least one scenario). This script
checks that the *content* survived: it compares the ``openspec/`` tree at a base revision with the
working tree and reports every difference that is not covered by a named, consumed exception.

What is conserved, per spec file (living ``specs/<id>/spec.md`` and change deltas
``changes/<change>/specs/<id>/spec.md`` alike):

* **Units** -- every sentence of body prose (not only SHALL/MUST sentences; a list item under a
  lead-in that ends in ``:`` inherits that lead-in's force and is a unit too). The multiset of units
  across body and scenario text must be identical, except through ``deleted``, ``split-sentence``,
  ``inherit-shall``, ``reference-expansion`` or ``context-restated`` entries.
* **Scope** -- a conditional or ordering lead-in travels verbatim into every fragment that holds a
  unit it governs (``context-lost``), the normative order per original heading is preserved
  (``normative-order-changed``), and deictic or structural references (``the list above``, ``this
  requirement``, ``rule N`` ...) must resolve inside their own body (``orphaned-reference``).
* **Scenarios** -- the multiset of (name, body) is identical; re-homing is allowed and listed; a new
  scenario needs a source (``moved-body-text``, ``test-sourced`` with a nodeid resolved against a
  collected list, or ``restates-shall`` which may not introduce a literal its body lacks). Names are
  unique within a file.
* **Headings** -- every original heading survives verbatim exactly once; new headings are unique and
  fold-distinct from every living heading of the same capability (archive refuses near misses).
* **Fences** -- the multiset of fenced blocks is identical and each stays anchored to the unit that
  precedes it; prose may not be turned into a fence or a ``**Label**:`` metadata line to dodge the
  tool's length measure.
* **Purpose** -- unchanged unless declared.
* **Tool rules** -- every head body is <= 500 by the tool's own measure (``requirement_body``),
  holds SHALL or MUST, and has a scenario.

A drift report lists everything a pass-10 reader must read: fissions, inherited modals,
duplicated lead-ins, deletions, re-homed scenarios, restatements, fence moves, compound-heading
splits.

Exit status: 0 when no FAIL finding; 1 otherwise; 2 on usage error. WARN findings never fail the
run.

Usage::

    check-openspec-split.py --base <git-rev> [--spec <id> ...] [--json out.json]
    check-openspec-split.py --base-dir <openspec dir> --head-dir <openspec dir> ...
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

MAX_BODY = 500  # OpenSpec's MAX_REQUIREMENT_TEXT_LENGTH (dist/core/validation/constants.js)

FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADER_RE = re.compile(r"^#{1,6}\s")
REQ_RE = re.compile(r"^### Requirement:\s*(.+?)\s*$")
SCENARIO_RE = re.compile(r"^####\s+(?:Scenario:\s*)?(.+?)\s*$")
METADATA_RE = re.compile(r"^\*\*[^*]+\*\*:")
KEYWORD_RE = re.compile(r"\b(SHALL|MUST)\b")
LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)]|[a-z][.)])\s+")
TABLE_ROW_RE = re.compile(r"^\|")
TABLE_DELIM_RE = re.compile(r"^\|\s*:?-{3,}")
LEAD_IN_WORDS = re.compile(
    r"\b(when|if|unless|only|for each|where|after|before|in this order|whenever)\b", re.I
)
ORDER_MARKERS = re.compile(r"\b(in this order|first\b.*\bthen|after rule \d+|rule \d+)\b", re.I)
DEICTIC_RE = re.compile(
    r"\b(the list above|the table above|the list below|the table below|the following list|"
    r"these rules|this requirement's|this requirement|the body above|"
    r"requirements? in this specification|the (?:two|three|four|five|six|seven|eight|nine|ten) "
    r"[\w-]+ requirements|rule \d+|rules \d+(?:[-\u2013]\d+)?(?: and \d+)?)\b",
    re.I,
)
COMPOUND_HEADING_RE = re.compile(r"\b(and|never|not|but)\b", re.I)
LITERAL_RE = re.compile(r"`([^`]+)`|\b(\d+(?:\.\d+)?)\b")
POSITIONAL_CITATION_RE = re.compile(r"\bscenarios?\s+\d+(?:\s*[-\u2013,]\s*\d+)?\b", re.I)
# a run of N backticks closes only on the same run, so `` ` `` (a literal backtick) is one span
CODE_SPAN_RE = re.compile(r"(`+)(?:(?!\1)[^\n])*?\1")
WORD_RE = re.compile(r"[A-Za-z0-9_`'\-/]+|[.,;:()\[\]{}\"]")


# --------------------------------------------------------------------------------------------
# Parsing — mirrors OpenSpec's requirement-text.js for the body measure, and reads raw lines for
# conservation (so metadata laundering cannot hide prose from the comparison).
# --------------------------------------------------------------------------------------------


def fence_mask(lines: list[str]) -> list[bool]:
    mask: list[bool] = []
    inside = False
    for line in lines:
        if FENCE_RE.match(line):
            inside = not inside
            mask.append(True)
            continue
        mask.append(inside)
    return mask


def requirement_body(body_lines: list[str]) -> str:
    """OpenSpec's ``extractRequirementBody``: non-fenced, non-blank, trimmed lines up to the first
    header, ``\\n``-joined; ``**Label**:`` lines kept only when nothing else remains."""
    mask = fence_mask(body_lines)
    captured: list[str] = []
    metadata: list[str] = []
    for line, fenced in zip(body_lines, mask, strict=True):
        if fenced:
            continue
        if HEADER_RE.match(line):
            break
        trimmed = line.strip()
        if not trimmed:
            continue
        if METADATA_RE.match(trimmed):
            metadata.append(trimmed)
            continue
        captured.append(trimmed)
    return "\n".join(captured) if captured else "\n".join(metadata)


def body_length(body: str) -> int:
    return len(body)


@dataclass
class Scenario:
    name: str
    body: str  # normalised


@dataclass
class Requirement:
    heading: str
    raw_body_lines: list[str]  # up to the first scenario header (fences included)
    scenarios: list[Scenario]
    fences: list[str]  # normalised fenced blocks in body order
    units: list[str]  # ordered prose units (normalised)
    lead_ins: dict[int, str]  # unit index -> governing lead-in (normalised)
    table_headers: set[str]  # header + delimiter rows of each table (structure, duplicable)
    metadata_lines: list[str]
    order: int


@dataclass
class SpecFile:
    key: str  # "demo" or "changes/<change>/<id>"
    capability: str
    purpose: str
    requirements: list[Requirement]
    path: Path


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_units(paragraph_lines: list[str]) -> list[str]:
    """Sentence units: end at a sentence-final ``.``/``!``/``?`` outside code spans; a list item is
    always its own unit (it may lack terminal punctuation)."""
    units: list[str] = []
    buf: list[str] = []
    for line in paragraph_lines:
        if LIST_ITEM_RE.match(line.strip()) or TABLE_ROW_RE.match(line.strip()):
            if buf:
                units.extend(_sentences(" ".join(buf)))
                buf = []
            units.append(_norm(line))
            continue
        buf.append(line.strip())
    if buf:
        units.extend(_sentences(" ".join(buf)))
    return [u for u in units if u]


def _sentences(text: str) -> list[str]:
    text = _norm(text)
    if not text:
        return []
    # Protect code spans from the sentence splitter.
    spans: list[str] = []

    def _stash(m: re.Match[str]) -> str:
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    protected = CODE_SPAN_RE.sub(_stash, text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z`*(\[\"'\x00])", protected)
    out: list[str] = []
    for part in parts:
        restored = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], part)
        if restored.strip():
            out.append(restored.strip())
    return out


def _is_lead_in(unit: str) -> bool:
    return unit.endswith(":") or bool(LEAD_IN_WORDS.search(unit) and not unit.endswith("."))


def _parse_requirement(heading: str, lines: list[str], order: int) -> Requirement:
    mask = fence_mask(lines)
    # body = lines before the first non-fenced level-4 (or any) header
    body_end = len(lines)
    for i, (line, fenced) in enumerate(zip(lines, mask, strict=True)):
        if not fenced and HEADER_RE.match(line):
            body_end = i
            break
    body_lines = lines[:body_end]
    body_mask = mask[:body_end]

    fences: list[str] = []
    prose: list[str] = []
    metadata: list[str] = []
    fence_buf: list[str] | None = None
    for line, fenced in zip(body_lines, body_mask, strict=True):
        if FENCE_RE.match(line):
            if fence_buf is None:
                fence_buf = []
            else:
                fences.append("\n".join(s.strip() for s in fence_buf))
                fence_buf = None
                prose.append("\x01FENCE\x01")
            continue
        if fenced and fence_buf is not None:
            fence_buf.append(line)
            continue
        trimmed = line.strip()
        if METADATA_RE.match(trimmed):
            metadata.append(trimmed)
            prose.append(trimmed)  # conserved as prose regardless of how the tool treats it
            continue
        prose.append(line)

    # paragraphs split on blank lines; fence markers separate too
    units: list[str] = []
    lead_ins: dict[int, str] = {}
    table_headers: set[str] = set()
    current_lead: str | None = None
    lead_block_open = False  # the lead-in's own paragraph, or the list/table right after it
    para: list[str] = []

    def _starts_block(line: str) -> bool:
        t = line.strip()
        return bool(LIST_ITEM_RE.match(t) or TABLE_ROW_RE.match(t))

    def _flush() -> None:
        nonlocal current_lead, para, lead_block_open
        for unit in _split_units(para):
            idx = len(units)
            units.append(unit)
            if TABLE_DELIM_RE.match(unit) and idx > 0 and TABLE_ROW_RE.match(units[idx - 1]):
                # a table's header row and delimiter row are structure, not an obligation:
                # conserved, but a fragment that keeps some rows repeats them (like a lead-in)
                table_headers.update((units[idx - 1], unit))
                lead_ins.pop(idx - 1, None)
                continue
            if _is_lead_in(unit):
                current_lead = unit
                lead_block_open = True
            elif current_lead is not None and lead_block_open:
                lead_ins[idx] = current_lead
        para = []

    for pos, line in enumerate(prose):
        if line == "\x01FENCE\x01":
            _flush()
            units.append("\x01FENCE\x01")
            continue
        if not line.strip():
            _flush()
            # a blank line ends the lead-in's scope unless a list or table follows it directly
            following = next((ln for ln in prose[pos + 1 :] if ln.strip()), "")
            lead_block_open = lead_block_open and _starts_block(following)
            continue
        if _starts_block(line) and para and not _starts_block(para[-1]):
            # list/table starts: the preceding sentence(s) may be the lead-in; flush them first
            _flush()
        para.append(line)
    _flush()

    # scenarios
    scenarios: list[Scenario] = []
    i = body_end
    while i < len(lines):
        line = lines[i]
        if not mask[i] and SCENARIO_RE.match(line) and line.startswith("####"):
            name = SCENARIO_RE.match(line).group(1)  # type: ignore[union-attr]
            j = i + 1
            buf: list[str] = []
            while j < len(lines) and not (not mask[j] and re.match(r"^#{1,4}\s", lines[j])):
                buf.append(lines[j])
                j += 1
            body = _norm(" ".join(s.strip() for s in buf))
            if body:
                scenarios.append(Scenario(name=_norm(name), body=body))
            i = j
            continue
        i += 1

    return Requirement(
        heading=_norm(heading),
        raw_body_lines=body_lines,
        scenarios=scenarios,
        fences=fences,
        units=units,
        lead_ins=lead_ins,
        table_headers=table_headers,
        metadata_lines=metadata,
        order=order,
    )


def parse_spec(path: Path, key: str, capability: str) -> SpecFile:
    lines = path.read_text(encoding="utf-8").split("\n")
    mask = fence_mask(lines)
    purpose = ""
    requirements: list[Requirement] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not mask[i] and line.strip() == "## Purpose":
            j = i + 1
            buf: list[str] = []
            while j < n and not (not mask[j] and re.match(r"^#{1,3}\s", lines[j])):
                buf.append(lines[j])
                j += 1
            purpose = _norm(" ".join(buf))
            i = j
            continue
        m = REQ_RE.match(line) if not mask[i] else None
        if m:
            j = i + 1
            while j < n and not (not mask[j] and re.match(r"^#{1,3}\s", lines[j])):
                j += 1
            requirements.append(_parse_requirement(m.group(1), lines[i + 1 : j], len(requirements)))
            i = j
            continue
        i += 1
    return SpecFile(
        key=key, capability=capability, purpose=purpose, requirements=requirements, path=path
    )


def load_tree(root: Path) -> dict[str, SpecFile]:
    """``root`` is an ``openspec/`` directory."""
    out: dict[str, SpecFile] = {}
    for path in sorted((root / "specs").glob("*/spec.md")):
        cap = path.parent.name
        out[cap] = parse_spec(path, cap, cap)
    changes = root / "changes"
    if changes.is_dir():
        for path in sorted(changes.glob("*/specs/*/spec.md")):
            if path.parts[-4] == "archive" or "archive" in path.relative_to(changes).parts[:1]:
                continue
            change = path.relative_to(changes).parts[0]
            cap = path.parent.name
            key = f"changes/{change}/{cap}"
            out[key] = parse_spec(path, key, cap)
    return out


# --------------------------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------------------------

EXCEPTION_KINDS = (
    "deleted",
    "split-sentence",
    "inherit-shall",
    "modalise",
    "reference-expansion",
    "context-restated",
    "list-split",
    "fence-rehome",
    "scenario-rehome",
    "moved-body-text",
    "test-sourced",
    "restates-shall",
)


@dataclass
class SplitException:
    kind: str
    data: dict
    consumed: bool = False

    def addr(self) -> tuple[str, str, int] | None:
        if "heading" in self.data and "ordinal" in self.data:
            return (self.data["spec"], _norm(self.data["heading"]), int(self.data["ordinal"]))
        return None


def load_exceptions(root: Path) -> list[SplitException]:
    path = root / ".split-exceptions.toml"
    if not path.is_file():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out: list[SplitException] = []
    for kind in EXCEPTION_KINDS:
        for entry in data.get(kind, []) or []:
            out.append(SplitException(kind=kind, data=entry))
    unknown = sorted(set(data) - set(EXCEPTION_KINDS))
    if unknown:
        raise SystemExit(f"unknown exception kind(s) in {path}: {', '.join(unknown)}")
    return out


# --------------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------------


@dataclass
class Finding:
    level: str  # FAIL | WARN
    code: str
    spec: str
    detail: str


@dataclass
class DriftEntry:
    kind: str
    spec: str
    name: str
    detail: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    drift: list[DriftEntry] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.level == "FAIL" for f in self.findings)

    def fail(self, code: str, spec: str, detail: str) -> None:
        self.findings.append(Finding("FAIL", code, spec, detail))

    def warn(self, code: str, spec: str, detail: str) -> None:
        self.findings.append(Finding("WARN", code, spec, detail))

    def note(self, kind: str, spec: str, name: str, detail: str) -> None:
        self.drift.append(DriftEntry(kind, spec, name, detail))


# --------------------------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------------------------


def _tokens(text: str) -> Counter[str]:
    return Counter(WORD_RE.findall(_norm(text)))


def _fold(name: str) -> str:
    return re.sub(r"\s+", "", name).casefold()


def _core(unit: str) -> str:
    """A unit without its list marker, case or terminal punctuation — what survives a move into a
    scenario's THEN line."""
    text = LIST_ITEM_RE.sub("", _norm(unit), count=1)
    return text.casefold().rstrip(".;:!?").strip()


def _same(a: object, b: object) -> bool:
    sa, sb = _norm(str(a)), _norm(str(b))
    return sa == sb or _core(sa) == _core(sb)


def _stem(word: str) -> str:
    return word.lower()[:5]


def _addressed(base_spec: SpecFile) -> dict[tuple[str, str, int], str]:
    """(spec, heading, ordinal) -> unit text, ordinal 1-based over prose units (fences skipped)."""
    out: dict[tuple[str, str, int], str] = {}
    for req in base_spec.requirements:
        ordinal = 0
        for unit in req.units:
            if unit == "\x01FENCE\x01":
                continue
            ordinal += 1
            out[(base_spec.key, req.heading, ordinal)] = unit
    return out


def _take(
    exceptions: list[SplitException],
    kind: str,
    spec: str,
    *,
    _peek: bool = False,
    **match: object,
) -> SplitException | None:
    """Find (and by default consume) the first unconsumed entry of ``kind`` for ``spec`` whose
    fields match. With ``_peek`` the entry is returned whether or not it was already consumed and
    is left as is, so two passes can see one declaration."""
    for exc in exceptions:
        if exc.kind != kind or exc.data.get("spec") != spec:
            continue
        if not _peek and exc.consumed:
            continue
        if all(_same(exc.data.get(k, ""), v) for k, v in match.items()):
            if not _peek:
                exc.consumed = True
            return exc
    return None


def compare_spec(
    base: SpecFile,
    head: SpecFile,
    exceptions: list[SplitException],
    report: Report,
    *,
    living_headings_for_capability: set[str],
    collected_nodeids: set[str] | None,
    purpose_rewritten: set[str],
) -> None:
    spec = head.key

    # ---- Purpose
    if base.purpose != head.purpose and base.capability not in purpose_rewritten:
        report.fail("purpose-changed", spec, f"Purpose changed without --purpose-rewritten {spec}")

    # ---- Units (all prose, body plus scenario text)
    base_units = [u for r in base.requirements for u in r.units if u != "\x01FENCE\x01"]
    head_units = [u for r in head.requirements for u in r.units if u != "\x01FENCE\x01"]
    base_count = Counter(base_units)
    head_count = Counter(head_units)
    head_scenario_text = " ".join(s.body for r in head.requirements for s in r.scenarios)
    base_scenario_text = " ".join(s.body for r in base.requirements for s in r.scenarios)

    addressed = _addressed(base)
    addr_by_text: dict[str, list[tuple[str, str, int]]] = {}
    for key, text in addressed.items():
        addr_by_text.setdefault(text, []).append(key)

    lost = base_count - head_count
    added = head_count - base_count
    restated_leads = {
        _norm(str(e.data.get("new", "")))
        for e in exceptions
        if e.kind == "context-restated" and e.data.get("spec") == spec
    }

    # consume exceptions that explain a lost unit
    for unit, n in list(lost.items()):
        for _ in range(n):
            handled = False
            for addr in addr_by_text.get(unit, []):
                _, heading, ordinal = addr
                exc = _take(
                    exceptions, "deleted", spec, heading=heading, ordinal=ordinal, text=unit
                ) or _take(exceptions, "deleted", spec, heading=heading, ordinal=ordinal)
                if exc is not None:
                    report.note("deleted", spec, heading, f"[{ordinal}] {unit}")
                    handled = True
                    break
                exc = _take(exceptions, "split-sentence", spec, heading=heading, ordinal=ordinal)
                if exc is not None:
                    news = [_norm(s) for s in exc.data.get("new", [])]
                    allowed = Counter(exc.data.get("added_tokens", []))
                    for s in news:
                        if s in added:
                            added[s] -= 1
                            if added[s] <= 0:
                                del added[s]
                        else:
                            report.fail(
                                "split-sentence-new-missing",
                                spec,
                                f"declared fragment not found in head: {s}",
                            )
                    old_tok = _tokens(exc.data.get("old", unit))
                    new_tok = Counter()
                    for s in news:
                        new_tok += _tokens(s)
                    drift = (new_tok - old_tok) - allowed
                    missing = old_tok - new_tok
                    # connective words may be dropped by a fission (and/, /;) — nothing else
                    missing -= Counter(
                        {"and": missing["and"], ",": missing[","], ";": missing[";"]}
                    )
                    polarity = {"not", "never", "only", "no", "unless"}
                    if drift or missing or (allowed & Counter(polarity)):
                        report.fail(
                            "split-sentence-token-drift",
                            spec,
                            f"[{heading} #{ordinal}] added={dict(drift)} lost={dict(missing)}",
                        )
                    for s in news:
                        if not KEYWORD_RE.search(s):
                            report.fail(
                                "split-sentence-no-shall", spec, f"fragment lacks SHALL/MUST: {s}"
                            )
                    report.note("split-sentence", spec, heading, f"[{ordinal}] {unit} -> {news}")
                    handled = True
                    break
                exc = _take(exceptions, "inherit-shall", spec, heading=heading, ordinal=ordinal)
                if exc is not None:
                    new = _norm(exc.data.get("new", ""))
                    if new in added:
                        added[new] -= 1
                        if added[new] <= 0:
                            del added[new]
                    else:
                        report.fail(
                            "inherit-shall-new-missing", spec, f"declared unit not in head: {new}"
                        )
                    extra = _tokens(new) - _tokens(unit)
                    lost_tok = _tokens(unit) - _tokens(new)
                    extra_words = Counter(
                        {k: v for k, v in extra.items() if k not in ("SHALL", "MUST")}
                    )
                    # only the modal plus (optionally) a subject noun phrase of <= 3 words and "be"
                    if sum(extra_words.values()) > 4 or lost_tok - Counter({"is": 1, "are": 1}):
                        report.fail(
                            "inherit-shall-token-drift",
                            spec,
                            f"[{heading} #{ordinal}] added={dict(extra)} lost={dict(lost_tok)}",
                        )
                    report.note("inherit-shall", spec, heading, f"[{ordinal}] {unit} -> {new}")
                    handled = True
                    break
                exc = _take(exceptions, "modalise", spec, heading=heading, ordinal=ordinal)
                if exc is not None:
                    new = _norm(exc.data.get("new", ""))
                    if new in added:
                        added[new] -= 1
                        if added[new] <= 0:
                            del added[new]
                    else:
                        report.fail(
                            "modalise-new-missing", spec, f"declared unit not in head: {new}"
                        )
                    verb = exc.data.get("verb") or []
                    old_tok = _tokens(unit)
                    new_tok = _tokens(new)
                    gained = new_tok - old_tok
                    lost_tok = old_tok - new_tok
                    modal = Counter({m: 1 for m in ("SHALL", "MUST") if gained.get(m)})
                    expected_gain = modal + (Counter({verb[1]: 1}) if len(verb) == 2 else Counter())
                    expected_loss = Counter({verb[0]: 1}) if len(verb) == 2 else Counter()
                    if (
                        sum(modal.values()) != 1
                        or gained != expected_gain
                        or lost_tok != expected_loss
                        or not KEYWORD_RE.search(new)
                    ):
                        report.fail(
                            "modalise-token-drift",
                            spec,
                            f"[{heading} #{ordinal}] gained={dict(gained)} lost={dict(lost_tok)}; "
                            "a modalise entry may add one modal and de-inflect one declared "
                            "verb only",
                        )
                    report.note("modalise", spec, heading, f"[{ordinal}] {unit} -> {new}")
                    handled = True
                    break
                exc = _take(
                    exceptions, "reference-expansion", spec, heading=heading, ordinal=ordinal
                )
                if exc is not None:
                    new = _norm(exc.data.get("new", ""))
                    if new in added:
                        added[new] -= 1
                        if added[new] <= 0:
                            del added[new]
                    else:
                        report.fail(
                            "reference-expansion-new-missing",
                            spec,
                            f"declared unit not in head: {new}",
                        )
                    report.note(
                        "reference-expansion", spec, heading, f"[{ordinal}] {unit} -> {new}"
                    )
                    handled = True
                    break
                exc = _take(exceptions, "context-restated", spec, heading=heading, ordinal=ordinal)
                if exc is not None:
                    new = _norm(exc.data.get("new", ""))
                    if new in added:
                        added[new] -= 1
                        if added[new] <= 0:
                            del added[new]
                    report.note("context-restated", spec, heading, f"[{ordinal}] {unit} -> {new}")
                    handled = True
                    break
            if not handled:
                # moved into a scenario?
                core = _core(unit)
                in_head_sc = bool(core) and core in head_scenario_text.casefold()
                in_base_sc = bool(core) and core in base_scenario_text.casefold()
                if in_head_sc and not in_base_sc:
                    moved = _take(exceptions, "moved-body-text", spec, text=unit)
                    governed = any(
                        idx in r.lead_ins
                        for r in base.requirements
                        for idx, u in enumerate(r.units)
                        if u == unit
                    )
                    is_list_item = bool(LIST_ITEM_RE.match(unit) or TABLE_ROW_RE.match(unit))
                    if KEYWORD_RE.search(unit) or (is_list_item and governed):
                        report.fail(
                            "inherited-normative-moved",
                            spec,
                            f"normative unit moved into a scenario: {unit}",
                        )
                    elif moved is None:
                        report.fail(
                            "unit-moved-undeclared",
                            spec,
                            "body text moved into a scenario without a moved-body-text entry: "
                            f"{unit}",
                        )
                    else:
                        report.note("moved-body-text", spec, moved.data.get("scenario", "?"), unit)
                else:
                    where = addr_by_text.get(unit, [("?", "?", 0)])[0]
                    report.fail("unit-lost", spec, f"[{where[1]} #{where[2]}] {unit}")

    for unit, n in added.items():
        for _ in range(n):
            if unit in base_scenario_text and unit not in head_scenario_text:
                report.note("scenario-text-promoted", spec, "?", unit)
                continue
            # a duplicated lead-in is the expected repair, not an addition; so is a lead-in
            # restated through a context-restated entry (the first copy consumes the entry,
            # every later copy is a duplicate like a verbatim one)
            if (
                any(unit in r.lead_ins.values() for r in base.requirements)
                or unit in restated_leads
            ):
                report.note("lead-in-duplicated", spec, "?", unit)
                continue
            if any(unit in r.table_headers for r in base.requirements):
                report.note("table-header-duplicated", spec, "?", unit)
                continue
            report.fail("unit-added", spec, unit)

    # ---- Metadata laundering and fences
    base_meta = Counter(m for r in base.requirements for m in r.metadata_lines)
    head_meta = Counter(m for r in head.requirements for m in r.metadata_lines)
    for line in head_meta - base_meta:
        report.fail("metadata-line-introduced", spec, line)

    base_fences = Counter(f for r in base.requirements for f in r.fences)
    head_fences = Counter(f for r in head.requirements for f in r.fences)
    for f in head_fences - base_fences:
        report.fail("fence-added", spec, f[:120])
    for f in base_fences - head_fences:
        report.fail("fence-lost", spec, f[:120])

    # anchors: the prose unit immediately before each fence
    def _anchors(sf: SpecFile) -> Counter[tuple[str, str]]:
        out: Counter[tuple[str, str]] = Counter()
        for r in sf.requirements:
            fi = 0
            prev = ""
            for u in r.units:
                if u == "\x01FENCE\x01":
                    if fi < len(r.fences):
                        out[(r.fences[fi], prev)] += 1
                    fi += 1
                else:
                    prev = u
        return out

    for (fence, anchor), _n in (_anchors(base) - _anchors(head)).items():
        exc = _take(exceptions, "fence-rehome", spec, fence_prefix=fence[:40])
        if exc is None:
            report.fail(
                "fence-moved", spec, f"fence no longer follows '{anchor[:80]}': {fence[:60]}"
            )
        else:
            report.note("fence-rehome", spec, anchor[:60], fence[:60])

    # ---- Scope: lead-ins travel; order preserved
    head_unit_locations: dict[str, list[Requirement]] = {}
    for r in head.requirements:
        for u in r.units:
            if u in r.table_headers:
                continue  # structure shared by every table; it locates nothing
            head_unit_locations.setdefault(u, []).append(r)
    for breq in base.requirements:
        for idx, lead in breq.lead_ins.items():
            unit = breq.units[idx]
            for hreq in head_unit_locations.get(unit, []):
                carried = lead in hreq.units or any(u in restated_leads for u in hreq.units)
                if not carried:
                    exc = _take(
                        exceptions, "context-restated", spec, heading=breq.heading, unit=unit
                    )
                    if exc is None:
                        report.fail(
                            "context-lost",
                            spec,
                            f"'{unit[:80]}' is governed by '{lead}' but its fragment "
                            f"'{hreq.heading}' does not carry it",
                        )
                    else:
                        report.note("context-restated", spec, hreq.heading, lead)

    # order: concatenate head fragments in document order, project onto base's normative units
    head_sequence = [u for r in head.requirements for u in r.units if u != "\x01FENCE\x01"]
    for breq in base.requirements:
        normative = [u for u in breq.units if u != "\x01FENCE\x01" and KEYWORD_RE.search(u)]
        positions: list[int] = []
        for u in normative:
            try:
                positions.append(head_sequence.index(u))
            except ValueError:
                continue  # lost/changed units are reported above
        if positions != sorted(positions):
            report.fail(
                "normative-order-changed",
                spec,
                f"[{breq.heading}] normative order differs after the split",
            )
        has_order_marker = any(ORDER_MARKERS.search(u) for u in breq.units if u != "\x01FENCE\x01")
        frags = {r.heading for u in breq.units for r in head_unit_locations.get(u, [])}
        if has_order_marker and len(frags) > 1:
            exc = _take(exceptions, "list-split", spec, heading=breq.heading)
            if exc is None:
                report.warn(
                    "order-marker-split",
                    spec,
                    f"[{breq.heading}] ordered rules now span {len(frags)} fragments; "
                    "declare list-split naming the rule numbers each fragment carries",
                )
            else:
                report.note("list-split", spec, breq.heading, str(exc.data.get("fragments", "")))

    # ---- Deictic / structural references must resolve in their own body
    split_headings = {
        breq.heading
        for breq in base.requirements
        if len({r.heading for u in breq.units for r in head_unit_locations.get(u, [])}) > 1
    }
    # a requirement whose sentence was rewritten through a consumed entry is split too, even
    # when its surviving units all sit in one fragment (lane D finding 3: the compound-heading
    # check was silent after a fission)
    for exc in exceptions:
        if (
            exc.consumed
            and exc.kind in ("split-sentence", "modalise", "inherit-shall")
            and exc.data.get("spec") == spec
        ):
            split_headings.add(_norm(str(exc.data.get("heading", ""))))
    head_units_by_heading = {r.heading: set(r.units) for r in head.requirements}
    changed_headings = split_headings | {
        breq.heading
        for breq in base.requirements
        if {u for u in breq.units if u != "\x01FENCE\x01"}
        != head_units_by_heading.get(breq.heading, set()) - {"\x01FENCE\x01"}
    }
    for hreq in head.requirements:
        body_text = " ".join(u for u in hreq.units if u != "\x01FENCE\x01")
        has_list = any(LIST_ITEM_RE.match(u) for u in hreq.units if u != "\x01FENCE\x01")
        has_table = any(TABLE_ROW_RE.match(u) for u in hreq.units if u != "\x01FENCE\x01")
        has_fence = bool(hreq.fences)
        for m in DEICTIC_RE.finditer(body_text):
            phrase = m.group(0)
            low = phrase.lower()
            # the originating base requirement: the one whose units contain this unit
            origin = next(
                (
                    b
                    for b in base.requirements
                    for u in hreq.units
                    if u in b.units and u != "\x01FENCE\x01"
                ),
                None,
            )
            if origin is None or origin.heading not in changed_headings:
                continue  # unchanged requirement; reference stood before and stands now
            resolved = False
            if low.startswith(("the list", "the table", "the following", "these rules")):
                resolved = has_list or has_fence or has_table
            elif low.startswith(("rule", "rules")):
                resolved = bool(re.search(r"(?im)^\s*\d+[.)]\s", "\n".join(hreq.units))) or bool(
                    re.search(r"rule \d+", hreq.heading, re.I)
                )
            # self/structural references never resolve once the requirement is split
            exc = _take(
                exceptions, "reference-expansion", spec, heading=origin.heading, phrase=phrase
            )
            if not resolved and exc is None:
                report.fail(
                    "orphaned-reference",
                    spec,
                    f"[{hreq.heading}] '{phrase}' no longer resolves inside its own body",
                )

    # ---- Scenarios
    base_sc = Counter((s.name, s.body) for r in base.requirements for s in r.scenarios)
    head_sc = Counter((s.name, s.body) for r in head.requirements for s in r.scenarios)
    for name, body in base_sc - head_sc:
        report.fail("scenario-lost", spec, f"'{name}': {body[:80]}")
    base_home = {s.name: r.heading for r in base.requirements for s in r.scenarios}
    head_home = {s.name: r.heading for r in head.requirements for s in r.scenarios}
    for name, body in head_sc - base_sc:
        host = head_home.get(name, "?")
        host_req = next((r for r in head.requirements if r.heading == host), None)
        host_body = " ".join(u for u in host_req.units) if host_req else ""
        moved = _take(exceptions, "moved-body-text", spec, scenario=name) or _take(
            exceptions, "moved-body-text", spec, _peek=True, scenario=name
        )
        if moved is not None:
            # the moved prose must be absent from every head body
            text = _norm(str(moved.data.get("text", "")))
            if text and any(text in " ".join(r.units) for r in head.requirements):
                report.fail("moved-body-text-still-in-body", spec, text)
            report.note("moved-body-text", spec, name, text)
            continue
        tested = _take(exceptions, "test-sourced", spec, scenario=name)
        if tested is not None:
            nodeid = str(tested.data.get("test", ""))
            if collected_nodeids is None:
                report.fail(
                    "test-nodeid-unverified",
                    spec,
                    f"'{name}' cites {nodeid} but no --collected-nodeids file was given",
                )
            elif nodeid not in collected_nodeids:
                report.fail(
                    "test-nodeid-unresolved", spec, f"'{name}' cites {nodeid}, not collected"
                )
            else:
                report.note("test-sourced", spec, name, nodeid)
            continue
        restated = _take(exceptions, "restates-shall", spec, scenario=name)
        if restated is not None:
            target = _norm(str(restated.data.get("restates", "")))
            if target and target not in host_body:
                report.fail(
                    "restates-shall-target-missing",
                    spec,
                    f"'{name}' restates a unit its host body does not hold: {target[:80]}",
                )
            for lit in LITERAL_RE.finditer(body):
                token = lit.group(1) or lit.group(2)
                if token and token not in host_body and token not in host:
                    report.fail(
                        "restates-shall-adds-literal",
                        spec,
                        f"'{name}' introduces `{token}` which its host body lacks",
                    )
            if not restated.data.get("searched_tests"):
                report.fail(
                    "restates-shall-no-search",
                    spec,
                    f"'{name}' lacks a recorded searched_tests note",
                )
            report.note("restates-shall", spec, name, target[:80])
            continue
        rehome = _take(exceptions, "scenario-rehome", spec, scenario=name)
        if rehome is not None and name in base_home:
            report.note("scenario-rehome", spec, name, f"{base_home[name]} -> {host}")
            continue
        if name in base_home and (name, body) not in base_sc:
            report.fail("scenario-body-changed", spec, f"'{name}' body differs from base")
            continue
        report.fail(
            "scenario-added-unsourced", spec, f"'{name}' under '{host}' has no source entry"
        )
    names = Counter(s.name for r in head.requirements for s in r.scenarios)
    for name, n in names.items():
        if n > 1:
            report.fail("scenario-name-duplicate", spec, f"'{name}' appears {n} times")
    # A scenario whose (name, body) is unchanged but whose host moved. Within the fragments of
    # its own original requirement that is routine (a drift note). Under a *different* original
    # requirement it changes what the scenario claims to prove, so it must be declared.
    origin_of_head_req: dict[str, str | None] = {}
    base_heading_set = {b.heading for b in base.requirements}
    # a fragment made only of rewritten units (split-sentence / inherit-shall /
    # reference-expansion output) maps back through the entry that produced them
    rewritten_origin: dict[str, str] = {}
    for exc in exceptions:
        if exc.kind in (
            "split-sentence",
            "inherit-shall",
            "modalise",
            "reference-expansion",
            "context-restated",
        ):
            if exc.data.get("spec") != spec:
                continue
            news = exc.data.get("new", [])
            for s in news if isinstance(news, list) else [news]:
                rewritten_origin[_norm(str(s))] = _norm(str(exc.data.get("heading", "")))
    for hreq in head.requirements:
        origin = next(
            (
                b.heading
                for b in base.requirements
                for u in hreq.units
                if u != "\x01FENCE\x01" and u in b.units
            ),
            None,
        )
        if origin is None:
            origin = next((rewritten_origin[u] for u in hreq.units if u in rewritten_origin), None)
        if origin is None and hreq.heading in base_heading_set:
            origin = hreq.heading
        origin_of_head_req[hreq.heading] = origin
    for name, home in head_home.items():
        if (
            name in base_home
            and base_home[name] != home
            and (name, _sc_body(head, name)) in base_sc
        ):
            origin = origin_of_head_req.get(home)
            if origin == base_home[name]:
                report.note("scenario-rehomed", spec, name, f"{base_home[name]} -> {home}")
                continue
            exc = _take(exceptions, "scenario-rehome", spec, scenario=name)
            if exc is None:
                report.fail(
                    "scenario-rehomed-across-requirements",
                    spec,
                    f"'{name}' moved from '{base_home[name]}' to '{home}' (origin "
                    f"'{origin}'); declare a scenario-rehome entry naming the test that "
                    "cites it",
                )
            else:
                report.note(
                    "scenario-rehome",
                    spec,
                    name,
                    f"{base_home[name]} -> {home}; test={exc.data.get('test', '?')}",
                )

    # ---- Headings
    head_headings = Counter(r.heading for r in head.requirements)
    for breq in base.requirements:
        n = head_headings.get(breq.heading, 0)
        if n == 0:
            report.fail("heading-lost", spec, breq.heading)
        elif n > 1:
            report.fail("heading-duplicate", spec, breq.heading)
        else:
            keeper = next(r for r in head.requirements if r.heading == breq.heading)
            if breq.heading in split_headings and COMPOUND_HEADING_RE.search(breq.heading):
                base_words = {
                    w.lower()
                    for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", breq.heading)
                    if w.lower()
                    not in {"and", "never", "not", "but", "the", "with", "from", "that"}
                }
                keeper_stems = {
                    _stem(w) for w in re.findall(r"[A-Za-z][A-Za-z-]+", " ".join(keeper.units))
                }
                missing = sorted(w for w in base_words if _stem(w) not in keeper_stems)
                if missing:
                    report.warn(
                        "compound-heading-split",
                        spec,
                        f"'{breq.heading}' kept on a fragment whose body lacks: "
                        f"{', '.join(missing)}",
                    )
    for heading, n in head_headings.items():
        if n > 1 and heading not in {b.heading for b in base.requirements}:
            report.fail("heading-duplicate", spec, heading)
    base_headings = {b.heading for b in base.requirements}
    new_headings = [h for h in head_headings if h not in base_headings]
    folds = {_fold(h) for h in living_headings_for_capability}
    for h in new_headings:
        if _fold(h) in folds:
            report.fail(
                "archive-name-collision",
                spec,
                f"'{h}' matches a living '{head.capability}' heading case/space-insensitively",
            )

    # ---- Tool rules on every head body
    for hreq in head.requirements:
        body = requirement_body(hreq.raw_body_lines)
        if body_length(body) > MAX_BODY:
            report.fail(
                "tool-body-too-long",
                spec,
                f"'{hreq.heading}' body is {body_length(body)} > {MAX_BODY}",
            )
        if not KEYWORD_RE.search(body):
            report.fail("tool-no-shall", spec, f"'{hreq.heading}' body has no SHALL/MUST")
        if not hreq.scenarios:
            report.fail("tool-no-scenario", spec, f"'{hreq.heading}' has no scenario")


def _sc_body(sf: SpecFile, name: str) -> str:
    for r in sf.requirements:
        for s in r.scenarios:
            if s.name == name:
                return s.body
    return ""


def check_trees(
    *,
    base_root: Path,
    head_root: Path,
    specs: set[str] | None = None,
    collected_nodeids: Path | None = None,
    purpose_rewritten: set[str] | None = None,
    citation_roots: list[Path] | None = None,
) -> Report:
    report = Report()
    base = load_tree(base_root)
    head = load_tree(head_root)
    exceptions = load_exceptions(head_root)
    nodeids: set[str] | None = None
    if collected_nodeids is not None:
        nodeids = {
            line.strip()
            for line in collected_nodeids.read_text(encoding="utf-8").splitlines()
            if "::" in line
        }
    keys = sorted(set(base) | set(head))
    if specs:
        keys = [k for k in keys if k in specs or k.split("/")[-1] in specs]
    for key in keys:
        if key not in head:
            report.fail("spec-file-removed", key, "present at base, missing in head")
            continue
        if key not in base:
            report.fail("spec-file-added", key, "absent at base; a split never creates a spec file")
            continue
        cap = head[key].capability
        living = set()
        if cap in head and key != cap:
            living = {r.heading for r in head[cap].requirements}
        compare_spec(
            base[key],
            head[key],
            exceptions,
            report,
            living_headings_for_capability=living,
            collected_nodeids=nodeids,
            purpose_rewritten=purpose_rewritten or set(),
        )
    for exc in exceptions:
        if not exc.consumed:
            report.fail(
                "exception-unused",
                str(exc.data.get("spec", "?")),
                f"{exc.kind} entry never consumed: "
                f"{json.dumps(exc.data, ensure_ascii=False)[:160]}",
            )
    # positional citations in code/tests to a split file
    if citation_roots:
        split_caps = {
            k.split("/")[-1]
            for k in keys
            if k in base and k in head and len(head[k].requirements) > len(base[k].requirements)
        }
        for root in citation_roots:
            for path in root.rglob("*.py"):
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for m in POSITIONAL_CITATION_RE.finditer(text):
                    window = text[max(0, m.start() - 160) : m.end() + 40]
                    hit = next(
                        (c for c in split_caps if c in window and "spec" in window.lower()), None
                    )
                    if hit:
                        line_no = text.count("\n", 0, m.start()) + 1
                        report.fail(
                            "positional-citation",
                            hit,
                            f"{path}:{line_no} cites '{m.group(0)}' of a split spec by position",
                        )
    return report


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def _materialise_base(repo: Path, rev: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="openspec-base-"))
    archive = subprocess.run(
        ["git", "archive", rev, "openspec"], cwd=repo, capture_output=True, check=True, timeout=120
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(tmp)], input=archive, check=True, timeout=120)
    return tmp / "openspec"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", help="git revision holding the pre-split openspec/ tree")
    ap.add_argument(
        "--base-dir", type=Path, help="pre-split openspec/ directory (instead of --base)"
    )
    ap.add_argument(
        "--head-dir", type=Path, help="post-split openspec/ directory (default: ./openspec)"
    )
    ap.add_argument("--spec", action="append", default=[], help="limit to these spec ids")
    ap.add_argument(
        "--purpose-rewritten", action="append", default=[], help="spec ids whose Purpose changed"
    )
    ap.add_argument(
        "--collected-nodeids", type=Path, help="file of pytest nodeids (collect-only -q output)"
    )
    ap.add_argument(
        "--citation-root", type=Path, action="append", default=[], help="code roots to grep"
    )
    ap.add_argument("--json", type=Path, help="write the report as JSON here")
    ap.add_argument("--drift", type=Path, help="write the drift report (markdown) here")
    args = ap.parse_args(argv)

    repo = Path.cwd()
    head_root = args.head_dir or (repo / "openspec")
    if args.base_dir:
        base_root = args.base_dir
    elif args.base:
        base_root = _materialise_base(repo, args.base)
    else:
        ap.error("one of --base or --base-dir is required")
        return 2

    report = check_trees(
        base_root=base_root,
        head_root=head_root,
        specs=set(args.spec) or None,
        collected_nodeids=args.collected_nodeids,
        purpose_rewritten=set(args.purpose_rewritten),
        citation_roots=args.citation_root or None,
    )
    for f in report.findings:
        print(f"{f.level} {f.code} [{f.spec}] {f.detail}")
    fails = sum(1 for f in report.findings if f.level == "FAIL")
    warns = sum(1 for f in report.findings if f.level == "WARN")
    print(
        f"{'OK' if report.ok else 'FAILED'}: {fails} fail, {warns} warn, "
        f"{len(report.drift)} drift entries"
    )
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "ok": report.ok,
                    "findings": [asdict(f) for f in report.findings],
                    "drift": [asdict(d) for d in report.drift],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if args.drift:
        lines = [
            "# Split drift report",
            "",
            "Read every entry; the checker could not judge these.",
            "",
        ]
        for d in report.drift:
            lines.append(f"- **{d.kind}** `{d.spec}` — {d.name}: {d.detail}")
        args.drift.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
