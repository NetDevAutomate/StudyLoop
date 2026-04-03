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

from textual import work
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

# Break logic — imported from FCIS core (single source of truth)
from studyctl.logic.break_logic import THRESHOLDS as _BREAK_THRESHOLDS
from studyctl.logic.break_logic import BreakSuggestion, check_break_needed
from studyctl.logic.break_logic import energy_band as _energy_band
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

# Status shapes matching session-protocol.md visual language
STATUS_SHAPES: dict[str, tuple[str, str]] = {
    "win": ("\u2713", "green"),
    "insight": ("\u2605", "green"),
    "learning": ("\u25c6", "blue"),
    "struggling": ("\u25b2", "yellow"),
    "parked": ("\u25cb", "dim"),
}


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
    thresholds = _BREAK_THRESHOLDS[band]
    elapsed_mins = elapsed_secs / 60

    if elapsed_mins < thresholds.micro:
        return "green"
    if elapsed_mins < thresholds.short:
        return "amber"
    return "red"


# Pomodoro cycle: 25 focus, 5 break, repeated 4 times, then 15 long break.
# All durations in seconds.
POMODORO_FOCUS = 25 * 60
POMODORO_SHORT_BREAK = 5 * 60
POMODORO_LONG_BREAK = 15 * 60
POMODORO_CYCLE_LENGTH = 4  # long break after this many focus blocks


def _pomodoro_state(elapsed_secs: int) -> tuple[str, int, int, int]:
    """Compute pomodoro state from total elapsed seconds.

    Returns:
        (phase, remaining_secs, cycle_number, block_in_cycle)
        phase: "focus" | "short_break" | "long_break"
        remaining_secs: seconds left in current phase
        cycle_number: which full cycle (1-based)
        block_in_cycle: which focus block within the cycle (1-4)
    """
    # One full cycle = 4x(focus + short_break) - last short_break + long_break
    # = 4*25 + 3*5 + 15 = 130 min
    single_block = POMODORO_FOCUS + POMODORO_SHORT_BREAK  # 30 min
    full_cycle = (single_block * POMODORO_CYCLE_LENGTH) - POMODORO_SHORT_BREAK + POMODORO_LONG_BREAK

    cycle_number = elapsed_secs // full_cycle + 1
    pos_in_cycle = elapsed_secs % full_cycle

    # Walk through the blocks in the cycle
    for block_idx in range(POMODORO_CYCLE_LENGTH):
        # Focus phase
        if pos_in_cycle < POMODORO_FOCUS:
            remaining = POMODORO_FOCUS - pos_in_cycle
            return ("focus", remaining, cycle_number, block_idx + 1)
        pos_in_cycle -= POMODORO_FOCUS

        # Break phase (short for blocks 1-3, long for block 4)
        if block_idx < POMODORO_CYCLE_LENGTH - 1:
            if pos_in_cycle < POMODORO_SHORT_BREAK:
                remaining = POMODORO_SHORT_BREAK - pos_in_cycle
                return ("short_break", remaining, cycle_number, block_idx + 1)
            pos_in_cycle -= POMODORO_SHORT_BREAK
        else:
            if pos_in_cycle < POMODORO_LONG_BREAK:
                remaining = POMODORO_LONG_BREAK - pos_in_cycle
                return ("long_break", remaining, cycle_number, block_idx + 1)
            pos_in_cycle -= POMODORO_LONG_BREAK

    # Shouldn't reach here, but safety: start a new focus
    return ("focus", POMODORO_FOCUS, cycle_number + 1, 1)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class TimerWidget(Static):
    """Energy-adaptive timer with pause/resume/reset.

    Two modes:
    - **elapsed**: counts up, colour transitions at energy thresholds
    - **pomodoro**: 25/5/25/5/25/5/25/15 cycle, counts down within each phase
    """

    elapsed: reactive[int] = reactive(0)
    paused: reactive[bool] = reactive(False)
    energy: reactive[int] = reactive(5)
    timer_mode: reactive[str] = reactive("elapsed")

    def render(self) -> str:
        indicator = " [bold red]PAUSED[/]" if self.paused else ""

        if self.timer_mode == "pomodoro":
            return self._render_pomodoro() + indicator
        return self._render_elapsed() + indicator

    def _render_elapsed(self) -> str:
        """Count-up timer with energy-adaptive colour phases."""
        mins, secs = divmod(self.elapsed, 60)
        hours, mins = divmod(mins, 60)
        phase = _timer_phase(self.elapsed, self.energy)
        colour = {"green": "green", "amber": "yellow", "red": "red"}.get(phase, "white")
        time_str = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"
        return f"[bold {colour}]{time_str}[/]"

    def _render_pomodoro(self) -> str:
        """Countdown timer with focus/break cycle display."""
        phase, remaining, _cycle, block = _pomodoro_state(self.elapsed)
        mins, secs = divmod(remaining, 60)

        if phase == "focus":
            colour = "green"
            label = f"FOCUS {block}/{POMODORO_CYCLE_LENGTH}"
        elif phase == "short_break":
            colour = "cyan"
            label = "BREAK"
        else:
            colour = "magenta"
            label = "LONG BREAK"

        return f"[bold {colour}]{mins:02d}:{secs:02d}[/] [{colour}]{label}[/]"


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


class BreakBanner(Static):
    """Break suggestion banner — shows/hides based on FCIS check_break_needed()."""

    DEFAULT_CSS = """
    BreakBanner {
        height: auto;
        max-height: 3;
        content-align: center middle;
        display: none;
    }
    BreakBanner.visible {
        display: block;
    }
    BreakBanner.micro {
        background: $warning-darken-2;
        color: $text;
    }
    BreakBanner.short {
        background: $warning;
        color: $text;
    }
    BreakBanner.long {
        background: $error;
        color: $text;
        text-style: bold;
    }
    """

    def show_break(self, break_type: str, message: str) -> None:
        """Show the break banner with the given type and message."""
        self.remove_class("micro", "short", "long")
        self.add_class("visible", break_type)
        self.update(message)

    def hide_break(self) -> None:
        """Hide the break banner."""
        self.remove_class("visible", "micro", "short", "long")
        self.update("")


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
        ("Q", "end_session", "End Session"),
        ("q", "quit", "Quit sidebar"),
    ]

    def compose(self) -> ComposeResult:
        yield TimerWidget(id="timer")
        yield BreakBanner(id="break_banner")
        yield ActivityFeed(id="activity")
        yield CounterBar(id="counters")
        yield Static("[dim]p:pause  r:reset  Q:end session[/]", id="status")

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

            # Check if a break is needed (FCIS — pure function call)
            if not paused:
                elapsed_mins = elapsed // 60
                last_break_at = state.get("last_break_at_min")
                breaks_taken = state.get("breaks_taken", 0)
                suggestion = check_break_needed(
                    elapsed_minutes=elapsed_mins,
                    energy=energy,
                    last_break_at=last_break_at,
                    breaks_taken=breaks_taken,
                )
                self.call_from_thread(self._update_break_banner, suggestion)
                # Write break state to IPC for web dashboard
                if suggestion:
                    write_session_state(
                        {
                            "break_suggestion": suggestion.break_type,
                            "break_message": suggestion.message,
                        }
                    )
            else:
                self.call_from_thread(self._update_break_banner, None)

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

    def _update_break_banner(self, suggestion: BreakSuggestion | None) -> None:
        banner = self.query_one("#break_banner", BreakBanner)
        if suggestion is not None:
            banner.show_break(suggestion.break_type, suggestion.message)
        else:
            banner.hide_break()

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
        import contextlib

        topic = state.get("topic", "?")[:20]
        energy = state.get("energy", "?")
        wins = sum(1 for t in topics if t.status in ("win", "insight"))
        review = sum(1 for t in topics if t.status == "struggling")
        parked = len(parking)

        timer_mode = state.get("timer_mode", "elapsed")
        if timer_mode == "pomodoro":
            phase, remaining, _cycle, block = _pomodoro_state(elapsed)
            r_mins, r_secs = divmod(remaining, 60)
            if phase == "focus":
                timer_str = f"{r_mins:02d}:{r_secs:02d} F{block}"
            elif phase == "short_break":
                timer_str = f"{r_mins:02d}:{r_secs:02d} BRK"
            else:
                timer_str = f"{r_mins:02d}:{r_secs:02d} LONG"
        else:
            mins, secs = divmod(elapsed, 60)
            timer_str = f"{mins:02d}:{secs:02d}"

        line = f"{topic} | {timer_str} | E:{energy} | W:{wins} P:{parked} R:{review}"
        with contextlib.suppress(OSError):
            (SESSION_DIR / "session-oneline.txt").write_text(line)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_pause(self) -> None:
        """Toggle timer pause/resume by writing to the state file.

        Resuming from pause counts as "break taken" — resets the break
        clock so check_break_needed() won't re-suggest immediately.
        """
        state = read_session_state()
        if state.get("paused_at"):
            # Resume: add paused duration to total, clear paused_at
            paused_at = datetime.fromisoformat(state["paused_at"])
            if paused_at.tzinfo is None:
                paused_at = paused_at.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            pause_duration = (now - paused_at).total_seconds()
            total = state.get("total_paused_seconds", 0) + int(pause_duration)
            # Record break taken: elapsed minutes at resume time
            elapsed = _compute_elapsed(state)
            elapsed_min = elapsed // 60
            breaks = state.get("breaks_taken", 0) + 1
            write_session_state(
                {
                    "paused_at": None,
                    "total_paused_seconds": total,
                    "last_break_at_min": elapsed_min,
                    "breaks_taken": breaks,
                    "break_suggestion": None,
                    "break_message": None,
                }
            )
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

    def action_end_session(self) -> None:
        """End the entire study session (agent + sidebar + tmux).

        Sends /exit to Claude Code, runs DB cleanup, then fires a raw
        tmux kill-session. We DON'T use the retry-loop kill_session()
        because we're running inside the session being killed — tmux
        sends SIGHUP which terminates us mid-verification.

        Strategy: fire the kill and accept that we'll die from SIGHUP.
        """
        import contextlib

        from studyctl.session_state import read_session_state
        from studyctl.tmux import _tmux

        state = read_session_state()
        main_pane = state.get("tmux_main_pane")
        session_name = state.get("tmux_session")

        # Try graceful agent exit (best effort)
        if main_pane:
            with contextlib.suppress(Exception):
                _tmux("send-keys", "-t", main_pane, "C-c")
                time_mod.sleep(0.5)
                _tmux("send-keys", "-t", main_pane, "/exit", "Enter")
                time_mod.sleep(1)

        # Run DB cleanup (state=ended, end study session, clean IPC files).
        # Idempotent — safe even if the agent wrapper's cleanup also fires.
        with contextlib.suppress(Exception):
            from studyctl.cli._study import _cleanup_session

            _cleanup_session()

        # Fire-and-forget: kill ALL study tmux sessions. This ensures no
        # stale sessions remain and the user returns to their original shell
        # (not stranded in tmux). Kills us too via SIGHUP — that's fine.
        from studyctl.tmux import kill_all_study_sessions

        kill_all_study_sessions(current_session=session_name)

        # If we somehow survive (e.g., no sessions found), exit cleanly.
        self.exit()


def run_sidebar() -> None:
    """Entry point for the sidebar app."""
    app = SidebarApp()
    app.run()


if __name__ == "__main__":
    run_sidebar()
