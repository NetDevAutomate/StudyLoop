"""R-60 guard: no public page advertises the removed 90-day heatmap.

`_buildHeatmap()`'s own comment said it was a placeholder: it emitted
`count: 0, level: 'level-0'` for all 90 days with no API call ever fired,
and the CSS classes a populated cell would need (`.l1`-`.l4`) were never
emitted. For a product whose docs say the heatmap "shows activity, not a
moral score", a permanently empty grid was a "nothing counts" hazard.
Removed outright (components.js, index.html, style.css); this pins the two
doc bullets staying gone.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_cli_reference_does_not_advertise_a_heatmap() -> None:
    text = (REPO_ROOT / "docs" / "cli-reference.md").read_text(encoding="utf-8")
    assert "heatmap" not in text.lower()


def test_web_ui_guide_does_not_advertise_a_heatmap() -> None:
    text = (REPO_ROOT / "docs" / "web-ui-guide.md").read_text(encoding="utf-8")
    assert "heatmap" not in text.lower()
