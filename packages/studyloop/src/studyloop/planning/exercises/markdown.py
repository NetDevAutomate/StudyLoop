"""Structured Markdown (de)serialisation for exercise sets.

Same contract as study plans: the Markdown document is the source of truth, and
``parse_exercise_set(render_exercise_set(s)) == s`` for every field this module
knows about.  Multiple-choice questions are *authored in Markdown form* — GFM
task lists where ``- [x]`` marks a correct option — so a learner or an agent can
write a quiz in a text editor with no tooling.

Canonical document shape::

    ---
    id: python-decorators--closures
    plan_id: python-decorators
    topic: closures
    title: Closures
    concepts:
      - closures
    created: 2026-08-04T00:00:00+00:00
    updated: 2026-08-04T00:00:00+00:00
    ---

    # Closures

    ## Blank Slate

    ### Requirements

    - `make_counter()` returns a function that counts its own calls

    ### Rubric

    - [2] Uses a closure over a local `(check: nonlocal|\\[\\w+\\])`
      `(ask: Where does the count have to live to survive between calls?)`

    ### Reference Solution

    ```python
    def make_counter(): ...
    ```

    ## Completion

    ### Requirements
    ### Starter Code
    ### Rubric
    ### Reference Solution

    ## Multiple Choice

    ### Q1 — What keeps a closure's variable alive?

    - [ ] The global namespace `(why: globals are shared between counters)`
    - [x] A cell object held by the function

    `(ask: What would happen if two counters shared one global?)`

    ## Notes
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .models import (
    Choice,
    CodeExercise,
    Criterion,
    ExerciseSet,
    MultipleChoiceQuestion,
    utc_now_iso,
)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_CHECKBOX_RE = re.compile(r"^[-*]\s+\[( |x|X)\]\s*(.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_WEIGHT_RE = re.compile(r"^\[(\d+)\]\s*")
_FENCE_RE = re.compile(r"^```\s*([\w+-]*)\s*$")
_Q_HEADING_RE = re.compile(r"^Q?(\d+)?\s*(?:[—–-]\s*)?(.*)$")  # noqa: RUF001

#: ``  `(key: value)`  `` annotations, the same convention milestones use for
#: ``(concepts: ...)``.  Order-independent and strippable from the title.
_ANNOTATION_RE = re.compile(r"`\((check|forbid|ask|why)\s*:\s*(.*?)\)`", re.IGNORECASE | re.DOTALL)

_KNOWN_SECTIONS = {
    "blank slate",
    "completion",
    "multiple choice",
    "notes",
}

_SUB_REQUIREMENTS = "requirements"
_SUB_STARTER = "starter code"
_SUB_RUBRIC = "rubric"
_SUB_REFERENCE = "reference solution"

PLACEHOLDER_REQUIREMENTS = "_No requirements authored yet._"
PLACEHOLDER_RUBRIC = "_No rubric criteria yet — attempts cannot be scored._"
PLACEHOLDER_REFERENCE = "_No reference solution recorded._"
PLACEHOLDER_QUESTIONS = "_No multiple-choice questions yet._"
PLACEHOLDER_NOTES = "_No notes._"
PLACEHOLDER_BLANK_SLATE = "_No blank-slate exercise yet._"
PLACEHOLDER_COMPLETION = "_No completion exercise yet._"

_PLACEHOLDERS = frozenset(
    {
        PLACEHOLDER_REQUIREMENTS,
        PLACEHOLDER_RUBRIC,
        PLACEHOLDER_REFERENCE,
        PLACEHOLDER_QUESTIONS,
        PLACEHOLDER_NOTES,
        PLACEHOLDER_BLANK_SLATE,
        PLACEHOLDER_COMPLETION,
    }
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_frontmatter(text: str) -> tuple[dict, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    try:
        import yaml

        loaded = yaml.safe_load(raw)
    except Exception:
        loaded = None
    if not isinstance(loaded, dict):
        loaded = _naive_frontmatter(raw)
    return loaded, body


def _naive_frontmatter(raw: str) -> dict:
    data: dict = {}
    current: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current:
            data[current].append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value:
            data[key] = value
            current = None
        else:
            data[key] = []
            current = key
    return data


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.strip("[]").split(",") if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def _as_scalar_str(value) -> str:
    """Stringify a frontmatter scalar without losing ISO-8601 shape."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _split_sections(body: str) -> tuple[str, dict[str, list[str]], list[str]]:
    """Split into ``(h1, {h2_lower: lines}, unknown)``, fence-aware."""
    title = ""
    sections: dict[str, list[str]] = {}
    unknown: list[str] = []
    current: list[str] | None = None
    in_fence = False

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            if current is not None:
                current.append(line)
            continue
        if not in_fence and stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
            current = None
            continue
        if not in_fence and stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if heading in _KNOWN_SECTIONS:
                current = sections.setdefault(heading, [])
            else:
                unknown.append(line)
                current = unknown
            continue
        if current is None:
            if stripped:
                unknown.append(line)
            continue
        current.append(line)

    return title, sections, unknown


def _subsection_items(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group ``###`` blocks, preserving heading case (question prompts are data)."""
    out: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not in_fence and stripped.startswith("### "):
            current = []
            out.append((stripped[4:].strip(), current))
            continue
        if current is not None:
            current.append(line)
    return out


def _bullets(lines: list[str], *, include_checkboxes: bool = False) -> list[str]:
    items: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not include_checkboxes and _CHECKBOX_RE.match(stripped):
            continue
        match = _BULLET_RE.match(stripped)
        if match:
            items.append(match.group(1).strip())
    return [item for item in items if item not in _PLACEHOLDERS]


def _prose(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    return "" if text in _PLACEHOLDERS else text


def _first_code_block(lines: list[str]) -> tuple[str, str]:
    """Return ``(code, language)`` for the first fenced block in ``lines``."""
    code: list[str] = []
    language = ""
    in_fence = False
    for line in lines:
        match = _FENCE_RE.match(line.strip())
        if match and not in_fence:
            in_fence = True
            language = match.group(1) or ""
            continue
        if in_fence and line.strip().startswith("```"):
            break
        if in_fence:
            code.append(line)
    return "\n".join(code).strip("\n"), language


def _annotations(text: str) -> tuple[str, dict[str, str]]:
    """Strip ``` `(key: value)` ``` annotations, returning ``(clean, values)``."""
    found: dict[str, str] = {}
    for match in _ANNOTATION_RE.finditer(text):
        key = match.group(1).lower()
        value = " ".join(match.group(2).split()).strip()
        # First annotation wins, so a duplicated key cannot silently override.
        found.setdefault(key, value)
    clean = _ANNOTATION_RE.sub("", text)
    return " ".join(clean.split()).strip(), found


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_criterion(text: str) -> Criterion:
    """Parse one rubric bullet: ``[weight] Title `(check: …)` `(ask: …)```."""
    body = text.strip()
    weight = 1
    match = _WEIGHT_RE.match(body)
    if match:
        weight = int(match.group(1))
        body = body[match.end() :]
    title, notes = _annotations(body)
    # Trailing separators left behind once annotations are removed.
    title = title.strip().rstrip("—–-").strip()  # noqa: RUF001
    title = re.sub(r"\*\*(.*?)\*\*", r"\1", title).strip()
    return Criterion(
        title=title or "Unnamed criterion",
        weight=weight,
        check=notes.get("check", ""),
        forbid=notes.get("forbid", ""),
        ask=notes.get("ask", ""),
    )


def _parse_code_exercise(kind: str, lines: list[str]) -> CodeExercise | None:
    """Parse a ``## Blank Slate`` / ``## Completion`` block."""
    subs = {heading.lower(): block for heading, block in _subsection_items(lines)}
    if not subs:
        return None
    requirements = _bullets(subs.get(_SUB_REQUIREMENTS, []))
    rubric = [parse_criterion(item) for item in _bullets(subs.get(_SUB_RUBRIC, []))]
    starter, starter_lang = _first_code_block(subs.get(_SUB_STARTER, []))
    reference, ref_lang = _first_code_block(subs.get(_SUB_REFERENCE, []))
    if not (requirements or rubric or starter or reference):
        return None
    # A blank slate must not carry starter code; if a document supplies some,
    # honour the document's intent by treating the exercise as a completion.
    resolved_kind = kind
    if kind == "blank_slate" and starter.strip():
        resolved_kind = "completion"
    return CodeExercise(
        kind=resolved_kind,
        title=kind.replace("_", " ").title(),
        requirements=requirements,
        starter_code=starter,
        rubric=rubric,
        reference_solution=reference,
        language=starter_lang or ref_lang or "python",
    )


def _parse_questions(lines: list[str]) -> list[MultipleChoiceQuestion]:
    """Parse ``### Qn — prompt`` blocks with GFM task-list choices."""
    out: list[MultipleChoiceQuestion] = []
    for heading, block in _subsection_items(lines):
        match = _Q_HEADING_RE.match(heading.strip())
        prompt = (match.group(2) if match else heading).strip() or heading.strip()
        choices: list[Choice] = []
        for raw in block:
            checkbox = _CHECKBOX_RE.match(raw.strip())
            if not checkbox:
                continue
            text, notes = _annotations(checkbox.group(2))
            choices.append(
                Choice(
                    text=text.strip().rstrip("—–-").strip(),  # noqa: RUF001
                    correct=checkbox.group(1).lower() == "x",
                    why=notes.get("why", ""),
                )
            )
        # A question-level `(ask: …)` may sit on its own line below the choices.
        _, question_notes = _annotations(
            "\n".join(line for line in block if not _CHECKBOX_RE.match(line.strip()))
        )
        if prompt or choices:
            out.append(
                MultipleChoiceQuestion(
                    prompt=prompt,
                    choices=choices,
                    ask=question_notes.get("ask", ""),
                )
            )
    return out


def parse_exercise_set(text: str, *, set_id: str = "") -> ExerciseSet:
    """Parse a structured Markdown document into an :class:`ExerciseSet`."""
    meta, body = _load_frontmatter(text)
    title_from_body, sections, unknown = _split_sections(body)

    topic = str(meta.get("topic") or title_from_body or "untitled").strip()
    title = str(meta.get("title") or title_from_body or topic).strip()
    resolved_id = str(meta.get("id") or set_id or "").strip()

    notes = _prose(sections.get("notes", []))
    if unknown:
        leftover = _prose(unknown)
        notes = f"{notes}\n\n{leftover}".strip() if notes else leftover

    return ExerciseSet(
        set_id=resolved_id,
        topic=topic,
        title=title,
        plan_id=str(meta.get("plan_id") or "").strip(),
        concepts=_as_list(meta.get("concepts")),
        created=_as_scalar_str(meta.get("created")) or utc_now_iso(),
        updated=_as_scalar_str(meta.get("updated")) or utc_now_iso(),
        blank_slate=_parse_code_exercise("blank_slate", sections.get("blank slate", [])),
        completion=_parse_code_exercise("completion", sections.get("completion", [])),
        multiple_choice=_parse_questions(sections.get("multiple choice", [])),
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_criterion(criterion: Criterion) -> str:
    """Render one rubric criterion as a Markdown bullet."""
    line = f"- [{criterion.weight}] {criterion.title}"
    if criterion.check:
        line += f" `(check: {criterion.check})`"
    if criterion.forbid:
        line += f" `(forbid: {criterion.forbid})`"
    if criterion.ask:
        line += f" `(ask: {criterion.ask})`"
    return line


def render_question(question: MultipleChoiceQuestion, number: int) -> list[str]:
    """Render one multiple-choice question in authored Markdown form."""
    out = [f"### Q{number} — {question.prompt}", ""]
    for choice in question.choices:
        box = "x" if choice.correct else " "
        line = f"- [{box}] {choice.text}"
        if choice.why:
            line += f" `(why: {choice.why})`"
        out.append(line)
    out.append("")
    if question.ask:
        out.append(f"`(ask: {question.ask})`")
        out.append("")
    return out


def _render_code_exercise(
    exercise: CodeExercise | None,
    *,
    heading: str,
    placeholder: str,
    with_starter: bool,
) -> list[str]:
    out = [f"## {heading}", ""]
    if exercise is None:
        out.extend([placeholder, ""])
        return out

    out.extend(["### Requirements", ""])
    if exercise.requirements:
        out.extend(f"- {item}" for item in exercise.requirements)
    else:
        out.append(PLACEHOLDER_REQUIREMENTS)
    out.append("")

    if with_starter:
        out.extend(["### Starter Code", "", f"```{exercise.language}"])
        out.append(exercise.starter_code)
        out.extend(["```", ""])

    out.extend(["### Rubric", ""])
    if exercise.rubric:
        out.extend(render_criterion(c) for c in exercise.rubric)
    else:
        out.append(PLACEHOLDER_RUBRIC)
    out.append("")

    out.extend(["### Reference Solution", ""])
    if exercise.reference_solution:
        out.append(f"```{exercise.language}")
        out.append(exercise.reference_solution)
        out.append("```")
    else:
        out.append(PLACEHOLDER_REFERENCE)
    out.append("")
    return out


def redacted_copy(exercise_set: ExerciseSet) -> ExerciseSet:
    """Return a copy of ``exercise_set`` that is safe to show a learner.

    Redaction by *construction*, not by pattern-stripping the rendered text: a
    new object is built carrying only the fields a learner may see, and then
    rendered. A blacklist regex over the document would silently miss a new
    field the day someone adds one; this cannot, because anything not copied is
    absent.

    What is removed, and why each one is an answer key:

    * ``reference_solution`` — the solution itself.
    * ``Criterion.check`` / ``forbid`` — the regex that recognises a correct
      solution is a partial solution.
    * ``Choice.correct`` — which option is right.
    * ``Choice.why`` — written about a *distractor*, so it identifies the
      distractors, and by elimination the answer.
    * ``MultipleChoiceQuestion.ask`` — authored as the follow-up for someone who
      got it wrong, so it hints at the answer before the attempt.
    """

    def _redact_code(exercise: CodeExercise | None) -> CodeExercise | None:
        if exercise is None:
            return None
        return CodeExercise(
            kind=exercise.kind,
            title=exercise.title,
            requirements=list(exercise.requirements),
            starter_code=exercise.starter_code,
            rubric=[Criterion(title=c.title, weight=c.weight) for c in exercise.rubric],
            reference_solution="",
            language=exercise.language,
        )

    return ExerciseSet(
        set_id=exercise_set.set_id,
        topic=exercise_set.topic,
        title=exercise_set.title,
        plan_id=exercise_set.plan_id,
        concepts=list(exercise_set.concepts),
        created=exercise_set.created,
        updated=exercise_set.updated,
        blank_slate=_redact_code(exercise_set.blank_slate),
        completion=_redact_code(exercise_set.completion),
        multiple_choice=[
            MultipleChoiceQuestion(
                prompt=question.prompt,
                choices=[Choice(text=choice.text) for choice in question.choices],
                ask="",
            )
            for question in exercise_set.multiple_choice
        ],
        notes=exercise_set.notes,
    )


def render_for_learner(exercise_set: ExerciseSet) -> str:
    """Render the document with every answer removed — the attempt-time view."""
    return render_exercise_set(redacted_copy(exercise_set))


def render_exercise_set(exercise_set: ExerciseSet) -> str:
    """Render an :class:`ExerciseSet` as its canonical Markdown document.

    This is the *authoring* view and includes reference solutions and marked
    answers. Use :func:`render_for_learner` for anything a learner will see.
    """
    out = [
        "---",
        f"id: {exercise_set.set_id}",
        f"plan_id: {exercise_set.plan_id}",
        f"topic: {exercise_set.topic}",
        f"title: {exercise_set.title}",
    ]
    if exercise_set.concepts:
        out.append("concepts:")
        out.extend(f"  - {c}" for c in exercise_set.concepts)
    else:
        out.append("concepts: []")
    out.extend(
        [
            f"created: {exercise_set.created}",
            f"updated: {exercise_set.updated}",
            "---",
            "",
            f"# {exercise_set.title}",
            "",
        ]
    )

    out.extend(
        _render_code_exercise(
            exercise_set.blank_slate,
            heading="Blank Slate",
            placeholder=PLACEHOLDER_BLANK_SLATE,
            with_starter=False,
        )
    )
    out.extend(
        _render_code_exercise(
            exercise_set.completion,
            heading="Completion",
            placeholder=PLACEHOLDER_COMPLETION,
            with_starter=True,
        )
    )

    out.extend(["## Multiple Choice", ""])
    if exercise_set.multiple_choice:
        for number, question in enumerate(exercise_set.multiple_choice, 1):
            out.extend(render_question(question, number))
    else:
        out.extend([PLACEHOLDER_QUESTIONS, ""])

    out.extend(["## Notes", "", exercise_set.notes or PLACEHOLDER_NOTES, ""])
    return "\n".join(out)
