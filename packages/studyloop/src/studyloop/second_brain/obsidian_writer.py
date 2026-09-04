"""The only code in StudyLoop that writes into a learner's vault.

Deliberately one module, and deliberately small. A vault holds notes the learner
wrote by hand; a second writer somewhere else in the codebase would be a second
place for the containment and ownership rules to be forgotten. Template
installation reuses this rather than adding its own.

Three rules, enforced in this order:

1. **Containment.** The resolved target must sit under the resolved vault root.
   Checked on resolved paths, so ``..``, an absolute folder and a symlinked
   directory are all caught — the third is the one a string check misses, and it
   is a perfectly ordinary thing for a learner to have set up.
2. **Ownership.** A file is replaced only when its frontmatter carries
   StudyLoop's marker AND that marker names this projection. A learner's own note
   in the way is refused; so is the projection of a plan that has been renamed,
   because losing the note under the old name would be silent data loss.
3. **Atomicity.** Write a sibling temp file, fsync it, copy the existing mode
   across, re-check that the target has not been exchanged, then ``os.replace``.
   Obsidian watches the directory, so a partially written note is visible in the UI —
   and ``os.replace`` is only atomic within one filesystem, which is why the temp file
   is a sibling and never in ``/tmp``.

Known limitation, stated rather than papered over: an attacker who can already write
to the vault directory can exchange an ANCESTOR for a symlink between the containment
re-check and the rename. Closing that needs descriptor-relative, no-follow operations
(``openat``/``renameat`` with ``O_NOFOLLOW``), which have no portable equivalent on
Windows. The checks here narrow the window to microseconds and detect an exchange of
the target itself; they do not eliminate the ancestor case.

:func:`projection_path` returns a :class:`VaultTarget` rather than a bare path so
that the vault-relative label travels with it. Every message and every reported
path in this feature is vault-relative; deriving that string at each call site
would be one more place to accidentally leak an absolute home directory into
JSON an agent may echo.
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import yaml

from studyloop.second_brain.core import SecondBrainError
from studyloop.second_brain.projection import OWNERSHIP_KEY

if TYPE_CHECKING:
    from studyloop.second_brain.projection import ProjectionIdentity

logger = logging.getLogger(__name__)


class WriteOutcome(Enum):
    """What a write actually did.

    ``UNCHANGED`` is a first-class outcome rather than a silent no-op because the
    CLI reports it: a learner republishing at every wind-down should see that
    nothing needed rewriting.

    ``REPLACED`` exists for the same reason one level up. The writer always knew the
    difference between creating a note and overwriting one whose bytes had drifted --
    it compares them to decide whether to write at all -- but it reported both as
    ``WRITTEN``. So a learner who had typed into a projection saw the identical
    success line as someone publishing for the first time, and their words were gone
    with nothing said. A validation council found that by reading the journey
    evidence; the information was one frame below the surface that needed it.
    """

    WRITTEN = "written"
    REPLACED = "replaced"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class VaultTarget:
    """A checked write location inside a vault."""

    #: Absolute path on this machine. Never reported to a caller.
    path: Path
    #: Vault-relative POSIX label, e.g. ``Study/Plans/python-decorators.md``.
    #: This is what appears in results, messages and JSON.
    relative: str
    #: The resolved vault root the containment check was made against.
    root: Path


def _resolved_root(vault: Path) -> Path:
    root = Path(vault).expanduser()
    if not root.is_dir():
        raise SecondBrainError(
            f"Vault path is not a directory: {root}. "
            "Mount it, or point second_brain.vault_path somewhere else."
        )
    return root.resolve()


def projection_path(vault: Path, folder: str, relative: str) -> VaultTarget:
    """Resolve ``<vault>/<folder>/<relative>``, refusing any escape.

    ``relative`` is a POSIX-style path inside the StudyLoop folder, e.g.
    ``Plans/python-decorators.md``.

    The containment check runs against the resolved deepest EXISTING ancestor,
    which is what catches a symlinked ``Study`` directory pointing outside the
    vault: ``Path.resolve()`` on a path whose parents do not exist yet cannot
    follow the symlink that matters. Because a symlink can appear between this
    check and the write, :func:`write_projection` re-checks before replacing.
    """
    root = _resolved_root(vault)

    if Path(folder).is_absolute() or Path(relative).is_absolute():
        raise SecondBrainError(
            f"Refusing to write outside the vault: '{folder}/{relative}' is not a "
            "relative path inside the configured folder."
        )

    candidate = PurePosixPath(str(folder).replace("\\", "/")) / PurePosixPath(
        str(relative).replace("\\", "/")
    )
    if ".." in candidate.parts:
        raise SecondBrainError(f"Refusing to write outside the vault: '{candidate}' contains '..'.")

    target = (root / candidate).expanduser()
    probe = _nearest_existing(target)
    try:
        probe.resolve().relative_to(root)
    except ValueError as exc:
        raise SecondBrainError(
            f"Refusing to write outside the vault: '{candidate}' resolves through "
            f"{probe.name}, which is not under the configured vault."
        ) from exc

    return VaultTarget(path=target, relative=candidate.as_posix(), root=root)


def _nearest_existing(target: Path) -> Path:
    """The deepest ancestor of ``target`` that exists."""
    probe = target
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def marker_from_text(text: str) -> dict[str, Any] | None:
    """Extract a StudyLoop ownership marker from a document's frontmatter.

    ``None`` covers every "not ours" case — no frontmatter, unparseable
    frontmatter, frontmatter without the marker key, a marker that does not claim
    ownership. They are collapsed on purpose: each means ownership is unknown, and
    unknown ownership must produce the same refusal rather than a different code
    path per shape.
    """
    if not text.startswith("---\n"):
        return None
    _, _, rest = text.partition("---\n")
    frontmatter_text, separator, _ = rest.partition("\n---")
    if not separator:
        return None
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        return None
    if not isinstance(frontmatter, dict):
        return None
    marker = frontmatter.get(OWNERSHIP_KEY)
    if not isinstance(marker, dict) or marker.get("owned") is not True:
        return None
    return marker


def _file_identity(path: Path) -> tuple[int, int, int] | None:
    """A stable identity for whatever is at ``path``, or ``None`` when absent.

    Device, inode and creation-or-change time. Used to detect that the target was
    exchanged between the ownership check and the replace: a content comparison would
    miss an exchange for a file that happens to have the same bytes, and a
    modification-time comparison has second-or-worse granularity on some filesystems.
    ``lstat`` so a symlink appearing in the window is itself the change.
    """
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return (info.st_dev, info.st_ino, info.st_ctime_ns)


def read_text_if_present(path: Path) -> str | None:
    """The file's text, or ``None`` when it does not exist.

    Read-first-and-catch rather than ``exists()`` then read. Two reasons: a vault
    is a directory Obsidian and a sync client are both writing to, so the file can
    disappear between the two calls; and this repository's structural guard
    (``tests/test_no_exists_then_read_race.py``) fails any ``exists()``-then-read
    pair outright, having been bitten by exactly that shape before.

    A file that exists but cannot be decoded returns ``""`` — present, contents
    unknown — so the caller treats it as "something is there" rather than "nothing
    is there", which is the safe direction when the question is whether to
    overwrite.
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError):
        return ""


def read_marker(path: Path) -> dict[str, Any] | None:
    """Return the file's StudyLoop ownership marker, or ``None``."""
    text = read_text_if_present(path)
    if text is None:
        return None
    return marker_from_text(text)


def _assert_replaceable(
    target: VaultTarget, identity: ProjectionIdentity, existing_text: str
) -> None:
    marker = marker_from_text(existing_text)
    if marker is None:
        raise SecondBrainError(
            f"Refusing to overwrite '{target.relative}': it is not marked as "
            "StudyLoop-owned. Move or rename that note, then retry."
        )
    same_projection = (
        marker.get("kind") == identity.kind
        and marker.get("plan_id") == identity.plan_id
        and marker.get("learning_record") == identity.learning_record
    )
    if not same_projection:
        raise SecondBrainError(
            f"Refusing to overwrite '{target.relative}': its StudyLoop ownership "
            "marker belongs to a different projection."
        )


def _assert_parent_contained(target: VaultTarget, *, when: str) -> None:
    """Refuse when ``target``'s directory no longer resolves under the vault.

    Resolved on the nearest EXISTING ancestor: ``Path.resolve`` on a path whose
    directories do not exist yet cannot follow a symlink that would be followed
    once they do, so checking the unbuilt parent directly would pass exactly
    when it matters (O1). ``when`` names the call site in the message so a
    refusal says which window it caught.
    """
    ancestor = target.path.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    try:
        ancestor.resolve().relative_to(target.root)
    except ValueError as exc:
        raise SecondBrainError(
            f"Refusing to write outside the vault: '{target.relative}' no longer "
            f"resolves under the configured vault (checked {when})."
        ) from exc


@dataclass(frozen=True)
class WriteVerdict:
    """What a write WOULD do, decided without doing it.

    ``refusal`` carries the message a real write would raise, so a dry run can report
    the same refusal the learner would actually hit rather than promising a write that
    cannot happen.
    """

    outcome: WriteOutcome
    refusal: str | None = None


def classify_write(
    target: VaultTarget, rendered: str, identity: ProjectionIdentity
) -> WriteVerdict:
    """Decide the outcome of a write without performing it.

    Shares every check with :func:`write_projection` -- symlink refusal, ownership,
    byte equality -- because the alternative is a second, untested description of what
    the writer does, which is exactly how a dry run comes to disagree with reality.
    """
    path = target.path
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            return WriteVerdict(
                WriteOutcome.WRITTEN,
                f"Refusing to overwrite '{target.relative}': it is a symbolic link.",
            )
    except FileNotFoundError:
        return WriteVerdict(WriteOutcome.WRITTEN)

    existing_text = read_text_if_present(path)
    if existing_text is None:
        return WriteVerdict(WriteOutcome.WRITTEN)
    try:
        _assert_replaceable(target, identity, existing_text)
    except SecondBrainError as exc:
        return WriteVerdict(WriteOutcome.WRITTEN, str(exc))
    if existing_text == rendered:
        return WriteVerdict(WriteOutcome.UNCHANGED)
    # REPLACED, not WRITTEN (O4): the real publish distinguishes creating a
    # note from overwriting a learner's edits, and warns on the latter. A dry
    # run that said "would write" for both could not preview the one warning
    # that was added precisely so a learner is told before losing text.
    return WriteVerdict(WriteOutcome.REPLACED)


def write_projection(
    target: VaultTarget,
    rendered: str,
    identity: ProjectionIdentity,
    *,
    create_only: bool = False,
) -> WriteOutcome:
    """Install ``rendered`` at ``target``, atomically and idempotently.

    ``create_only`` is for template installation: never replace anything, even a
    file StudyLoop owns, because a template the learner has edited is theirs.
    """
    path = target.path

    # A symlink is the learner's own content, whatever it points at. Following it to
    # validate the referent's marker and then calling os.replace would destroy the
    # LINK -- a file StudyLoop never owned and cannot recreate -- while reporting
    # success. lstat, not exists(), because exists() follows.
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise SecondBrainError(
                f"Refusing to overwrite '{target.relative}': it is a symbolic link, "
                "which StudyLoop does not own. Replace it with a regular file or move "
                "it aside."
            )
    except FileNotFoundError:
        pass

    existing_text = read_text_if_present(path)
    identity_before = _file_identity(path)
    was_replaced = False

    if existing_text is not None:
        if create_only:
            raise SecondBrainError(f"'{target.relative}' already exists; leaving it alone.")
        _assert_replaceable(target, identity, existing_text)
        # Compared against the file's ACTUAL bytes, not against the content_hash
        # recorded in its marker. The marker records what StudyLoop last INTENDED
        # to write, so a projection the learner has edited by hand still carries
        # the hash of the correct content -- comparing against it would report
        # "unchanged" and leave the edit in place, silently turning the vault into
        # a second source of truth. Both sides come from the same renderer, so byte
        # equality is exact and needs no hash reasoning at all.
        if existing_text == rendered:
            logger.debug("second brain: %s is already current", target.relative)
            return WriteOutcome.UNCHANGED
        # Owned, present, and different: the learner has edited this note since
        # StudyLoop wrote it. Recorded so the caller can say so.
        was_replaced = True

    # Containment check BEFORE anything is created (O1, 2026-09-04 review):
    # mkdir(parents=True) used to run first, so an ancestor swapped for a
    # symlink between projection_path and here created directories OUTSIDE the
    # vault before the file write was refused. Checked on the nearest EXISTING
    # ancestor, because resolve() on a not-yet-created path cannot see where a
    # hostile symlink would send its children.
    _assert_parent_contained(target, when="before creating directories")

    path.parent.mkdir(parents=True, exist_ok=True)

    # Re-check containment now that the parents exist: a symlink could have been
    # created since projection_path ran. The residual TOCTOU window is accepted --
    # it cannot be closed with POSIX path APIs alone -- but narrowing it to the
    # microseconds before the replace is worth the extra call.
    _assert_parent_contained(target, when="after creating directories")

    # Replace-by-rename creates a NEW inode, so an existing note's mode has to be
    # copied across or a learner who tightened its permissions silently loses that.
    # A file that vanished between the read above and this stat is a new file for
    # mode purposes (the inode-identity check below still refuses the replace);
    # any OTHER stat failure on an existing note is refused rather than defaulted
    # (O7): silently re-opening a note the learner had locked down to 0o600 as
    # 0o644 is exactly the loss the copy exists to prevent.
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        existing_mode = 0o644
    except OSError as exc:
        raise SecondBrainError(
            f"Could not read the permissions of '{target.relative}': {exc}. "
            "Refusing to replace it, so its mode cannot be silently widened."
        ) from exc

    # delete=False, and closed by the `with handle:` block below before the
    # rename: a context manager here would delete the file we are about to
    # os.replace into place.
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, existing_mode)
        # Re-check what is at the target NOW, not what was there when ownership was
        # validated. A vault is a directory Obsidian and a sync client are both
        # writing to, so a note can appear -- or be replaced by one the learner
        # owns -- in the window between the two, and os.replace would delete it
        # without ever having seen its frontmatter. Compared by inode identity
        # rather than by content, because the content could coincide.
        if _file_identity(path) != identity_before:
            temp_path.unlink(missing_ok=True)
            raise SecondBrainError(
                f"Refusing to overwrite '{target.relative}': it changed while StudyLoop "
                "was preparing the new version. Nothing was written; try again."
            )
        # And containment one last time, immediately before the replace (O1):
        # everything above narrowed the window; this closes it to the rename
        # itself, which is as far as POSIX path APIs can take it.
        try:
            _assert_parent_contained(target, when="before the replace")
        except SecondBrainError:
            temp_path.unlink(missing_ok=True)
            raise
        os.replace(temp_path, path)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise SecondBrainError(
            f"Could not write '{target.relative}': {exc}. The existing note was left untouched."
        ) from exc
    return WriteOutcome.REPLACED if was_replaced else WriteOutcome.WRITTEN


def read_user_note(target: VaultTarget) -> str | None:
    """Read a user-owned sibling note, or ``None`` when it is absent.

    Read-only by construction: there is no write path for a file StudyLoop does
    not own, and a missing note is a normal answer rather than an error — a
    learner who has not written anything yet has nothing to pull.
    """
    try:
        return target.path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise SecondBrainError(f"Could not read '{target.relative}': {exc}") from exc


__all__ = [
    "VaultTarget",
    "WriteOutcome",
    "WriteVerdict",
    "classify_write",
    "marker_from_text",
    "projection_path",
    "read_marker",
    "read_text_if_present",
    "read_user_note",
    "write_projection",
]
