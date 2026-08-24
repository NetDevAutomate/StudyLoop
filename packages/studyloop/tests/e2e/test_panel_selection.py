"""Selecting and bulk-deleting on the Parking Lot and Notes panels.

Written from two user reports, both about the same two panels:

  A. *"Items are VERY hard to select. It took several tries and at times I had
     to resort to Tab and Space/Return."*
  B. *"Selecting one or all doesn't allow me to delete the selected items."*

Neither was a missing feature — ``POST /api/parking/clear`` and
``POST /api/notes/clear`` have taken ``ids`` or ``all`` since they were written,
and both are driven by passing journeys. Both reports were about the **pointer
and the affordance**, which is why nothing in the suite caught them:

* a press that drifted past the drag threshold and changed nothing still
  swallowed its own click, so the card did nothing at all — the "several tries";
* the checkbox, the clear button and the column-select button were all below the
  WCAG 2.2 24x24 minimum on a PWA that advertises phone and tablet use;
* clicking a card only ever opened the editor, never selected, while
  ``.selected`` and ``.editing`` looked the same — so a card could look selected
  while the selection was empty and the delete button sat disabled;
* the whole bulk bar (and every checkbox) lived behind a mode button, so there
  was no visual entry point to bulk delete anywhere on either panel.

Everything here drives the REAL panels against a REAL server on an isolated
temp database — no stubbed selectors, no mocked fetches, and the learner's own
notes and parked topics are never touched.

Run:  uv run --group dev pytest packages/studyloop/tests/e2e/test_panel_selection.py -m e2e
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")
pytest.importorskip("requests")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_paths import PLAYWRIGHT_ARTIFACTS as RESULTS  # noqa: E402
from e2e._env import RunningServer, build_test_world, start_server  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Iterator

    from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18614  # unique; sister e2e suites use 18593-18613

#: WCAG 2.2 SC 2.5.8 (Target Size, Minimum). 44px is the AAA/touch figure the
#: panels reach under ``@media (pointer: coarse)``; 24 is the floor everywhere.
MIN_TARGET_PX = 24


def _diag(page: Page | None, name: str) -> None:
    """Best-effort failure artefacts (screenshot + HTML)."""
    if page is None:
        return
    RESULTS.mkdir(exist_ok=True)
    stamp = int(time.time())
    try:
        page.screenshot(path=str(RESULTS / f"{name}-{stamp}.png"), full_page=True)
        (RESULTS / f"{name}-{stamp}.html").write_text(page.content())
    except Exception:  # pragma: no cover - diagnostics must not mask the failure
        pass


# ---------------------------------------------------------------------------
# Isolated server
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def running_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[RunningServer]:
    """Real subprocess server on a temp DB and a temp state dir.

    Isolation is not optional here: this module creates and deletes parked
    topics and notes, and the developer's real ``~/.config/studyloop`` holds
    their actual study history.
    """
    root = tmp_path_factory.mktemp("panel-selection")
    world = build_test_world(root, WEB_PORT, fake_agent=True)
    server = start_server(world)
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture()
def clean(running_server: RunningServer) -> str:
    """Hard-clear both panels before each test so counts mean something."""
    import requests

    base_url = running_server.base_url
    for path in ("/api/parking/clear", "/api/notes/clear"):
        requests.post(f"{base_url}{path}", json={"all": True, "hard": True}, timeout=10)
    return base_url


def _seed_cards(server: str, *questions: str) -> None:
    import requests

    for question in questions:
        resp = requests.post(f"{server}/api/parking/item", json={"question": question}, timeout=10)
        assert resp.status_code == 201, resp.text


def _seed_notes(server: str, *titles: str) -> None:
    import requests

    for title in titles:
        resp = requests.post(
            f"{server}/api/notes",
            json={"title": title, "body": "Body for " + title, "kind": "note"},
            timeout=10,
        )
        assert resp.status_code == 201, resp.text


def _open_parking(page: Page, server: str) -> None:
    page.goto(f"{server}/")
    page.wait_for_function("() => !!window.Alpine", timeout=10_000)
    page.locator("#parking-lot-toggle").click()
    page.wait_for_selector("#parking-panel", state="visible", timeout=8_000)
    page.wait_for_function(
        "() => document.querySelectorAll('#parking-panel .parking-column').length > 0",
        timeout=8_000,
    )


def _open_notes(page: Page, server: str) -> None:
    page.goto(f"{server}/")
    page.wait_for_function("() => !!window.Alpine", timeout=10_000)
    page.locator("#notes-toggle").click()
    page.wait_for_selector("#notes-panel", state="visible", timeout=8_000)


def _card(page: Page, question: str):
    return page.locator(
        "#parking-panel .parking-card",
        has=page.locator(f'.parking-card-title:text-is("{question}")'),
    )


def _hit_box(page: Page, selector: str) -> dict:
    """Bounding box of a control's *clickable region*, label wrapper included.

    Deliberately class-name agnostic: what matters to a finger is the size of
    whatever region activates the control, not which element carries the CSS.
    """
    box = page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const hit = el.closest('label') || el;
            const r = hit.getBoundingClientRect();
            return { width: r.width, height: r.height };
        }""",
        selector,
    )
    assert box is not None, f"no element matched {selector!r}"
    return box


# ---------------------------------------------------------------------------
# Bug A1 — a press that changes nothing must behave like a click
# ---------------------------------------------------------------------------


def test_a_small_pointer_drift_still_opens_the_card(page: Page, clean: str) -> None:
    """The headline defect: 9px of trackpad drift used to eat the click entirely.

    The old code set ``_justDragged`` *before* the "dropped outside a column"
    and "same column, no-op" early returns, so any press that wandered past the
    6px threshold and changed nothing produced no drag, no edit and no feedback
    of any kind. The user clicked again, and again — "several tries".

    The contract this pins: **a press that changes nothing always behaves like
    a click.**
    """
    try:
        _seed_cards(clean, "Drifty click")
        _open_parking(page, clean)

        title = page.locator('#parking-panel .parking-card-title:text-is("Drifty click")')
        box = title.bounding_box()
        assert box
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2

        page.mouse.move(cx, cy)
        page.mouse.down()
        # 9px: past the 6px mouse threshold, nowhere near a deliberate drag,
        # and squarely in the range a trackpad produces on an ordinary click.
        page.mouse.move(cx + 9, cy, steps=3)
        page.mouse.up()

        page.wait_for_selector("#parking-panel .parking-card.editing", timeout=5_000)
        _card(page, "Drifty click").locator(".parking-title-input").wait_for(
            state="visible", timeout=5_000
        )
    except Exception:
        _diag(page, "selection-drift-click")
        raise


def test_a_touch_tap_with_finger_drift_still_opens_the_card(page: Page, clean: str) -> None:
    """A finger is not a mouse: ~10px of tap-drift is an ordinary tap.

    One threshold for every pointer type is what made the PWA's own advertised
    input method the worst-behaved one. Driven with real ``PointerEvent``s
    carrying ``pointerType: 'touch'`` because that is the only way to give the
    component a touch pointer *with* drift.
    """
    try:
        _seed_cards(clean, "Tap me")
        _open_parking(page, clean)

        page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                const r = el.getBoundingClientRect();
                const x = r.x + r.width / 2, y = r.y + r.height / 2;
                const make = (type, px, py, buttons) => new PointerEvent(type, {
                    bubbles: true, cancelable: true, composed: true,
                    pointerId: 1, pointerType: 'touch', isPrimary: true,
                    button: 0, buttons, clientX: px, clientY: py,
                });
                el.dispatchEvent(make('pointerdown', x, y, 1));
                window.dispatchEvent(make('pointermove', x + 4, y + 5, 1));
                window.dispatchEvent(make('pointermove', x + 7, y + 8, 1));
                window.dispatchEvent(make('pointerup', x + 7, y + 8, 0));
                el.dispatchEvent(new MouseEvent('click', {
                    bubbles: true, cancelable: true,
                    clientX: x + 7, clientY: y + 8,
                }));
            }""",
            "#parking-panel .parking-card-title",
        )

        page.wait_for_selector("#parking-panel .parking-card.editing", timeout=5_000)
    except Exception:
        _diag(page, "selection-touch-drift")
        raise


def test_a_real_drag_back_to_the_same_column_does_not_open_the_editor(
    page: Page, clean: str
) -> None:
    """The other half of the contract — an unambiguous drag still eats its click.

    Without this, loosening the swallow rule would make every dropped-and-
    reconsidered drag pop the editor open.
    """
    try:
        _seed_cards(clean, "Dragged and reconsidered")
        _open_parking(page, clean)

        title = page.locator("#parking-panel .parking-card-title").first
        box = title.bounding_box()
        assert box
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx, cy + 90, steps=8)  # a real drag, deliberately long
        page.mouse.move(cx + 2, cy + 2, steps=8)  # …then dropped back where it started
        page.mouse.up()

        page.wait_for_timeout(400)
        assert page.locator("#parking-panel .parking-card.editing").count() == 0, (
            "a committed drag must still swallow its trailing click"
        )
    except Exception:
        _diag(page, "selection-real-drag")
        raise


# ---------------------------------------------------------------------------
# Bug A2 — hit targets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "selector",
    [
        "#parking-panel .parking-card-check",
        "#parking-panel .parking-card-clear",
        "#parking-panel .parking-column-select",
    ],
)
def test_parking_controls_meet_the_minimum_target_size(
    page: Page, clean: str, selector: str
) -> None:
    """A bare native checkbox is ~13x13. WCAG 2.2 puts the floor at 24x24."""
    try:
        _seed_cards(clean, "Target size")
        _open_parking(page, clean)
        box = _hit_box(page, selector)
        assert box["width"] >= MIN_TARGET_PX and box["height"] >= MIN_TARGET_PX, (
            f"{selector} hit area is {box['width']:.0f}x{box['height']:.0f}, "
            f"below the {MIN_TARGET_PX}px minimum"
        )
    except Exception:
        _diag(page, "selection-target-parking")
        raise


@pytest.mark.parametrize(
    "selector",
    ["#notes-panel .note-card-check", "#notes-panel .note-card-delete"],
)
def test_notes_controls_meet_the_minimum_target_size(page: Page, clean: str, selector: str) -> None:
    try:
        _seed_notes(clean, "Target size note")
        _open_notes(page, clean)
        page.wait_for_selector("#notes-panel .note-card", timeout=8_000)
        box = _hit_box(page, selector)
        assert box["width"] >= MIN_TARGET_PX and box["height"] >= MIN_TARGET_PX, (
            f"{selector} hit area is {box['width']:.0f}x{box['height']:.0f}, "
            f"below the {MIN_TARGET_PX}px minimum"
        )
    except Exception:
        _diag(page, "selection-target-notes")
        raise


# ---------------------------------------------------------------------------
# Bug A3 — selected must not look like open, and a click must be able to select
# ---------------------------------------------------------------------------


def test_a_selected_parking_card_looks_different_from_an_open_one(page: Page, clean: str) -> None:
    """Both states used to be "accent border" and nothing else.

    That is how a user ends up staring at what looks like a selected card while
    ``selected`` is still empty and the delete button is disabled.
    """
    try:
        _seed_cards(clean, "Ticked", "Opened")
        _open_parking(page, clean)

        _card(page, "Ticked").locator(".parking-card-check").check()
        _card(page, "Opened").locator(".parking-card-title").click()
        page.wait_for_selector("#parking-panel .parking-card.editing", timeout=5_000)

        styles = page.evaluate(
            """() => {
                const pick = (cls) => document.querySelector(
                    '#parking-panel .parking-card.' + cls);
                const read = (el) => {
                    const cs = getComputedStyle(el);
                    const before = getComputedStyle(el, '::before');
                    return {
                        background: cs.backgroundColor,
                        shadow: cs.boxShadow,
                        beforeBackground: before.backgroundColor,
                        beforeWidth: before.width,
                    };
                };
                return { selected: read(pick('selected')), editing: read(pick('editing')) };
            }"""
        )
        assert styles["selected"] != styles["editing"], (
            "a selected card and an open card are visually identical beyond the "
            f"border colour: {styles}"
        )
        marked = styles["selected"]["shadow"] != "none" or styles["selected"][
            "beforeWidth"
        ] not in ("auto", "0px")
        assert marked, (
            "selection needs a mark of its own (bar/shadow), not just a border "
            f"colour it shares with the editor: {styles['selected']}"
        )
    except Exception:
        _diag(page, "selection-selected-vs-editing")
        raise


def test_a_selected_note_looks_different_from_an_open_one(page: Page, clean: str) -> None:
    try:
        _seed_notes(clean, "Ticked note", "Opened note")
        _open_notes(page, clean)
        page.wait_for_selector("#notes-panel .note-card", timeout=8_000)

        page.locator('#notes-panel .note-card:has-text("Ticked note") .note-card-check').check()
        page.locator('#notes-panel .note-card:has-text("Opened note") .note-card-title').click()
        page.wait_for_selector("#notes-panel .note-card.editing", timeout=5_000)

        styles = page.evaluate(
            """() => {
                const pick = (cls) => document.querySelector('#notes-panel .note-card.' + cls);
                const read = (el) => {
                    const cs = getComputedStyle(el);
                    const before = getComputedStyle(el, '::before');
                    return {
                        background: cs.backgroundColor,
                        shadow: cs.boxShadow,
                        beforeWidth: before.width,
                    };
                };
                return { selected: read(pick('selected')), editing: read(pick('editing')) };
            }"""
        )
        assert styles["selected"] != styles["editing"], (
            f"a selected note and an open note look identical: {styles}"
        )
        assert styles["selected"]["shadow"] != "none" or styles["selected"]["beforeWidth"] not in (
            "auto",
            "0px",
        ), f"selection needs a mark of its own: {styles['selected']}"
    except Exception:
        _diag(page, "selection-note-selected-vs-editing")
        raise


def test_in_select_mode_clicking_a_parking_card_selects_it(page: Page, clean: str) -> None:
    """Select mode makes the card body the checkbox — the gesture people reach for.

    Previously ``onCardTitleClick`` never consulted ``selectMode``, so "select
    this one" opened an editor and left the selection empty.
    """
    try:
        _seed_cards(clean, "Click to select")
        _open_parking(page, clean)

        page.locator("#parking-select-mode").click()
        page.locator('#parking-panel .parking-card-title:text-is("Click to select")').click()

        page.wait_for_function(
            """() => document.querySelector('#parking-selected-count')
                     .innerText.trim().startsWith('1')""",
            timeout=5_000,
        )
        assert page.locator("#parking-panel .parking-card.editing").count() == 0, (
            "in select mode a card click must select, not open the editor"
        )
        assert not page.locator("#parking-clear-selected").is_disabled()

        # …and clicking again deselects, or "select" would be a one-way door.
        page.locator('#parking-panel .parking-card-title:text-is("Click to select")').click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card.selected').length === 0",
            timeout=5_000,
        )
        assert page.locator("#parking-clear-selected").is_disabled()
    except Exception:
        _diag(page, "selection-click-selects-parking")
        raise


def test_in_select_mode_clicking_a_note_selects_it(page: Page, clean: str) -> None:
    try:
        _seed_notes(clean, "Clickable note")
        _open_notes(page, clean)
        page.wait_for_selector("#notes-panel .note-card", timeout=8_000)

        page.locator("#notes-select-mode").click()
        page.locator('#notes-panel .note-card-title:text-is("Clickable note")').click()

        page.wait_for_function(
            """() => document.querySelector('#notes-selected-count')
                     .innerText.trim().startsWith('1')""",
            timeout=5_000,
        )
        assert page.locator("#notes-panel .note-card.editing").count() == 0
        assert not page.locator("#notes-clear-selected").is_disabled()
    except Exception:
        _diag(page, "selection-click-selects-notes")
        raise


def test_keyboard_can_select_a_focused_parking_card(page: Page, clean: str) -> None:
    """Enter/Space on the card itself — parity with the pointer gesture.

    The card ``<article>`` was ``tabindex="0"`` but bound only arrow keys, so
    the only keyboard route into selection was Tab-ing to the inner checkbox.
    """
    try:
        _seed_cards(clean, "Keyboard select")
        _open_parking(page, clean)

        page.locator("#parking-select-mode").click()
        card = page.locator("#parking-panel .parking-card").first
        card.focus()
        page.keyboard.press("Enter")

        page.wait_for_function(
            """() => document.querySelector('#parking-selected-count')
                     .innerText.trim().startsWith('1')""",
            timeout=5_000,
        )
    except Exception:
        _diag(page, "selection-keyboard")
        raise


# ---------------------------------------------------------------------------
# Bug A4 — the target must not move while the user is aiming at it
# ---------------------------------------------------------------------------


def test_entering_select_mode_does_not_shift_the_card_contents(page: Page, clean: str) -> None:
    """The checkbox used to be ``x-show``-toggled with no reserved space.

    Every card's contents jumped ~19px sideways the instant select mode was
    entered — moving the very target the user was already aiming at.
    """
    try:
        _seed_cards(clean, "Stay put")
        _open_parking(page, clean)

        title = page.locator("#parking-panel .parking-card-title").first
        before = title.bounding_box()
        page.locator("#parking-select-mode").click()
        page.wait_for_timeout(250)
        after = title.bounding_box()
        assert before and after
        assert abs(before["x"] - after["x"]) < 1.0, (
            f"card contents moved {abs(before['x'] - after['x']):.0f}px when select "
            "mode was entered"
        )
    except Exception:
        _diag(page, "selection-no-shift")
        raise


# ---------------------------------------------------------------------------
# Bug B — bulk delete must be reachable, and All/None must actually work
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("panel", "prefix"),
    [("parking", "parking"), ("notes", "notes")],
)
def test_bulk_delete_is_visible_without_entering_a_mode(
    page: Page, clean: str, panel: str, prefix: str
) -> None:
    """The capability existed; nothing on either panel advertised it.

    The bulk bar was wrapped in ``<template x-if="selectMode">`` — absent from
    the DOM entirely — and the checkboxes were ``x-show="selectMode"`` too, so
    there was no visual entry point to bulk deletion anywhere.
    """
    try:
        if panel == "parking":
            _seed_cards(clean, "Discoverable")
            _open_parking(page, clean)
            check = "#parking-panel .parking-card-check"
        else:
            _seed_notes(clean, "Discoverable note")
            _open_notes(page, clean)
            page.wait_for_selector("#notes-panel .note-card", timeout=8_000)
            check = "#notes-panel .note-card-check"

        for control in ("select-all", "select-none", "selected-count", "clear-selected"):
            locator = page.locator(f"#{prefix}-{control}")
            assert locator.is_visible(), (
                f"#{prefix}-{control} is not reachable without first finding a mode button"
            )
        assert page.locator(check).is_visible(), (
            "cards give no sign that they can be selected at all"
        )
    except Exception:
        _diag(page, f"selection-discoverable-{panel}")
        raise


def test_disabled_delete_selected_explains_itself(page: Page, clean: str) -> None:
    """A greyed-out button with no explanation reads as broken, not un-armed."""
    try:
        _seed_cards(clean, "Nothing ticked yet")
        _open_parking(page, clean)

        button = page.locator("#parking-clear-selected")
        assert button.is_disabled()
        hint = (button.get_attribute("title") or "").lower()
        assert "select" in hint or "tick" in hint or "choose" in hint, (
            f"the disabled state must say why it is disabled, got {hint!r}"
        )
        count = page.locator("#parking-selected-count").inner_text().lower()
        assert count.strip() not in ("", "0 selected"), (
            "'0 selected' next to a greyed button teaches nothing about what to do"
        )
    except Exception:
        _diag(page, "selection-disabled-explains")
        raise


def test_both_panels_call_the_bulk_action_the_same_thing(page: Page, clean: str) -> None:
    """Parking said "Clear selected", Notes said "Delete selected".

    The user's own word was "delete"; two names for one gesture on two panels
    in the same column is a reason to hunt for a second feature that isn't there.
    """
    try:
        _seed_cards(clean, "Label check")
        _seed_notes(clean, "Label check note")
        _open_parking(page, clean)
        parking_label = page.locator("#parking-clear-selected").inner_text().strip()
        page.locator("#notes-toggle").click()
        page.wait_for_selector("#notes-panel", state="visible", timeout=8_000)
        notes_label = page.locator("#notes-clear-selected").inner_text().strip()
        assert parking_label == notes_label == "Delete selected", (
            f"panels disagree on the label: parking={parking_label!r} notes={notes_label!r}"
        )
    except Exception:
        _diag(page, "selection-labels")
        raise


def test_parking_select_all_then_delete_selected_clears_the_board(page: Page, clean: str) -> None:
    """``#parking-select-all`` was referenced by no test anywhere. Now it is."""
    import requests

    try:
        _seed_cards(clean, "Alpha", "Beta", "Gamma")
        _open_parking(page, clean)
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 3",
            timeout=8_000,
        )

        page.locator("#parking-select-all").click()
        page.wait_for_function(
            """() => document.querySelector('#parking-selected-count')
                     .innerText.trim().startsWith('3')""",
            timeout=5_000,
        )
        assert page.locator("#parking-panel .parking-card.selected").count() == 3

        page.locator("#parking-clear-selected").click()
        page.wait_for_selector("#parking-empty", state="visible", timeout=8_000)
        assert requests.get(f"{clean}/api/parking/board", timeout=10).json()["total"] == 0

        # Soft, so the undo the toast promises is real.
        page.locator("#parking-undo-clear").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 3",
            timeout=8_000,
        )
    except Exception:
        _diag(page, "selection-parking-all")
        raise


def test_parking_select_none_drops_the_whole_selection(page: Page, clean: str) -> None:
    """``#parking-select-none`` was referenced by no test anywhere either."""
    try:
        _seed_cards(clean, "One", "Two")
        _open_parking(page, clean)
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 2",
            timeout=8_000,
        )

        page.locator("#parking-select-all").click()
        page.wait_for_function(
            """() => document.querySelector('#parking-selected-count')
                     .innerText.trim().startsWith('2')""",
            timeout=5_000,
        )
        page.locator("#parking-select-none").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card.selected').length === 0",
            timeout=5_000,
        )
        assert page.locator("#parking-clear-selected").is_disabled(), (
            "with nothing selected, delete-selected must go inert again"
        )
        # Nothing was deleted by clearing a selection.
        assert page.locator("#parking-panel .parking-card").count() == 2
    except Exception:
        _diag(page, "selection-parking-none")
        raise


def test_notes_select_all_then_delete_selected_empties_the_list(page: Page, clean: str) -> None:
    """``#notes-select-all`` — the other half of the untested pair."""
    import requests

    try:
        _seed_notes(clean, "Note one", "Note two", "Note three")
        _open_notes(page, clean)
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '3 notes'",
            timeout=10_000,
        )

        page.locator("#notes-select-all").click()
        page.wait_for_function(
            """() => document.querySelector('#notes-selected-count')
                     .innerText.trim().startsWith('3')""",
            timeout=5_000,
        )
        page.locator("#notes-clear-selected").click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '0 notes'",
            timeout=10_000,
        )
        assert requests.get(f"{clean}/api/notes", timeout=10).json()["notes"] == []

        page.locator("#notes-undo-clear").click()
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '3 notes'",
            timeout=10_000,
        )
    except Exception:
        _diag(page, "selection-notes-all")
        raise


def test_notes_select_none_drops_the_whole_selection(page: Page, clean: str) -> None:
    """``#notes-select-none`` — completing the four untested controls."""
    try:
        _seed_notes(clean, "Keep one", "Keep two")
        _open_notes(page, clean)
        page.wait_for_function(
            "() => document.querySelector('#notes-total-count').innerText === '2 notes'",
            timeout=10_000,
        )

        page.locator("#notes-select-all").click()
        page.wait_for_function(
            """() => document.querySelector('#notes-selected-count')
                     .innerText.trim().startsWith('2')""",
            timeout=5_000,
        )
        page.locator("#notes-select-none").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#notes-panel .note-card.selected').length === 0",
            timeout=5_000,
        )
        assert page.locator("#notes-clear-selected").is_disabled()
        assert page.locator("#notes-panel .note-card").count() == 2
    except Exception:
        _diag(page, "selection-notes-none")
        raise


def test_ticking_a_checkbox_alone_arms_delete_selected(page: Page, clean: str) -> None:
    """The end-to-end path the user reported broken: tick one, delete it.

    No mode button anywhere in this test — that is the point.
    """
    import requests

    try:
        _seed_cards(clean, "Delete me", "Keep me")
        _open_parking(page, clean)
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 2",
            timeout=8_000,
        )

        assert page.locator("#parking-clear-selected").is_disabled()
        _card(page, "Delete me").locator(".parking-card-check").check()
        page.wait_for_function(
            """() => !document.querySelector('#parking-clear-selected').disabled""",
            timeout=5_000,
        )
        page.locator("#parking-clear-selected").click()
        page.wait_for_function(
            "() => document.querySelectorAll('#parking-panel .parking-card').length === 1",
            timeout=8_000,
        )

        board = requests.get(f"{clean}/api/parking/board", timeout=10).json()
        survivors = {i["question"] for c in board["columns"] for i in c["items"]}
        assert survivors == {"Keep me"}
    except Exception:
        _diag(page, "selection-tick-then-delete")
        raise
