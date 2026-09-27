"""The header's controls read as one row of labelled fields.

Reported 2026-09-27 with a screenshot of the header: the voice-engine badge
("System voices") rendered as large bold text between the voice and theme
pickers, and those two pickers had no visible label while Font and Size did.

Cause: the badge's classes (``tts-engine-badge`` plus ``pending``/``ok``/
``degraded``, assigned by ``ttsEngineClass`` in components.js) had no CSS rule
at all from the commit that added the badge (de7e870b), so the span inherited
the header's text styles. It is the same unbacked-class slip the
``.header-field`` comment in style.css already records, which is why the first
test reads every state the script can assign instead of naming one selector.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "studyloop" / "web" / "static"


class _HeaderFields(HTMLParser):
    """Collect the header's ``.header-field`` groups: label text, pickers, badge."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.field_depth: int | None = None
        self.label_depth: int | None = None
        self.fields: list[dict] = []
        self.loose_selects: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        attr = {key: value or "" for key, value in attrs}
        classes = attr.get("class", "").split()
        if "header-field" in classes and self.field_depth is None:
            self.field_depth = self.depth
            self.fields.append({"label": "", "selects": [], "badge": False})
        elif self.field_depth is not None and "header-field-label" in classes:
            self.label_depth = self.depth
        if tag == "select":
            name = attr.get("id") or attr.get("title", "")
            if self.field_depth is None:
                self.loose_selects.append(name)
            else:
                self.fields[-1]["selects"].append(name)
        if attr.get("id") == "tts-engine-badge" and self.field_depth is not None:
            self.fields[-1]["badge"] = True

    def handle_endtag(self, tag: str) -> None:
        if self.label_depth == self.depth:
            self.label_depth = None
        if self.field_depth == self.depth:
            self.field_depth = None
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.label_depth is not None:
            self.fields[-1]["label"] += data.strip()


def _header() -> _HeaderFields:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    start = html.index('<div class="header-controls">')
    end = html.index("</header>", start)
    parser = _HeaderFields()
    parser.feed(html[start:end])
    parser.close()
    assert parser.depth == 0, "the header controls did not parse as balanced elements"
    return parser


def test_every_state_the_script_assigns_the_voice_badge_has_a_style() -> None:
    script = (STATIC / "components.js").read_text(encoding="utf-8")
    states = set(re.findall(r"'tts-engine-badge (\w+)'", script))
    assert states == {"pending", "ok", "degraded"}, f"the class seam moved: {states}"

    css = (STATIC / "style.css").read_text(encoding="utf-8")
    assert re.search(r"(^|\n)\.tts-engine-badge\s*\{", css), "no rule for the badge itself"
    for state in sorted(states):
        assert re.search(rf"\.tts-engine-badge\.{state}\s*\{{", css), f"no rule for .{state}"


def test_every_header_picker_has_a_visible_label_in_reading_order() -> None:
    header = _header()
    assert header.loose_selects == [], f"pickers with no visible label: {header.loose_selects}"
    assert [field["label"] for field in header.fields] == ["Voice", "Theme", "Font", "Size"]
    assert all(len(field["selects"]) == 1 for field in header.fields)


def test_the_voice_badge_sits_in_the_voice_field() -> None:
    header = _header()
    voice = next(field for field in header.fields if field["selects"] == ["voice-select"])
    assert voice["badge"], "the engine badge floats outside the voice field"
    assert sum(field["badge"] for field in header.fields) == 1
