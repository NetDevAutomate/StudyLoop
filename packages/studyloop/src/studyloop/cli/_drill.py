"""``studyloop drill <setup|check|cleanup> <module>/<deck>/<task>`` -- the MVP's only execution
surface for module drills (proposal §7, drill-runner spec).

Exported as :data:`drill_group`; lane W registers it in ``cli/__init__.py`` (wave 2). One
invocation runs exactly one phase of one drill through the §5.5 runner:

1. resolve ``<module>/<deck>/<task>`` -- the installed module (lane C's lockfile, behind
   :func:`locate_installed_module`), the deck file under the snapshot's ``decks/`` whose
   ``id`` matches, the task whose ``id`` matches, and the phase's command
   (``setupCommand`` / ``command`` / ``cleanupCommand``), split into argv by ``shlex``;
2. find or open the attempt (``setup`` opens a new one; ``check`` reuses the open one or
   opens one; ``cleanup`` needs an open one and always closes it);
3. validate argv and script path and compute the digest **before** asking -- a command the
   runner would refuse is never shown as something to consent to;
4. show the consent text (phase, target, exact argv, script sha256) and ask. There is no
   ``--yes``. Declining exits 2 and runs nothing;
5. run the phase; print its result first; then post the typed fields to the mentor hop and
   print exactly one line -- ``Mentor told.`` or ``Mentor not told: <reason>``;
6. record the ``practice_check_events`` row and the attempt's own evidence; close the
   attempt when the phase was ``cleanup`` (whatever its exit) or a failed ``setup``.

Exit status: 0 passed, 1 failed (task not complete) or a refusal/usage problem reported by
Click, 2 error (timeout, cap, non-zero setup/cleanup, check could not run) or consent declined.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shlex
import stat
from pathlib import Path
from typing import TYPE_CHECKING

import click

from studyloop.content.schemas import SLUG_PATTERN, PracticeDeck
from studyloop.modules import hop, runner
from studyloop.modules.attempt import (
    Attempt,
    AttemptStore,
    DeliveryOutcome,
    DrillIdentity,
    ExitClass,
    InstalledModule,
    ModuleNotInstalledError,
    Phase,
    PhaseResult,
    RefusalError,
    SidecarError,
    record_phase,
)
from studyloop.modules.consent import ConsentLedger, describe_consent

if TYPE_CHECKING:
    from studyloop.content.schemas import PracticeTask

__all__ = [
    "ModuleNotInstalledError",
    "attempts_root",
    "drill_group",
    "locate_installed_module",
    "module_prerequisites",
    "run_drill_phase",
]

_SLUG = re.compile(SLUG_PATTERN)

_PHASE_FIELD = {
    Phase.SETUP: "setup_command",
    Phase.CHECK: "command",
    Phase.CLEANUP: "cleanup_command",
}


def attempts_root() -> Path:
    """Where attempt directories live: ``<state dir>/module-attempts`` (per-learner data)."""
    from studyloop.settings import load_settings

    return load_settings().state_dir / "module-attempts"


def locate_installed_module(module_id: str) -> InstalledModule:
    """Resolve an installed module through lane C's ``modules/store.py``.

    C exports ``load_lockfile()``, ``LockEntry`` (``id``, ``version``, ``digest`` in its
    canonical ``sha256:<64 hex>`` form -- the value the mentor envelope carries verbatim) and
    ``snapshot_dir(entry)`` (C2 brief, cross-lane facts). The import is lazy and by name
    because the store had not merged when this was written: until it lands, every lookup
    raises :class:`ModuleNotInstalledError` naming the gap, and the test suite points this
    seam at a fixture module instead. The coordinator reconciles the attribute names at merge.
    """
    try:
        store = importlib.import_module("studyloop.modules.store")
    except ModuleNotFoundError as exc:
        raise ModuleNotInstalledError(
            f"{module_id}: the module store (lane C, modules/store.py) is not in this build"
        ) from exc
    for entry in store.load_lockfile():
        if getattr(entry, "id", None) == module_id:
            return InstalledModule(
                module_id=module_id,
                module_digest=str(entry.digest),
                snapshot_dir=Path(store.snapshot_dir(entry)),
            )
    raise ModuleNotInstalledError(module_id)


def parse_drill_ref(ref: str) -> tuple[str, str, str]:
    """``<module>/<deck>/<task>``: exactly three lowercase slugs."""
    parts = ref.split("/")
    if len(parts) != 3 or not all(_SLUG.match(part) for part in parts):
        raise click.UsageError(
            f"drill reference {ref!r} must be <module>/<deck>/<task>, three lowercase slugs"
        )
    return parts[0], parts[1], parts[2]


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def load_drill(snapshot_dir: Path, deck_id: str, task_id: str) -> tuple[PracticeDeck, PracticeTask]:
    """Find the deck with ``id == deck_id`` under ``decks/`` and its task ``task_id``."""
    decks_dir = snapshot_dir / "decks"
    seen: list[str] = []
    for path in sorted(decks_dir.glob("*.json")) if decks_dir.is_dir() else []:
        if not _is_regular_file(path):
            continue  # MC013: only regular files are module content
        try:
            deck = PracticeDeck.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise click.ClickException(f"deck {path.name} does not validate: {exc}") from exc
        if deck.id is not None:
            seen.append(deck.id)
        if deck.id != deck_id:
            continue
        for task in deck.tasks:
            if task.id == task_id:
                return deck, task
        task_ids = [task.id for task in deck.tasks if task.id]
        raise click.ClickException(
            f"deck {deck_id!r} has no task {task_id!r} (tasks: {', '.join(task_ids) or 'none'})"
        )
    raise click.ClickException(
        f"module has no deck {deck_id!r} (decks: {', '.join(seen) or 'none'})"
    )


def module_prerequisites(snapshot_dir: Path) -> tuple[str, ...]:
    """``prerequisites[].id`` from the installed module's ``module.yaml``, in declared order.

    Read through lane C's ``ModuleManifest`` (``extra: forbid``). The snapshot passed
    ``module check`` at install, so a manifest that no longer validates means the snapshot
    was altered: refuse the phase rather than run it with an empty tool list.
    """
    import yaml
    from pydantic import ValidationError

    from studyloop.modules.manifest import ModuleManifest

    manifest_path = snapshot_dir / "module.yaml"
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        manifest = ModuleManifest.model_validate(raw)
    except (OSError, ValueError, yaml.YAMLError, ValidationError) as exc:
        raise click.ClickException(
            f"module.yaml in the installed snapshot does not validate ({exc}); "
            "re-run `studyloop module add` from the module's source"
        ) from exc
    return tuple(prerequisite.id for prerequisite in manifest.prerequisites)


def phase_argv(task: PracticeTask, phase: Phase, task_ref: str) -> tuple[str, ...]:
    """The phase's command from the task's verification block, split into literal argv."""
    verification = task.verification
    command = getattr(verification, _PHASE_FIELD[phase], "") if verification else ""
    if verification is None or verification.kind != "command" or not command.strip():
        raise click.ClickException(f"{task_ref} declares no {phase.value} phase")
    try:
        return tuple(shlex.split(command, posix=True))
    except ValueError as exc:
        raise click.ClickException(
            f"{phase.value} command cannot be split into argv: {exc}"
        ) from exc


def _echo_result(result: PhaseResult) -> None:
    click.echo(f"{result.phase.value}: {result.message}")
    if result.stdout:
        click.echo(result.stdout.rstrip("\n"))
    if result.stderr:
        click.echo("stderr:")
        click.echo(result.stderr.rstrip("\n"))
    if result.truncated:
        click.echo(f"[output truncated at the {result.cap_hit} cap]")


def _echo_outcome(outcome: DeliveryOutcome) -> None:
    """The one mentor line (M0): ``Mentor told.`` or ``Mentor not told: <reason>``."""
    if outcome.delivered:
        click.echo("Mentor told.")
        return
    detail = f" ({outcome.reason})" if outcome.reason else ""
    click.echo(f"Mentor not told: {outcome.status}{detail}")


def _exit_status(result: PhaseResult) -> int:
    if result.exit_class is ExitClass.PASSED:
        return 0
    if result.exit_class is ExitClass.FAILED:
        return 1
    return 2


def _open_attempt(
    store: AttemptStore, phase: Phase, drill: DrillIdentity, snapshot_dir: Path
) -> tuple[Attempt, bool]:
    """Return ``(attempt, opened_here)`` per phase: setup opens, check reuses-or-opens,
    cleanup needs one."""
    current = store.current(drill)
    if phase is Phase.SETUP:
        if current is not None:
            raise click.ClickException(
                f"attempt {current.attempt_id} is already open for {drill.drill_id}; run "
                f"`studyloop drill cleanup {drill.module_id}/{drill.drill_id}` first"
            )
        return store.open(drill, snapshot_dir=snapshot_dir), True
    if phase is Phase.CLEANUP:
        if current is None:
            raise click.ClickException(
                f"no open attempt for {drill.module_id}/{drill.drill_id}; nothing to clean up"
            )
        return current, False
    if current is not None:
        return current, False
    return store.open(drill, snapshot_dir=snapshot_dir), True


def run_drill_phase(phase: Phase, ref: str) -> int:
    """Run one phase of one drill; returns the process exit status (see module docstring)."""
    module_id, deck_id, task_id = parse_drill_ref(ref)
    try:
        installed = locate_installed_module(module_id)
    except ModuleNotInstalledError as exc:
        raise click.ClickException(
            f"module {module_id!r} is not installed ({exc}); `studyloop module list` shows what is"
        ) from exc
    _deck, task = load_drill(installed.snapshot_dir, deck_id, task_id)
    argv = phase_argv(task, phase, ref)
    timeout = task.verification.timeout_seconds if task.verification else 60
    drill = DrillIdentity(
        module_id=module_id,
        module_digest=installed.module_digest,
        deck_id=deck_id,
        task_id=task_id,
    )

    # Lane C's manifest is on main: the tools the module declares (`prerequisites[].id`,
    # each in core's enum -- MC005 at install) are what core resolves on the learner's
    # PATH and exposes to the child, and nothing else (M1 PATH ruling).
    prerequisites = module_prerequisites(installed.snapshot_dir)

    # Refuse what the runner would refuse BEFORE anyone is asked to consent to it: argv
    # (tokens, NUL, size), the script path (MC013) and the declared tools on the PATH.
    try:
        runner.validate_argv(argv)
        script = runner.resolve_script(installed.snapshot_dir, argv[0])
        runner.resolve_prerequisites(prerequisites)
    except RefusalError as exc:
        raise click.ClickException(str(exc)) from exc
    digest = runner.script_digest(script)

    store = AttemptStore(root=attempts_root())
    attempt, opened_here = _open_attempt(store, phase, drill, installed.snapshot_dir)

    click.echo(describe_consent(attempt, phase, argv, script_digest=digest))
    if not click.confirm("Run this phase now?", default=False):
        click.echo("Not confirmed -- nothing executed.")
        if opened_here:
            store.close(attempt, reason=f"{phase.value} not confirmed; nothing ran")
        return 2

    ledger = ConsentLedger()
    consent = ledger.issue(attempt, phase, argv, script_digest=digest)
    try:
        result = runner.run_phase(
            attempt,
            phase,
            argv,
            consent=consent,
            ledger=ledger,
            timeout_seconds=timeout,
            prerequisites=prerequisites,
        )
    except RefusalError as exc:
        if opened_here:
            store.close(attempt, reason=f"{phase.value} refused before spawn: {exc}")
        raise click.ClickException(str(exc)) from exc

    _echo_result(result)
    fields = hop.check_result_fields(attempt, result)
    outcome = hop.post_check_result(fields)
    _echo_outcome(outcome)

    if record_phase(attempt, result, delivery=outcome) is None:
        click.echo(
            "practice_check event not recorded: the sessions database is unavailable", err=True
        )
    # The child has exited and been reaped (run_phase returned): safe to write the sidecar.
    try:
        store.record_evidence(attempt, result, delivery=outcome)
        if phase is Phase.CLEANUP or (
            phase is Phase.SETUP and result.exit_class is not ExitClass.PASSED
        ):
            store.close(attempt, reason=result.message)
    except SidecarError as exc:
        raise click.ClickException(f"attempt record not updated: {exc}") from exc
    return _exit_status(result)


@click.group("drill")
def drill_group() -> None:
    """Run one phase of an installed module's drill, with consent, inside your session.

    DRILL is <module>/<deck>/<task> -- the module id from `studyloop module list`, the
    deck id and the task id from its decks. Each phase is one executable under the
    module's scripts/ plus literal arguments, run without a shell in a per-attempt
    directory with an environment built from scratch. Every phase shows its exact
    command and the script's sha256 and asks before running; there is no --yes.
    The result is printed, then one line says whether the mentor was told.
    """


def _phase_command(phase: Phase, help_text: str) -> click.Command:
    @drill_group.command(phase.value, help=help_text)
    @click.argument("drill", metavar="<module>/<deck>/<task>")
    def command(drill: str) -> None:
        raise SystemExit(run_drill_phase(phase, drill))

    return command


drill_setup = _phase_command(
    Phase.SETUP,
    "Open a new attempt and run the task's setupCommand. A non-zero exit is an error and "
    "the attempt is not started. Exit 0 passed, 2 error or not confirmed.",
)
drill_check = _phase_command(
    Phase.CHECK,
    "Run the task's check command in the open attempt (opening one if setup was not "
    "needed). Exit 0 passed, 1 task not complete, 2 could not run / timed out / output "
    "cap hit or not confirmed. A check records a transient practice_check event only -- "
    "never a learner observation.",
)
drill_cleanup = _phase_command(
    Phase.CLEANUP,
    "Run the task's cleanupCommand and close the attempt -- the attempt closes even when "
    "cleanup fails (the failure is shown). Exit 0 passed, 2 error or not confirmed.",
)
