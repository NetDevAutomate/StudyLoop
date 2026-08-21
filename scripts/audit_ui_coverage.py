#!/usr/bin/env python3
"""Audit how much of the web UI's interactive surface a browser test actually operates.

Why this exists
---------------
``tests/test_e2e_coverage_gate.py`` gates routes, nav views, CLI commands,
multiplexer backends and render classes. It does **not** gate *interactions*, so a
new button, toggle, dropdown or keyboard shortcut ships with nothing failing. This
script supplies the missing measurement:

    for every interactive control in index.html, does a browser test OPERATE it —
    not merely assert that it exists?

The distinction matters. "Asserted on" proves a control rendered; only
"actuated" (clicked / filled / selected / pressed) proves it does anything. Both
are reported separately.

Output
------
``--format table`` (default) prints a per-surface summary plus the un-actuated
backlog. ``--format json`` emits the same data for a gate to consume.

``--fail-over N`` exits non-zero when the number of un-actuated controls exceeds
N, which is how this becomes a ratchet rather than a report nobody reads.

Deliberate limitations, stated so the numbers are not over-trusted
-----------------------------------------------------------------
* Attribution is **positional**: a control belongs to the nearest preceding
  surface marker (nav view / ``<aside>`` / sidebar). Views are sequential
  top-level blocks in ``index.html``, so this is accurate today and would need
  revisiting if the markup were re-nested.
* A control is counted as actuated when its ``data-testid`` or ``id`` appears in
  an actuating call in a browser test. Text- and class-based selectors are NOT
  credited — that is intentional: they are the fragile pattern this audit exists
  to drive out (see docs/handoffs/2026-08-04-web-ui-e2e-coverage-gaps.md §3.3).
  Expect the first run to under-report real coverage; the fix is to add hooks,
  not to loosen the check.
* Controls inside ``<template x-for>`` are counted once (as authored), not once
  per rendered row.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "packages/studyloop/src/studyloop/web/static"
TESTS = REPO / "packages/studyloop/tests"

CONTROL_OPEN_RE = re.compile(r"<(button|input|select|textarea)\b")
HOOK_RE = re.compile(r'\bdata-testid="([\w-]+)"|\bid="([\w-]+)"')

#: A test "operates" a control when it clicks/fills/selects/checks/presses it.
#:
#: Anchored on the hook itself (``#id`` or ``data-testid="…"``) on purpose. An
#: earlier unanchored version allowed any identifier before the actuator, so
#: ``page.locator("#notes-clear-all").click()`` captured ``page`` and the control
#: was scored as merely asserted — reporting 5 actuated controls where 37 were.
_ACTUATORS = r"click|fill|select_option|check|uncheck|press|type|set_input_files|hover|focus"
ACTUATION_RE = re.compile(
    # locator("#hook…").click()  /  locator('[data-testid="hook"]…').fill(…)
    rf"""(?:\#|data-testid=["']?)([\w-]+)[^)\n]{{0,160}}?\)\s*(?:\.\s*first|\.\s*last|\.\s*nth\([^)]*\))?\s*\.\s*(?:{_ACTUATORS})\b"""
    # click("#hook")  /  fill('[data-testid="hook"]', …)
    rf"""|(?:{_ACTUATORS})\(\s*["'][^"']*?(?:\#|data-testid=["']?)([\w-]+)""",
)

#: Modules that drive a browser. Kept as a signature rather than a hardcoded list
#: so a new browser suite is picked up without editing this script.
BROWSER_SIGNATURE = re.compile(r"\.locator\(|wait_for_selector|page\.goto|web_page")


@dataclass
class Surface:
    """One addressable region of the UI (a nav view, a side panel, the chrome)."""

    name: str
    counts: Counter = field(default_factory=Counter)
    hooks: list[str] = field(default_factory=list)
    unhooked: int = 0

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _surface_markers(lines: list[str]) -> list[tuple[int, str]]:
    """Line numbers where a new surface begins.

    Only the sidebar ``<nav>`` counts as chrome: matching ``<header>`` too would
    scatter chrome markers through every view that has its own header, which
    silently mis-attributes half the page (a mistake worth recording — it made an
    earlier version of this audit report the side panels as chrome).
    """
    marks: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if re.search(r'<nav class="sidebar"', line):
            marks.append((i, "chrome:sidebar"))
        if m := re.search(r'<aside class="([\w-]+)', line):
            marks.append((i, f"panel:{m.group(1)}"))
        if (m := re.search(r"nav\.is\('([\w-]+)'\)", line)) and "x-show" in line:
            marks.append((i, f"view:{m.group(1)}"))
    marks.sort()
    return marks


def collect_surfaces(html: str) -> dict[str, Surface]:
    """Attribute every control to a surface, reading whole tags not whole lines.

    Tags are matched on the whole document and sliced forward to their closing
    ``>``, because almost every control in this markup spreads its attributes
    over several lines. An earlier version matched ``<tag[^>]*>`` line by line and
    silently found 66 of 232 controls — a 72% under-count that read as good news.
    """
    lines = html.split("\n")
    marks = _surface_markers(lines)

    # Offset -> line number, so a match position can be attributed to a surface.
    line_starts: list[int] = []
    offset = 0
    for line in lines:
        line_starts.append(offset)
        offset += len(line) + 1

    def line_of(pos: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def surface_at(idx: int) -> str:
        current = "chrome:header"
        for i, name in marks:
            if i > idx:
                break
            current = name
        return current

    surfaces: dict[str, Surface] = {}
    for match in CONTROL_OPEN_RE.finditer(html):
        close = html.find(">", match.end())
        tag = html[match.start() : close + 1 if close != -1 else match.end()]
        name = surface_at(line_of(match.start()))
        surface = surfaces.setdefault(name, Surface(name))
        surface.counts[match.group(1)] += 1
        if hook := HOOK_RE.search(tag):
            surface.hooks.append(hook.group(1) or hook.group(2))
        else:
            surface.unhooked += 1
    return surfaces


def collect_test_usage() -> tuple[set[str], set[str], list[Path]]:
    """Return (actuated hooks, merely-mentioned hooks, browser modules)."""
    modules = [
        p for p in sorted(TESTS.rglob("test_*.py")) if BROWSER_SIGNATURE.search(p.read_text())
    ]
    blob = "\n".join(p.read_text() for p in modules)
    actuated = {a or b for a, b in ACTUATION_RE.findall(blob)}
    mentioned = set(re.findall(r'[#\[]["\']?([\w-]+)', blob)) | set(
        re.findall(r'data-testid=["\']([\w-]+)', blob)
    )
    return actuated, mentioned, modules


def build_report() -> dict:
    html = (STATIC / "index.html").read_text()
    surfaces = collect_surfaces(html)
    actuated, mentioned, modules = collect_test_usage()

    rows, backlog = [], []
    totals = Counter()
    for name in sorted(surfaces):
        surface = surfaces[name]
        hooked_actuated = [h for h in surface.hooks if h in actuated]
        hooked_asserted = [h for h in surface.hooks if h not in actuated and h in mentioned]
        hooked_absent = [h for h in surface.hooks if h not in mentioned]
        rows.append(
            {
                "surface": name,
                "controls": surface.total,
                "by_tag": dict(surface.counts),
                "hooked": len(surface.hooks),
                "unhooked": surface.unhooked,
                "actuated": len(hooked_actuated),
                "asserted_only": len(hooked_asserted),
                "never_referenced": len(hooked_absent),
            }
        )
        totals["controls"] += surface.total
        totals["hooked"] += len(surface.hooks)
        totals["unhooked"] += surface.unhooked
        totals["actuated"] += len(hooked_actuated)
        totals["asserted_only"] += len(hooked_asserted)
        totals["never_referenced"] += len(hooked_absent)
        backlog.extend(
            {"surface": name, "hook": h, "state": state}
            for state, group in (
                ("asserted_only", hooked_asserted),
                ("never_referenced", hooked_absent),
            )
            for h in group
        )

    # An unhooked control cannot be actuated by hook, so it counts as un-actuated.
    un_actuated = totals["controls"] - totals["actuated"]
    return {
        "totals": dict(totals) | {"un_actuated": un_actuated},
        "surfaces": rows,
        "backlog": sorted(backlog, key=lambda r: (r["surface"], r["hook"])),
        "browser_modules": [str(p.relative_to(TESTS)) for p in modules],
    }


def print_table(report: dict) -> None:
    header = f"{'SURFACE':<32}{'ctrl':>5}{'hook':>5}{'act':>5}{'asrt':>5}{'none':>5}{'nohook':>7}"
    print(header)
    print("-" * len(header))
    for row in report["surfaces"]:
        print(
            f"{row['surface']:<32}{row['controls']:>5}{row['hooked']:>5}"
            f"{row['actuated']:>5}{row['asserted_only']:>5}"
            f"{row['never_referenced']:>5}{row['unhooked']:>7}"
        )
    t = report["totals"]
    print("-" * len(header))
    print(
        f"{'TOTAL':<32}{t['controls']:>5}{t['hooked']:>5}{t['actuated']:>5}"
        f"{t['asserted_only']:>5}{t['never_referenced']:>5}{t['unhooked']:>7}"
    )
    print()
    print(f"browser-driving test modules: {len(report['browser_modules'])}")
    print(
        f"controls NOT actuated by any browser test: {t['un_actuated']} "
        f"of {t['controls']} ({t['un_actuated'] * 100 // max(t['controls'], 1)}%)"
    )
    print()
    print(
        "legend: ctrl=controls  hook=has data-testid/id  act=actuated  "
        "asrt=asserted only  none=hook never referenced  nohook=no stable hook"
    )
    if report["backlog"]:
        print()
        print("=== hooks that exist but are never actuated ===")
        for item in report["backlog"]:
            print(f"  {item['surface']:<30} {item['hook']:<34} {item['state']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--format", choices=("table", "json"), default="table")
    parser.add_argument(
        "--fail-over",
        type=int,
        default=None,
        metavar="N",
        help="exit 1 when more than N controls are un-actuated (ratchet mode)",
    )
    args = parser.parse_args()

    report = build_report()
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print_table(report)

    if args.fail_over is not None:
        un_actuated = report["totals"]["un_actuated"]
        if un_actuated > args.fail_over:
            print(
                f"\nFAIL: {un_actuated} un-actuated controls exceeds the agreed "
                f"ceiling of {args.fail_over}. Either add a workflow that operates "
                f"the new control, or raise the ceiling deliberately and say why.",
                file=sys.stderr,
            )
            return 1
        print(f"\nOK: {un_actuated} un-actuated controls, ceiling {args.fail_over}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
