"""Textual sidebar app — runs in the tmux sidebar pane.

Polls IPC files every 2 seconds, updates timer + activity feed + counters.
Writes ``session-oneline.txt`` as a side effect for the tmux status bar.

Timer computes elapsed from ``started_at + paused_at + total_paused_seconds``
(same formula as the web dashboard — single source of truth in state file).
"""

from __future__ import annotations

import time as time_mod
from datetime import UTC, datetime
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static
from textual.worker import work

from studyctl.session_state import (
    PARKING_FILE,
    SESSION_DIR,
    STATE_FILE,
    TOPICS_FILE,
    ParkingEntry,
    TopicEntry,
    parse_parking_file,
    parse_topics_file,
    read_session_state,
    write_session_state,
)

# Energy-adaptive break thresholds (from break-science.md)
# Maps energy band → (micro_break_mins, short_break_mins, long_break_mins)
BREAK_THRESHOLDS: dict[str, tuple[int, int, int]] = {
    "high": (25, 50, 90),
    "medium": (20, 40, 75),
    "low": (15, 30, 60),
}

# Status shapes matching session-protocol.md visual language
STATUS_SHAPES: dict[str, tuple[str, str]] = {
    "win": ("\u2713", "green"),
    "insight": ("\u2605", "green"),
    "learning": ("\u25c6", "blue"),
    "struggling": ("\u25b2", "yellow"),
    "parked": ("\u25cb", "dim"),
}


def _energy_band(energy: int) -> str:
    """Map 1-10 energy to band name."""
    if energy <= 3:
        return "low"
    if energy <= 6:
        return "medium"
    return "high"


def _compute_elapsed(state: dict) -> int:
    """Compute elapsed seconds from state file fields.

    Uses the same formula as the web dashboard (Alpine.js):
    elapsed = (now - started_at) - total_paused_seconds
    If paused, subtract (now - paused_at) too.
    """
    started_at_str = state.get("started_at")
    if not started_at_str:
        return 0
    try:
        started_at = datetime.fromisoformat(started_at_str)
    except (ValueError, TypeError):
        return 0

    now = datetime.now(UTC)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)

    elapsed = (now - started_at).total_seconds()
    elapsed -= state.get("total_paused_seconds", 0)

    paused_at_str = state.get("paused_at")
    if paused_at_str:
        try:
            paused_at = datetime.fromisoformat(paused_at_str)
            if paused_at.tzinfo is None:
                paused_at = paused_at.replace(tzinfo=UTC)
            elapsed -= (now - paused_at).total_seconds()
        except (ValueError, TypeError):
            pass

    return max(0, int(elapsed))


def _timer_phase(elapsed_secs: int, energy: int) -> str:
    """Compute timer colour phase from elapsed time + energy thresholds.

    Returns 'green', 'amber', or 'red'.
    """
    band = _energy_band(energy)
    thresholds = BREAK_THRESHOLDS[band]
    elapsed_mins = elapsed_secs / 60

    if elapsed_mins < thresholds[0]:  # micro-break
        return "green"
    if elapsed_mins < thresholds[1]:  # short break
        return "amber"
    return "red"


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class TimerWidget(Static):
    """Energy-adaptive timer with pause/resume/reset."""

    elapsed: reactive[int] = reactive(0)
    paused: reactive[bool] = reactive(False)
    energy: reactive[int] = reactive(5)
    timer_mode: reactive[str] = reactive("elapsed")

    def render(self) -> str:
        mins, secs = divmod(self.elapsed, 60)
        hours, mins = divmod(mins, 60)
        phase = _timer_phase(self.elapsed, self.energy)
        colour = {"green": "green", "amber": "yellow", "red": "red"}.get(phase, "white")
        indicator = " [bold red]PAUSED[/]" if self.paused else ""

        time_str = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"

        return f"[bold {colour}]{time_str}[/]{indicator}"


class ActivityFeed(Static):
    """Scrolling activity feed with shapes and colours."""

    DEFAULT_CSS = "ActivityFeed { height: 1fr; overflow-y: auto; }"

    def update_feed(
        self,
        topics: list[TopicEntry],
        parking: list[ParkingEntry],
    ) -> None:
        lines: list[str] = []

        for t in topics:
            shape, colour = STATUS_SHAPES.get(t.status, ("\u25c6", "blue"))
            note_part = f" \u2014 {t.note}" if t.note else ""
            lines.append(f"[{colour}]{shape}[/] [{colour}]{t.topic}{note_part}[/]")

        for p in parking:
            shape, colour = STATUS_SHAPES["parked"]
            lines.append(f"[{colour}]{shape} Parked: {p.question}[/]")

        if not lines:
            self.update("[dim]Waiting for session activity...[/]")
        else:
            self.update("\n".join(lines))


class CounterBar(Static):
    """WINS | PARKED | REVIEW counters."""

    def update_counts(
        self,
        topics: list[TopicEntry],
        parking: list[ParkingEntry],
    ) -> None:
        wins = sum(1 for t in topics if t.status in ("win", "insight"))
        review = sum(1 for t in topics if t.status == "struggling")
        parked = len(parking)
        self.update(f"[green]\u2713 {wins}[/]  [dim]\u25cb {parked}[/]  [yellow]\u25b2 {review}[/]")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class SidebarApp(App[None]):
    """tmux sidebar: timer + activity + counters."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #timer {
        height: 3;
        content-align: center middle;
        text-style: bold;
    }
    #activity {
        height: 1fr;
        padding: 0 1;
    }
    #counters {
        height: 3;
        content-align: center middle;
    }
    #status {
        height: 1;
        content-align: center middle;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("p", "toggle_pause", "Pause/Resume"),
        ("r", "reset_timer", "Reset"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield TimerWidget(id="timer")
        yield ActivityFeed(id="activity")
        yield CounterBar(id="counters")
        yield Static("[dim]p:pause  r:reset  q:quit[/]", id="status")

    def on_mount(self) -> None:
        self._poll_ipc_files()

    @work(thread=True, exclusive=True)
    def _poll_ipc_files(self) -> None:
        """Poll IPC files every 2 seconds, update widgets reactively."""
        last_mtimes = (0.0, 0.0, 0.0)
        while True:
            mtimes = (
                STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0.0,
                TOPICS_FILE.stat().st_mtime if TOPICS_FILE.exists() else 0.0,
                PARKING_FILE.stat().st_mtime if PARKING_FILE.exists() else 0.0,
            )

            state = read_session_state()
            topics = parse_topics_file()
            parking = parse_parking_file()

            # Always recompute elapsed (it changes every second)
            elapsed = _compute_elapsed(state)
            energy = state.get("energy", 5)
            paused = state.get("paused_at") is not None
            timer_mode = state.get("timer_mode", "elapsed")

            self.call_from_thread(self._update_timer, elapsed, energy, paused, timer_mode)

            # Only update feed/counters when files change
            if mtimes != last_mtimes:
                self.call_from_thread(self._update_feed, topics, parking)
                self._write_oneline(state, topics, parking, elapsed)
                last_mtimes = mtimes

            time_mod.sleep(2)

    def _update_timer(
        self,
        elapsed: int,
        energy: int,
        paused: bool,
        timer_mode: str,
    ) -> None:
        timer = self.query_one("#timer", TimerWidget)
        timer.elapsed = elapsed
        timer.energy = energy
        timer.paused = paused
        timer.timer_mode = timer_mode

    def _update_feed(
        self,
        topics: list[TopicEntry],
        parking: list[ParkingEntry],
    ) -> None:
        self.query_one("#activity", ActivityFeed).update_feed(topics, parking)
        self.query_one("#counters", CounterBar).update_counts(topics, parking)

    def _write_oneline(
        self,
        state: dict,
        topics: list[TopicEntry],
        parking: list[ParkingEntry],
        elapsed: int,
    ) -> None:
        """Write pre-formatted one-line status for tmux status bar."""
        topic = state.get("topic", "?")[:20]
        energy = state.get("energy", "?")
        wins = sum(1 for t in topics if t.status in ("win", "insight"))
        review = sum(1 for t in topics if t.status == "struggling")
        parked = len(parking)
        mins, secs = divmod(elapsed, 60)
        line = f"{topic} | {mins:02d}:{secs:02d} | E:{energy} | W:{wins} P:{parked} R:{review}"
        import contextlib

        with contextlib.suppress(OSError):
            (SESSION_DIR / "session-oneline.txt").write_text(line)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_pause(self) -> None:
        """Toggle timer pause/resume by writing to the state file."""
        state = read_session_state()
        if state.get("paused_at"):
            # Resume: add paused duration to total, clear paused_at
            paused_at = datetime.fromisoformat(state["paused_at"])
            if paused_at.tzinfo is None:
                paused_at = paused_at.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            pause_duration = (now - paused_at).total_seconds()
            total = state.get("total_paused_seconds", 0) + int(pause_duration)
            write_session_state({"paused_at": None, "total_paused_seconds": total})
        else:
            # Pause: record the pause timestamp
            write_session_state({"paused_at": datetime.now(UTC).isoformat()})

    def action_reset_timer(self) -> None:
        """Reset the timer to zero."""
        write_session_state(
            {
                "started_at": datetime.now(UTC).isoformat(),
                "paused_at": None,
                "total_paused_seconds": 0,
            }
        )


def run_sidebar() -> None:
    """Entry point for the sidebar app."""
    app = SidebarApp()
    app.run()
