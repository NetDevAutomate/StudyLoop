"""Import generated flashcard and quiz artefacts into course review directories."""

from __future__ import annotations

import filecmp
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

from studyctl.content.storage import (
    get_course_dir,
    load_course_metadata,
    save_course_metadata,
    slugify,
)

ArtefactKind = Literal["flashcards", "quizzes"]
ImportAction = Literal["imported", "skipped", "invalid"]


@dataclass(frozen=True)
class ImportResult:
    """Outcome for one generated review artefact."""

    source: Path
    destination: Path | None
    kind: ArtefactKind
    action: ImportAction
    item_count: int
    message: str = ""

    def to_json_dict(self) -> dict[str, str | int | None]:
        data = asdict(self)
        data["source"] = str(self.source)
        data["destination"] = str(self.destination) if self.destination else None
        return data


def import_review_artefacts(
    *,
    source_dir: Path,
    base_path: Path,
    course: str,
    dry_run: bool = False,
) -> list[ImportResult]:
    """Validate and import generated flashcard/quiz JSON artefacts."""
    course_slug = slugify(course)
    if not course_slug:
        msg = "Course must contain at least one alphanumeric character."
        raise ValueError(msg)

    source = source_dir.expanduser()
    if not source.is_dir():
        msg = f"Source directory does not exist: {source}"
        raise FileNotFoundError(msg)

    course_dir = (
        base_path.expanduser() / course_slug if dry_run else get_course_dir(base_path, course_slug)
    )
    results: list[ImportResult] = []
    for path in _iter_review_json(source):
        kind = _kind_for_file(path)
        validation_error, item_count = _validate_review_json(path, kind)
        if validation_error:
            results.append(
                ImportResult(
                    source=path,
                    destination=None,
                    kind=kind,
                    action="invalid",
                    item_count=0,
                    message=validation_error,
                )
            )
            continue

        destination = course_dir / kind / path.name
        if destination.exists() and filecmp.cmp(path, destination, shallow=False):
            results.append(
                ImportResult(
                    source=path,
                    destination=destination,
                    kind=kind,
                    action="skipped",
                    item_count=item_count,
                    message="unchanged",
                )
            )
            continue

        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

        results.append(
            ImportResult(
                source=path,
                destination=destination,
                kind=kind,
                action="imported",
                item_count=item_count,
            )
        )

    if not dry_run:
        _record_import_metadata(course_dir, source, results)

    return results


def _iter_review_json(source_dir: Path) -> list[Path]:
    paths = [*source_dir.rglob("*flashcards.json"), *source_dir.rglob("*quiz.json")]
    return sorted({path for path in paths if path.is_file()})


def _kind_for_file(path: Path) -> ArtefactKind:
    if path.name.endswith("flashcards.json"):
        return "flashcards"
    return "quizzes"


def _validate_review_json(path: Path, kind: ArtefactKind) -> tuple[str, int]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return f"invalid JSON: {exc}", 0

    if not isinstance(data, dict):
        return "expected top-level JSON object", 0

    if kind == "flashcards":
        cards = data.get("cards")
        if not isinstance(cards, list):
            return "missing or invalid 'cards' list", 0
        for index, card in enumerate(cards):
            if not isinstance(card, dict):
                return f"card {index} must be an object", 0
            if not isinstance(card.get("front"), str) or not isinstance(card.get("back"), str):
                return f"card {index} must include string 'front' and 'back'", 0
        return "", len(cards)

    questions = data.get("questions")
    if not isinstance(questions, list):
        return "missing or invalid 'questions' list", 0
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            return f"question {index} must be an object", 0
        if not isinstance(question.get("question"), str):
            return f"question {index} must include string 'question'", 0
        options = question.get("answerOptions")
        if not isinstance(options, list) or len(options) < 2:
            return f"question {index} must include at least two answer options", 0
    return "", len(questions)


def _record_import_metadata(
    course_dir: Path,
    source_dir: Path,
    results: list[ImportResult],
) -> None:
    metadata = load_course_metadata(course_dir)
    imports = metadata.get("review_imports", [])
    if not isinstance(imports, list):
        imports = []
    imports.append(
        {
            "source_dir": str(source_dir),
            "imported_at": datetime.now(tz=UTC).isoformat(),
            "imported": sum(1 for result in results if result.action == "imported"),
            "skipped": sum(1 for result in results if result.action == "skipped"),
            "invalid": sum(1 for result in results if result.action == "invalid"),
        }
    )
    metadata["review_imports"] = imports[-20:]
    save_course_metadata(course_dir, metadata)
