"""Interactive flashcard and quiz review tab for the studyctl TUI.

Provides keyboard-driven study with spaced repetition tracking
and optional voice output via study-speak.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, ClassVar

try:
    from textual.binding import Binding
    from textual.containers import Center, Horizontal
    from textual.reactive import reactive
    from textual.widget import Widget
    from textual.widgets import Button, Static
except ImportError as _exc:
    raise ImportError("The TUI requires 'textual'. Install: pip install studyctl[tui]") from _exc

if TYPE_CHECKING:
    from textual.app import ComposeResult

from studyctl.review_db import record_card_review, record_session
from studyctl.review_loader import (
    Flashcard,
    QuizQuestion,
    ReviewResult,
)


class CardPanel(Static):
    """Displays a flashcard or quiz question with flip support."""

    revealed = reactive(False)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._front = ""
        self._back = ""

    def set_card(self, front: str, back: str) -> None:
        self._front = front
        self._back = back
        self.revealed = False
        self.update(self._front)

    def flip(self) -> None:
        self.revealed = not self.revealed
        self.update(self._back if self.revealed else self._front)


class StudyCardsTab(Widget):
    """Interactive flashcard and quiz review widget."""

    DEFAULT_CSS = """
    StudyCardsTab {
        layout: vertical;
        padding: 1 2;
    }
    #card-panel {
        height: auto;
        min-height: 5;
        padding: 1 2;
        border: round $accent;
        margin: 1 0;
    }
    #card-panel.revealed {
        border: round $success;
    }
    #score-bar {
        height: 3;
        dock: bottom;
        margin-top: 1;
    }
    #progress-label {
        text-align: center;
        margin: 1 0;
    }
    #status-label {
        text-align: center;
        color: $text-muted;
    }
    #voice-label {
        text-align: right;
        color: $text-muted;
    }
    .score-btn {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("space", "flip", "Flip / Submit"),
        Binding("y", "mark_correct", "Correct"),
        Binding("n", "mark_incorrect", "Incorrect"),
        Binding("s", "skip_card", "Skip"),
        Binding("h", "show_hint", "Hint"),
        Binding("v", "toggle_voice", "Voice"),
    ]

    current_index = reactive(0)
    voice_enabled = reactive(False)

    def __init__(
        self,
        cards: list[Flashcard | QuizQuestion],
        course_name: str = "",
        mode: str = "flashcards",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._cards = cards
        self._course = course_name
        self._mode = mode
        self._result = ReviewResult(total=len(cards))
        self._start_time = time.monotonic()
        self._card_start_time = time.monotonic()

    def compose(self) -> ComposeResult:
        yield Static(
            f"[bold]{self._course}[/bold] — {self._mode} ({len(self._cards)} items)",
            id="status-label",
        )
        voice_text = "Voice: ON" if self.voice_enabled else "Voice: OFF (v to toggle)"
        yield Static(voice_text, id="voice-label")
        yield CardPanel(id="card-panel")
        yield Static("", id="progress-label")
        with Center(), Horizontal(id="score-bar"):
            yield Button(
                "Know (y)",
                variant="success",
                id="btn-correct",
                classes="score-btn",
            )
            yield Button(
                "Don't Know (n)",
                variant="error",
                id="btn-incorrect",
                classes="score-btn",
            )
            yield Button(
                "Skip (s)",
                variant="default",
                id="btn-skip",
                classes="score-btn",
            )

    def on_mount(self) -> None:
        self._show_current_card()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-correct":
            self.action_mark_correct()
        elif event.button.id == "btn-incorrect":
            self.action_mark_incorrect()
        elif event.button.id == "btn-skip":
            self.action_skip_card()

    def _show_current_card(self) -> None:
        if self.current_index >= len(self._cards):
            self._show_summary()
            return

        card = self._cards[self.current_index]
        panel = self.query_one("#card-panel", CardPanel)
        self._card_start_time = time.monotonic()

        if isinstance(card, Flashcard):
            panel.set_card(
                f"[bold]Q:[/bold] {card.front}\n\n[dim]Press Space to reveal answer[/dim]",
                f"[bold]A:[/bold] {card.back}",
            )
        else:
            # Quiz question
            lines = [f"[bold]Q:[/bold] {card.question}\n"]
            letters = "abcdefghij"
            for j, opt in enumerate(card.options):
                lines.append(f"  [bold]{letters[j]})[/bold] {opt.text}")
            lines.append("\n[dim]Press Space to reveal answer[/dim]")
            panel.set_card(
                "\n".join(lines),
                self._format_quiz_answer(card),
            )

        # Speak the question if voice enabled
        if self.voice_enabled:
            text = card.front if isinstance(card, Flashcard) else card.question
            self._speak(text)

        progress = f"Card {self.current_index + 1}/{len(self._cards)}"
        if self._result.correct + self._result.incorrect > 0:
            progress += f"  |  Score: {self._result.score_pct:.0f}%"
        self.query_one("#progress-label", Static).update(progress)

    def _format_quiz_answer(self, q: QuizQuestion) -> str:
        letters = "abcdefghij"
        correct_idx = next((i for i, o in enumerate(q.options) if o.is_correct), 0)
        correct_opt = q.options[correct_idx]
        lines = [f"[green bold]Answer: {letters[correct_idx]})[/green bold] {correct_opt.text}"]
        if correct_opt.rationale:
            lines.append(f"\n[dim]{correct_opt.rationale}[/dim]")
        return "\n".join(lines)

    def _record_answer(self, correct: bool) -> None:
        card = self._cards[self.current_index]
        elapsed_ms = int((time.monotonic() - self._card_start_time) * 1000)

        if correct:
            self._result.correct += 1
        else:
            self._result.incorrect += 1
            self._result.wrong_hashes.append(card.card_hash)

        # Record to DB
        card_type = "flashcard" if isinstance(card, Flashcard) else "quiz"
        with contextlib.suppress(Exception):
            record_card_review(
                course=self._course,
                card_type=card_type,
                card_hash=card.card_hash,
                correct=correct,
                response_time_ms=elapsed_ms,
            )

        self.current_index += 1
        self._show_current_card()

    def _show_summary(self) -> None:
        duration = int(time.monotonic() - self._start_time)
        attempted = self._result.correct + self._result.incorrect
        pct = self._result.score_pct

        if pct >= 80:
            grade = "[green]Excellent[/green]"
        elif pct >= 60:
            grade = "[yellow]Good[/yellow]"
        else:
            grade = "[red]Needs review[/red]"

        wrong_count = len(self._result.wrong_hashes)
        summary = [
            "[bold]Session Complete![/bold]",
            "",
            f"  Score: {self._result.correct}/{attempted} ({pct:.0f}%) — {grade}",
            f"  Skipped: {self._result.skipped}",
            f"  Duration: {duration // 60}m {duration % 60}s",
        ]
        if wrong_count:
            summary.append(f"\n  [yellow]{wrong_count} cards to review again[/yellow]")

        panel = self.query_one("#card-panel", CardPanel)
        panel.update("\n".join(summary))

        # Hide score buttons
        for btn_id in ("btn-correct", "btn-incorrect", "btn-skip"):
            self.query_one(f"#{btn_id}", Button).display = False

        self.query_one("#progress-label", Static).update("[bold]Press q to return[/bold]")

        # Record session
        with contextlib.suppress(Exception):
            record_session(
                course=self._course,
                mode=self._mode,
                total=self._result.total,
                correct=self._result.correct,
                duration_seconds=duration,
            )

    def _speak(self, text: str) -> None:
        """Speak text via study-speak (non-blocking, best-effort)."""
        try:
            from agent_session_tools.speak import (
                _get_tts_config,
                _speak_kokoro,
            )

            cfg = _get_tts_config()
            voice = cfg.get("voice", "am_michael")
            speed = cfg.get("speed", 1.0)
            import threading

            threading.Thread(
                target=_speak_kokoro,
                args=(text,),
                kwargs={"voice": voice, "speed": speed},
                daemon=True,
            ).start()
        except Exception:
            pass  # Voice is optional

    # --- Actions ---

    def action_flip(self) -> None:
        panel = self.query_one("#card-panel", CardPanel)
        if not panel.revealed:
            panel.flip()
            panel.add_class("revealed")
            if self.voice_enabled and self.current_index < len(self._cards):
                card = self._cards[self.current_index]
                text = card.back if isinstance(card, Flashcard) else ""
                if text:
                    self._speak(text)

    def action_mark_correct(self) -> None:
        panel = self.query_one("#card-panel", CardPanel)
        if panel.revealed:
            panel.remove_class("revealed")
            self._record_answer(correct=True)

    def action_mark_incorrect(self) -> None:
        panel = self.query_one("#card-panel", CardPanel)
        if panel.revealed:
            panel.remove_class("revealed")
            self._record_answer(correct=False)

    def action_skip_card(self) -> None:
        self._result.skipped += 1
        panel = self.query_one("#card-panel", CardPanel)
        panel.remove_class("revealed")
        self.current_index += 1
        self._show_current_card()

    def action_show_hint(self) -> None:
        if self.current_index >= len(self._cards):
            return
        card = self._cards[self.current_index]
        if isinstance(card, QuizQuestion) and card.hint:
            self.notify(f"Hint: {card.hint}", title="Hint")

    def action_toggle_voice(self) -> None:
        self.voice_enabled = not self.voice_enabled
        label = self.query_one("#voice-label", Static)
        if self.voice_enabled:
            label.update("[green]Voice: ON[/green]")
            self.notify("Voice enabled")
        else:
            label.update("Voice: OFF (v to toggle)")
            self.notify("Voice disabled")
