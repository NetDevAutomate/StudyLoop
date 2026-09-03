"""R-33 guard: docs/tui-guide.md's break table must match break_logic.py.

The doc previously said Medium (4-7) = 20/45/90 and High (8-10) = 25/50/120;
the code's `THRESHOLDS` (and `energy_band`'s own band boundaries) say
Medium (4-6) = 20/40/75 and High (7-10) = 25/50/90 -- three numeric
mismatches plus both band boundaries. Rather than re-typing the table by
hand a second time (how it drifted the first time), this parses the
Markdown table straight out of the doc and compares every cell against the
live ``THRESHOLDS``/``energy_band`` values.
"""

from __future__ import annotations

import re
from pathlib import Path

from studyloop.logic.break_logic import THRESHOLDS, energy_band

REPO_ROOT = Path(__file__).resolve().parents[3]
TUI_GUIDE = REPO_ROOT / "docs" / "tui-guide.md"

#: "Low (1-3) | 15 min | 30 min | 60 min" -> ("Low", 1, 3, 15, 30, 60)
_ROW_RE = re.compile(
    r"\|\s*(\w+)\s*\((\d+)-(\d+)\)\s*\|\s*(\d+)\s*min\s*\|\s*(\d+)\s*min\s*\|\s*(\d+)\s*min\s*\|"
)


def _parse_break_table() -> list[tuple[str, int, int, int, int, int]]:
    rows = []
    for line in TUI_GUIDE.read_text(encoding="utf-8").splitlines():
        match = _ROW_RE.match(line.strip())
        if match:
            label, lo, hi, micro, short, long_ = match.groups()
            rows.append((label, int(lo), int(hi), int(micro), int(short), int(long_)))
    return rows


def test_break_table_parses_to_exactly_three_rows() -> None:
    """Sanity check the regex actually found the table, not zero rows."""
    rows = _parse_break_table()
    assert len(rows) == 3, f"expected 3 energy-band rows in {TUI_GUIDE}, parsed {rows}"


def test_break_table_bands_and_minutes_match_break_logic() -> None:
    band_by_label = {"Low": "low", "Medium": "medium", "High": "high"}
    rows = _parse_break_table()
    problems = []
    for label, lo, hi, doc_micro, doc_short, doc_long in rows:
        band = band_by_label[label]
        thresholds = THRESHOLDS[band]
        doc_triple = (doc_micro, doc_short, doc_long)
        code_triple = (thresholds.micro, thresholds.short, thresholds.long)
        if doc_triple != code_triple:
            problems.append(
                f"{label}: doc says {doc_micro}/{doc_short}/{doc_long}, "
                f"code says {thresholds.micro}/{thresholds.short}/{thresholds.long}"
            )
        # Every energy score claimed to be in [lo, hi] must actually map to
        # this band via the real energy_band() function -- catches a band
        # boundary drift (the doc said Medium covered up to 7; the code's
        # energy_band() puts 7 in "high").
        for energy in range(lo, hi + 1):
            actual_band = energy_band(energy)
            if actual_band != band:
                problems.append(
                    f"{label}: doc claims energy {energy} is in range {lo}-{hi}, "
                    f"but energy_band({energy}) returns {actual_band!r}"
                )
    assert not problems, "\n".join(problems)
