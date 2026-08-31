"""Setup wizard — first-run configuration for studyloop.

Two prompts on the happy path, three at most, and every one of them accepts
Enter. That budget is the design: each question is a chance to lose someone, and
this tool's audience abandons setup that interrogates them.

What changed, and why
---------------------
The previous wizard asked five questions, two of which were optional third-party
integrations (NotebookLM, Obsidian — the latter defaulting to *yes*), while
asking for none of the three facts the product actually needs. Its opening line
described studyloop as syncing "Obsidian notes to NotebookLM", so the very first
sentence a new user read assumed software they may not own.

Worse, it asked where *course materials* (PDFs, slides) live but never where the
user's **notes** live, and never which topics to focus on — which is why a real
install ends up with 20 configured topics and a doctor warning that only the
first three are active.

The notes folder is OPTIONAL
----------------------------
Deliberately, and this is the part two independent design passes both got wrong.
Notes auto-generated from the transcript of a course you have not started are a
record of downloading, not of learning, and "collecting notes" is a well-known
ADHD trap. A user with no notes at all must finish setup with a working config
and a clear next step, because their study sessions are the material.

So: blank is a first-class answer here, not a degraded one.

Inference over interrogation
----------------------------
Note format is scanned, never asked. The harness is detected on PATH and only
asked about when detection is genuinely ambiguous. Focus topics are ranked from
the notes folder and offered for confirmation — inferred, but never applied
silently, because ``studyloop now``'s first recommendation must not come from a
choice the user never saw.
"""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

import click
import yaml

from studyloop.cli._shared import console
from studyloop.harnesses import HARNESSES, RELEASE_HARNESSES
from studyloop.settings import CONFIG_DIR, MAX_ACTIVE_TOPICS, get_config_path

#: Extensions treated as study notes in 0.1.0. Kept as a list rather than a
#: boolean so Office formats extend it later without a config migration.
NOTE_EXTENSIONS: tuple[str, ...] = (".md", ".txt")

#: Directory names never offered as a focus topic. A real vault is full of these
#: and suggesting `Templates` as a study topic destroys trust in the suggestion.
SCAN_EXCLUDE: frozenset[str] = frozenset(
    {
        ".git",
        ".obsidian",
        ".trash",
        "archive",
        "attachments",
        "assets",
        "excalidraw",
        "files",
        "images",
        "media",
        "node_modules",
        "templates",
        "venv",
    }
)

#: Bounds on the scan. A multi-gigabyte vault must not make setup feel hung.
SCAN_MAX_DEPTH = 3
SCAN_MAX_FILES = 5000

#: Harness binaries, in the order they are offered when detection is ambiguous.
HARNESS_BINARIES: tuple[tuple[str, str], ...] = tuple(
    (HARNESSES[name].binary, name) for name in RELEASE_HARNESSES
)


def _setup_config_path() -> Path:
    """Return setup's target config path.

    ``STUDYLOOP_CONFIG`` wins for production behaviour. ``CONFIG_DIR`` remains
    patchable for existing isolated setup tests.
    """
    if "STUDYLOOP_CONFIG" in os.environ:
        return get_config_path()
    return CONFIG_DIR / "config.yaml"


def _validate_path(value: str) -> Path:
    """Expand user and return a Path."""
    return Path(value).expanduser()


class NotesScan:
    """What a notes folder actually contains.

    Deliberately a plain object rather than a dataclass so the wizard can report
    "nothing usable here" without the caller having to special-case ``None``.
    """

    def __init__(self) -> None:
        self.file_count: int = 0
        self.extensions: set[str] = set()
        self.candidates: list[tuple[str, int]] = []
        self.truncated: bool = False
        self.is_obsidian_vault: bool = False


def _scan_notes(root: Path) -> NotesScan:
    """Count note files and rank first-level subfolders as candidate topics.

    Bounded on purpose. ``SCAN_MAX_DEPTH`` and ``SCAN_MAX_FILES`` stop a large
    vault from making first-run setup feel broken, and ``SCAN_EXCLUDE`` keeps
    ``Templates/`` and attachment folders out of the topic suggestions.
    """
    scan = NotesScan()
    if not root.is_dir():
        return scan
    scan.is_obsidian_vault = (root / ".obsidian").is_dir()

    per_folder: dict[str, int] = {}
    for path in root.rglob("*"):
        if scan.file_count >= SCAN_MAX_FILES:
            scan.truncated = True
            break
        try:
            rel = path.relative_to(root)
        except ValueError:  # pragma: no cover - rglob results are always relative
            continue
        parts = rel.parts
        if len(parts) > SCAN_MAX_DEPTH:
            continue
        if any(part.lower() in SCAN_EXCLUDE for part in parts):
            continue
        if not path.is_file() or path.suffix.lower() not in NOTE_EXTENSIONS:
            continue
        scan.file_count += 1
        scan.extensions.add(path.suffix.lower())
        if len(parts) > 1:
            per_folder[parts[0]] = per_folder.get(parts[0], 0) + 1

    # Rank by note count so the strongest evidence is offered first.
    scan.candidates = sorted(per_folder.items(), key=lambda kv: (-kv[1], kv[0]))
    return scan


def _detect_harness() -> list[str]:
    """Return the configured names of harness CLIs present on PATH."""
    return [name for binary, name in HARNESS_BINARIES if shutil.which(binary)]


def _existing_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with contextlib.suppress(yaml.YAMLError, OSError):
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _merge_managed(existing: dict, managed: dict) -> dict:
    """Overlay only the keys this wizard manages, preserving everything else.

    A re-run must never destroy hand-edited configuration. Legacy keys such as
    ``obsidian_base``, existing notebook IDs, and a 20-entry ``topics`` list all
    survive untouched unless the user explicitly answered the question that owns
    them.
    """
    merged = {**existing, **managed}
    for key, value in managed.items():
        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            merged[key] = {**existing[key], **value}
    return merged


def _default_notes_answer(existing: dict) -> str:
    """Pre-fill the notes prompt from config, so a re-run is all-Enter.

    Only ``notes_path`` is used. Legacy ``obsidian_base`` is deliberately NOT
    offered as the default: it points at a vault ROOT, whose first-level
    subfolders are things like ``Personal`` and ``Work`` rather than study
    topics. Defaulting to it made a re-run scan an entire personal vault and
    offer ``Personal`` as a topic -- caught by a test that accidentally scanned
    2,312 real notes. A legacy user types their notes folder once; their
    ``obsidian_base`` keeps working for topic-path resolution regardless, via
    ``settings.notes_base()``.

    When nothing is set the default is blank, because at that point pressing
    Enter should SKIP rather than invent a folder the user never asked for.
    """
    value = existing.get("notes_path")
    return str(value) if value else ""


@click.command(name="setup")
def setup() -> None:
    """First-run setup wizard — two questions, both optional."""
    console.print()
    console.print("[bold cyan]studyloop setup[/bold cyan]")
    console.print(
        "studyloop turns a folder of notes into a study system: spaced-repetition "
        "reviews, focused sessions, and flashcards. Press Enter to accept the "
        "suggestion in brackets.\n"
    )

    config_path = _setup_config_path()
    existing = _existing_config(config_path)
    managed: dict = {}

    # ------------------------------------------------------------------
    # Question 1 — notes location. Blank is a valid, supported answer.
    # ------------------------------------------------------------------
    console.print("[bold]Where do your study notes live?[/bold]")
    console.print("  [dim]A folder of .md or .txt files. Sub-folders become topics.[/dim]")
    console.print("  [dim]No notes yet? Leave it blank — studyloop will learn from your[/dim]")
    console.print("  [dim]study sessions instead, which is the better source anyway.[/dim]")
    notes_raw = click.prompt(
        "  Notes folder",
        default=_default_notes_answer(existing),
        show_default=True,
    ).strip()

    scan = NotesScan()
    if notes_raw:
        notes_path = _validate_path(notes_raw)
        if not notes_path.exists():
            if click.confirm(f"  {notes_path} does not exist. Create it?", default=True):
                notes_path.mkdir(parents=True, exist_ok=True)
                console.print(f"  [green]Created {notes_path}[/green]\n")
            else:
                console.print("  [dim]Left unset — you can add notes_path later.[/dim]\n")
                notes_raw = ""
        if notes_raw:
            managed["notes_path"] = str(notes_raw)
            scan = _scan_notes(notes_path)
            if scan.is_obsidian_vault:
                console.print(
                    "  [dim]Obsidian vault detected — treated as a plain markdown folder.[/dim]"
                )
            if scan.file_count:
                formats = ", ".join(sorted(scan.extensions))
                more = "+" if scan.truncated else ""
                console.print(f"  [green]Found {scan.file_count}{more} notes ({formats})[/green]\n")
            else:
                console.print(
                    "  [yellow]No .md or .txt files found there yet — that's fine.[/yellow]\n"
                )
    else:
        console.print("  [dim]No notes folder set. Your study sessions will be the source.[/dim]\n")

    # ------------------------------------------------------------------
    # Question 2 — focus topics. Asked ONLY when the scan found candidates.
    # Inferred, then confirmed: never applied silently.
    # ------------------------------------------------------------------
    if scan.candidates:
        offered = [name for name, _ in scan.candidates[:MAX_ACTIVE_TOPICS]]
        counts = ", ".join(
            f"{name} ({count})" for name, count in scan.candidates[:MAX_ACTIVE_TOPICS]
        )
        console.print(f"[bold]Focus on up to {MAX_ACTIVE_TOPICS} topics to start?[/bold]")
        console.print(f"  [dim]Ranked by note count: {counts}[/dim]")
        if len(scan.candidates) > MAX_ACTIVE_TOPICS:
            console.print(
                f"  [dim]{len(scan.candidates) - MAX_ACTIVE_TOPICS} more folders found; "
                f"add them later with 'studyloop focus set'.[/dim]"
            )
        chosen = click.prompt(
            "  Topics (comma-separated)",
            default=", ".join(offered),
            show_default=True,
        )
        topics = [t.strip() for t in chosen.split(",") if t.strip()][:MAX_ACTIVE_TOPICS]
        if topics:
            managed["topics"] = [{"name": t, "notes_path": t} for t in topics]
            console.print(f"  [green]Focusing on: {', '.join(topics)}[/green]\n")
    elif notes_raw:
        console.print(
            "  [dim]No sub-folders to suggest as topics. "
            "Set them later with 'studyloop focus set'.[/dim]\n"
        )

    # ------------------------------------------------------------------
    # Question 3 — the harness. Asked ONLY when detection is ambiguous.
    # ------------------------------------------------------------------
    detected = _detect_harness()
    if len(detected) == 1:
        managed["ai_assistant"] = detected[0]
        console.print(
            f"[dim]Found {detected[0]} on your PATH — using it for study sessions.[/dim]\n"
        )
    elif detected:
        console.print("[bold]Which AI assistant should run your study sessions?[/bold]")
        assistant = click.prompt(
            "  Assistant",
            default=str(existing.get("ai_assistant") or detected[0]),
            type=click.Choice(detected, case_sensitive=False),
            show_choices=True,
        )
        managed["ai_assistant"] = assistant
        console.print("")
    else:
        console.print(
            "[dim]No AI assistant found on your PATH. studyloop works standalone; "
            "install one later for live sessions.[/dim]\n"
        )

    # ------------------------------------------------------------------
    # Write — managed keys only, everything else preserved.
    # ------------------------------------------------------------------
    managed.setdefault("content", {})["note_extensions"] = list(NOTE_EXTENSIONS)
    merged = _merge_managed(existing, managed)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.dump(merged, default_flow_style=False, sort_keys=False))

    console.print(f"[bold green]Configuration saved to {config_path}[/bold green]")
    console.print("\n[bold]You're set.[/bold] Next:")
    console.print("  studyloop doctor --fix   — verify the install")
    if not notes_raw:
        console.print('  studyloop study "topic"  — start a session; this becomes your material')
    console.print("  studyloop web            — plans, flashcards, live sessions")
