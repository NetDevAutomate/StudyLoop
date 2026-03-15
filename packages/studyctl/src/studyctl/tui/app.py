"""Textual TUI application for studyctl study management.

Launch via ``studyctl tui``.  Requires the ``tui`` extra::

    pip install studyctl[tui]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

try:
    from textual.app import App, ComposeResult
    from textual.containers import Vertical
    from textual.screen import ModalScreen
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        OptionList,
        Static,
        TabbedContent,
        TabPane,
    )
    from textual.widgets.option_list import Option
except ImportError as _exc:
    raise ImportError(
        "The TUI requires the 'textual' package. Install it with:\n  pip install studyctl[tui]"
    ) from _exc

from studyctl.cli import TOPIC_KEYWORDS
from studyctl.history import (
    get_study_session_stats,
    list_concepts,
    spaced_repetition_due,
    struggle_topics,
)
from studyctl.review_loader import (
    discover_directories,
    find_content_dirs,
    load_flashcards,
    load_quizzes,
    shuffle_items,
)


def _load_session_state() -> dict:
    """Load session state from the JSON file, returning defaults on failure."""
    state_path = Path.home() / ".config" / "studyctl" / "session-state.json"
    try:
        return json.loads(state_path.read_text()) if state_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


class CoursePickerScreen(ModalScreen[tuple[str, Path] | None]):
    """Modal overlay for selecting a course directory."""

    CSS = """
    CoursePickerScreen {
        align: center middle;
    }
    #course-picker {
        width: 60;
        max-height: 20;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def __init__(self, courses: list[tuple[str, Path]]) -> None:
        super().__init__()
        self._courses = courses

    def compose(self) -> ComposeResult:
        yield OptionList(
            *[Option(name) for name, _ in self._courses],
            id="course-picker",
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._courses[event.option_index])


class StudyApp(App):
    """Read-only study management dashboard."""

    TITLE = "studyctl"
    CSS = """
    Screen {
        background: $surface;
    }
    #dashboard-content {
        padding: 1 2;
    }
    .section-header {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }
    .info-line {
        margin-bottom: 0;
    }

    /* Dyslexic-friendly: wider spacing, more padding, clearer separation */
    .dyslexic #dashboard-content {
        padding: 2 4;
    }
    .dyslexic .section-header {
        margin-bottom: 2;
    }
    .dyslexic .info-line {
        margin-bottom: 1;
    }
    .dyslexic DataTable {
        padding: 1 2;
    }
    .dyslexic #card-panel {
        padding: 2 4;
        min-height: 8;
        margin: 2 1;
    }
    .dyslexic #progress-label {
        margin: 2 0;
    }
    .dyslexic #status-label {
        margin-bottom: 1;
    }
    .dyslexic .score-btn {
        margin: 0 2;
    }
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("d", "show_tab('dashboard')", "Dashboard"),
        ("r", "show_tab('review')", "Review"),
        ("c", "show_tab('concepts')", "Concepts"),
        ("s", "show_tab('sessions')", "Sessions"),
        ("f", "start_flashcards", "Flashcards"),
        ("z", "start_quiz", "Quiz"),
        ("o", "toggle_dyslexic", "OpenDyslexic"),
    ]

    def __init__(
        self,
        study_dirs: list[str] | None = None,
        theme_name: str = "",
        dyslexic_friendly: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._study_dirs = study_dirs or []
        self._theme_name = theme_name
        self._dyslexic_friendly = dyslexic_friendly

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(
            "Dashboard",
            "Review",
            "Concepts",
            "Sessions",
            "StudyCards",
            id="tabs",
        ):
            with TabPane("Dashboard", id="dashboard"):
                yield Vertical(
                    Static("", id="dashboard-content"),
                    id="dashboard-container",
                )
            with TabPane("Review", id="review"):
                yield DataTable(id="review-table")
            with TabPane("Concepts", id="concepts"):
                yield DataTable(id="concepts-table")
            with TabPane("Sessions", id="sessions"):
                yield DataTable(id="sessions-table")
            with TabPane("StudyCards", id="studycards"):
                yield Vertical(
                    Static("", id="studycards-content"),
                    id="studycards-container",
                )
        yield Footer()

    def on_mount(self) -> None:
        if self._theme_name:
            self.theme = self._theme_name
        if self._dyslexic_friendly:
            self.add_class("dyslexic")
            self.notify(
                "Dyslexic-friendly mode ON. For best results, set your "
                "terminal font to OpenDyslexic: https://opendyslexic.org",
                title="Accessibility",
                timeout=8,
            )
        self._populate_dashboard()
        self._populate_review()
        self._populate_concepts()
        self._populate_sessions()
        self._populate_studycards()

    def action_show_tab(self, tab_id: str) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = tab_id

    def action_toggle_dyslexic(self) -> None:
        """Toggle dyslexic-friendly mode (wider spacing)."""
        self.toggle_class("dyslexic")
        if self.has_class("dyslexic"):
            self.notify(
                "Dyslexic-friendly mode ON — wider spacing applied. "
                "Set terminal font to OpenDyslexic for best results.",
                title="Accessibility",
            )
        else:
            self.notify("Dyslexic-friendly mode OFF")

    # ------------------------------------------------------------------
    # Tab population
    # ------------------------------------------------------------------

    def _populate_dashboard(self) -> None:
        state = _load_session_state()
        energy = state.get("energy", "unknown")
        topic = state.get("topic", "none")

        due = spaced_repetition_due(TOPIC_KEYWORDS)
        struggles = struggle_topics()

        lines = [
            "[bold]Study Dashboard[/bold]",
            "",
            f"  Energy level:   {energy}",
            f"  Current topic:  {topic}",
            f"  Reviews due:    {len(due)}",
            f"  Struggle areas: {len(struggles)}",
        ]
        if struggles:
            lines.append("")
            lines.append("[bold]Top struggles:[/bold]")
            for s in struggles[:5]:
                lines.append(f"  • {s['topic']} ({s['mentions']} mentions)")

        widget = self.query_one("#dashboard-content", Static)
        widget.update("\n".join(lines))

    def _populate_review(self) -> None:
        table = self.query_one("#review-table", DataTable)
        table.add_columns("Topic", "Last Studied", "Days Ago", "Review Type")

        for item in spaced_repetition_due(TOPIC_KEYWORDS):
            table.add_row(
                item["topic"],
                item.get("last_studied") or "never",
                str(item.get("days_ago") or "—"),
                item.get("review_type", ""),
            )

    def _populate_concepts(self) -> None:
        table = self.query_one("#concepts-table", DataTable)
        table.add_columns("Name", "Domain", "Description")

        for concept in list_concepts():
            table.add_row(concept.name, concept.domain, concept.description)

    def _populate_sessions(self) -> None:
        table = self.query_one("#sessions-table", DataTable)
        table.add_columns("Topic", "Sessions", "Total Min", "Avg Min")

        for stat in get_study_session_stats():
            table.add_row(
                stat.get("topic") or "unknown",
                str(stat.get("sessions", 0)),
                str(round(stat.get("total_minutes") or 0)),
                str(round(stat.get("avg_minutes") or 0)),
            )

    def _populate_studycards(self) -> None:
        content = self.query_one("#studycards-content", Static)
        courses = discover_directories(self._study_dirs)

        if not courses:
            content.update(
                "[bold]Study Cards[/bold]\n\n"
                "  No courses found.\n\n"
                "  Configure directories in ~/.config/studyctl/config.yaml:\n"
                "    review:\n"
                "      directories:\n"
                "        - ~/Desktop/ZTM-DE/downloads\n"
                "        - ~/Desktop/Python/downloads\n\n"
                "  Or press [bold]f[/bold] for flashcards / [bold]z[/bold] for quiz"
                " and select a directory."
            )
            return

        lines = [
            "[bold]Study Cards[/bold]\n",
            f"  Found {len(courses)} course(s):\n",
        ]
        for name, path in courses:
            fc_dir, quiz_dir = find_content_dirs(path)
            fc_count = len(load_flashcards(fc_dir)) if fc_dir else 0
            quiz_count = len(load_quizzes(quiz_dir)) if quiz_dir else 0
            lines.append(
                f"  • [bold]{name}[/bold] — {fc_count} flashcards, {quiz_count} quiz questions"
            )

        lines.append("\n  Press [bold]f[/bold] for flashcards / [bold]z[/bold] for quiz")
        content.update("\n".join(lines))

    def _launch_study(self, mode: str = "flashcards") -> None:
        """Launch interactive study session."""
        courses = discover_directories(self._study_dirs)
        if not courses:
            self.notify(
                "No courses found. Configure review.directories in config.yaml",
                severity="error",
            )
            return

        if len(courses) == 1:
            self._start_session(courses[0], mode)
        else:
            self.push_screen(
                CoursePickerScreen(courses),
                lambda result: self._start_session(result, mode) if result else None,
            )

    def _start_session(self, course: tuple[str, Path], mode: str) -> None:
        """Start a study session for the selected course."""
        name, path = course
        fc_dir, quiz_dir = find_content_dirs(path)

        if mode == "flashcards" and fc_dir:
            cards = shuffle_items(load_flashcards(fc_dir))
        elif mode == "quiz" and quiz_dir:
            cards = shuffle_items(load_quizzes(quiz_dir))
        else:
            self.notify(
                f"No {mode} content found for {name}",
                severity="warning",
            )
            return

        if not cards:
            self.notify(f"No {mode} cards loaded", severity="warning")
            return

        from studyctl.tui.study_cards import StudyCardsTab

        # Replace studycards content with the interactive widget
        container = self.query_one("#studycards-container", Vertical)
        container.remove_children()
        container.mount(StudyCardsTab(cards=cards, course_name=name, mode=mode))

        # Switch to the tab
        tabs = self.query_one(TabbedContent)
        tabs.active = "studycards"

    def action_start_flashcards(self) -> None:
        self._launch_study("flashcards")

    def action_start_quiz(self) -> None:
        self._launch_study("quiz")
