# ruff: noqa
"""
Textual TUI Framework -- Pattern Reference
===========================================
Researched 2026-03-15 against Textual docs (textual.textualize.io).
Textual version in use: check `uv pip show textual` for exact version.

This file contains concrete, runnable examples for four key patterns
needed for the Socratic Study Mentor TUI implementation.
"""

# =============================================================================
# PATTERN 1: OptionList Widget -- Course Picker Modal/Overlay
# =============================================================================
#
# Key concepts:
#   - OptionList emits OptionList.OptionHighlighted and OptionList.OptionSelected
#   - OptionSelected carries: .option (the Option object), .index (int),
#     .option_list (the OptionList instance)
#   - Handler method name: on_option_list_option_selected
#   - Dynamic management: add_option(), clear_options(), replace_option_prompt()
#   - For a modal overlay, use ModalScreen (from textual.screen import ModalScreen)
#   - dismiss(result) returns data to the caller via a callback

from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Label, OptionList
from textual.widgets.option_list import Option


class CoursePickerScreen(ModalScreen[str]):
    """A modal overlay that presents a list of courses to choose from.

    Generic type [str] means dismiss() will return a string.
    The parent receives it via the callback passed to push_screen().
    """

    DEFAULT_CSS = """
    CoursePickerScreen {
        align: center middle;
    }

    CoursePickerScreen > OptionList {
        width: 60%;
        height: 60%;
        border: thick $accent;
        background: $surface;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, courses: list[str]) -> None:
        super().__init__()
        self.courses = courses

    def compose(self) -> ComposeResult:
        # Options can be added statically in compose...
        yield OptionList(
            *[Option(name, id=f"course-{i}") for i, name in enumerate(self.courses)],
            id="course-list",
        )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """User selected a course -- dismiss the modal and return the choice."""
        self.dismiss(str(event.option.prompt))

    def action_cancel(self) -> None:
        self.dismiss(None)


# Adding options dynamically (e.g., after an API call):
#
#   option_list = self.query_one("#course-list", OptionList)
#   option_list.clear_options()
#   for course in new_courses:
#       option_list.add_option(Option(course.name, id=course.slug))


# =============================================================================
# PATTERN 2: check_action + refresh_bindings -- Conditional Footer Keys
# =============================================================================
#
# Key concepts:
#   - check_action(action: str, parameters: tuple) -> bool | None
#       True  = show binding, action runs normally
#       False = HIDE binding entirely, action blocked
#       None  = show binding GREYED OUT (disabled), action blocked
#   - Call self.refresh_bindings() after state changes to update footer
#   - OR use reactive(default, bindings=True) for automatic refresh
#   - The bindings=True approach is preferred -- eliminates manual refresh calls

from textual.reactive import reactive


class QuizApp(App):
    """Demonstrates conditional key bindings based on quiz state."""

    BINDINGS = [
        ("space", "flip", "Flip Card"),
        ("n", "next_card", "Next"),
        ("r", "retry_wrong", "Retry Wrong"),  # only shown when wrong answers exist
    ]

    # bindings=True means: whenever this reactive changes, auto-call
    # refresh_bindings() which re-evaluates check_action for all bindings
    has_wrong_answers = reactive(False, bindings=True)
    card_flipped = reactive(False, bindings=True)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Question goes here", id="card")
        yield Footer()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Control which keys appear in the footer."""
        if action == "retry_wrong":
            # Only show "r" key when there are wrong answers to retry
            return self.has_wrong_answers  # True = visible, False = hidden
        if action == "flip":
            if self.card_flipped:
                return None  # greyed out -- card already flipped
        return True  # all other actions visible and enabled

    def action_flip(self) -> None:
        self.card_flipped = True
        self.query_one("#card", Label).update("Answer revealed!")
        # No need to call refresh_bindings() -- bindings=True handles it

    def action_next_card(self) -> None:
        self.card_flipped = False
        self.query_one("#card", Label).update("Next question...")

    def action_retry_wrong(self) -> None:
        if self.has_wrong_answers:
            self.has_wrong_answers = False
            self.query_one("#card", Label).update("Retrying wrong answers...")


# =============================================================================
# PATTERN 3: Widget State Management -- Swapping Content & Reactives
# =============================================================================
#
# Three approaches for swapping widget content:
#
# A) ContentSwitcher -- best for toggling between predefined views
# B) remove_children() + mount() -- best for fully dynamic content
# C) display/visibility CSS -- simplest for show/hide of existing widgets
#
# Reactive properties:
#   count = reactive(0)                    -- basic reactive
#   count = reactive(0, bindings=True)     -- auto-refreshes footer bindings
#   name = reactive("", layout=True)       -- triggers layout recalculation
#   data = reactive(None, repaint=True)    -- triggers repaint (default)
#
# Watcher naming convention: watch_<property_name>(self, new_value)
# Validator naming convention: validate_<property_name>(self, value) -> value

from textual.containers import Container, Vertical
from textual.widgets import ContentSwitcher, Static


# --- Approach A: ContentSwitcher ---
class TwoStateApp(App):
    """Switch between 'question' and 'answer' views."""

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="question-view", id="switcher"):
            yield Vertical(Label("What is 2+2?"), id="question-view")
            yield Vertical(Label("The answer is 4"), id="answer-view")
        yield Footer()

    def action_flip(self) -> None:
        switcher = self.query_one("#switcher", ContentSwitcher)
        if switcher.current == "question-view":
            switcher.current = "answer-view"
        else:
            switcher.current = "question-view"


# --- Approach B: Dynamic mount/remove ---
class DynamicSwapApp(App):
    """Swap container children dynamically."""

    def compose(self) -> ComposeResult:
        yield Container(Label("Initial content"), id="main-container")
        yield Footer()

    async def swap_content(self, new_widget) -> None:
        container = self.query_one("#main-container", Container)
        await container.remove_children()  # remove all children
        await container.mount(new_widget)  # mount replacement


# --- 2-State + Boolean State Machine ---
#
# For a flashcard app with states: QUESTION, ANSWER + wrong_answers: bool
#
# Use an enum or string reactive for the main state,
# and a boolean reactive for the secondary flag:

from enum import Enum, auto


class CardState(Enum):
    QUESTION = auto()
    ANSWER = auto()


class FlashcardWidget(Static):
    """A widget that manages card state with reactives."""

    card_state = reactive(CardState.QUESTION)
    has_wrong = reactive(False, bindings=True)

    def watch_card_state(self, state: CardState) -> None:
        """React to state changes -- update display accordingly."""
        if state == CardState.QUESTION:
            self.update("Q: What is the capital of France?")
        elif state == CardState.ANSWER:
            self.update("A: Paris")

    def flip(self) -> None:
        if self.card_state == CardState.QUESTION:
            self.card_state = CardState.ANSWER
        else:
            self.card_state = CardState.QUESTION


# =============================================================================
# PATTERN 4: Footer Bindings -- Binding Objects & Visibility Control
# =============================================================================
#
# Binding constructor:
#   Binding(key, action, description, show=True, key_display=None, priority=False)
#
#   show=True   -> displayed in footer (default)
#   show=False  -> binding works but NOT shown in footer (stealth binding)
#   priority=True -> binding takes precedence over focused widget's bindings
#
# The Footer widget reads BINDINGS from the active screen and focused widget
# chain. It calls check_action() for each binding to determine visibility.
#
# Visibility flow:
#   1. Footer collects all Binding objects from the focus chain
#   2. Filters out show=False bindings (never displayed)
#   3. For remaining bindings, calls check_action(action_name, params):
#       True  -> show in footer, action enabled
#       False -> HIDE from footer, action disabled
#       None  -> show GREYED OUT in footer, action disabled
#   4. Footer re-renders with the visible/enabled bindings
#
# When to use each:
#   - Binding(show=False): key that NEVER appears in footer (e.g., "escape")
#   - check_action returning False: key that CONDITIONALLY appears
#   - check_action returning None: key shown but GREYED OUT (disabled state)

from textual.binding import Binding


class FullExampleApp(App):
    """Complete example combining all patterns."""

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("space", "flip", "Flip", show=True),
        Binding("n", "next", "Next", show=True),
        Binding("r", "retry", "Retry Wrong", show=True),  # conditionally visible
        Binding("c", "pick_course", "Courses", show=True),
        Binding("?", "help", "Help", show=False),  # works but hidden from footer
    ]

    # bindings=True -> auto refresh_bindings on change
    wrong_count = reactive(0, bindings=True)
    card_flipped = reactive(False, bindings=True)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "retry":
            return self.wrong_count > 0  # hidden when no wrong answers
        if action == "flip":
            return None if self.card_flipped else True  # greyed when already flipped
        if action == "next":
            return True if self.card_flipped else None  # greyed until card is flipped
        return True

    def action_pick_course(self) -> None:
        """Push modal course picker, handle result via callback."""
        courses = ["Python Basics", "Data Structures", "Algorithms"]

        def on_course_selected(course: str | None) -> None:
            if course is not None:
                self.query_one("#current-course", Label).update(f"Course: {course}")

        self.push_screen(CoursePickerScreen(courses), on_course_selected)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("No course selected", id="current-course")
        yield Label("Card content here", id="card")
        yield Footer()


# =============================================================================
# SUMMARY OF KEY APIs
# =============================================================================
#
# OptionList:
#   - OptionList(*options)           constructor with initial options
#   - .add_option(Option|str)        add single option
#   - .clear_options()               remove all options
#   - .replace_option_prompt(id, p)  update option text by ID
#   - Message: OptionList.OptionSelected  (attrs: .option, .index)
#
# ModalScreen:
#   - class MyModal(ModalScreen[ReturnType])
#   - self.dismiss(result)           pop screen, return data
#   - app.push_screen(modal, callback)  push with result callback
#
# check_action:
#   - def check_action(self, action, parameters) -> bool | None
#   - True = visible+enabled, False = hidden, None = greyed out
#   - self.refresh_bindings()        manual refresh
#   - reactive(val, bindings=True)   automatic refresh on change
#
# Reactive:
#   - prop = reactive(default)
#   - prop = reactive(default, bindings=True)  auto-refresh footer
#   - watch_prop(self, new_val)      watcher method
#   - validate_prop(self, val)       validator method
#
# Widget content swapping:
#   - ContentSwitcher(initial="id")  toggle between children by ID
#   - container.remove_children()    clear all children
#   - container.mount(widget)        add new child
#   - widget.remove()                remove single widget
#
# Binding:
#   - Binding(key, action, desc, show=True/False, priority=False)
#   - show=False -> never in footer; check_action False -> conditionally hidden
