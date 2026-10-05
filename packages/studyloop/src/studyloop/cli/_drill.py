"""``studyloop drill <setup|check|cleanup> <module>/<deck>/<task>`` -- the MVP's only execution
surface for module drills (proposal §7, drill-runner spec).

Exported as :data:`drill_group`; lane W registers it in ``cli/__init__.py`` (wave 2). One
invocation runs exactly one phase of one drill through the §5.5 runner:

1. resolve ``<module>/<deck>/<task>`` -- the installed module (lane C's lockfile, behind
   :func:`locate_installed_module`), the deck file under the snapshot's ``decks/`` whose
   ``id`` matches, the task whose ``id`` matches, and the phase's command
   (``setupCommand`` / ``command`` / ``cleanupCommand``), split into argv by ``shlex``;
2. find or open the attempt (``setup`` opens a new one; ``check`` reuses the open one or
   opens one; ``cleanup`` needs an open one and always closes it). For a
   ``kubeconfig-context`` module core's own tools (``kind``, ``kubectl``, ``docker``) are
   then resolved on the learner's PATH whatever the module declares (M1 Q2) and ``setup``
   **provisions the disposable kind cluster** (lane K0, ``modules/cluster.py``) and records
   its one-context kubeconfig on the attempt -- all BEFORE the consent prompt, so the prompt
   can name the cluster and the kubeconfig; ``check`` and ``cleanup`` reuse the recorded
   kubeconfig, and a ``check`` that found nothing open is refused (only ``setup`` provisions);
3. validate argv and script path and compute the digest **before** asking -- a command the
   runner would refuse is never shown as something to consent to (this happens before step
   2's open, so a refused command never leaves a record);
4. show the consent text (phase, target, exact argv, script sha256) and ask. There is no
   ``--yes``. Declining exits 2 and runs nothing;
5. run the phase; print its result first; then post the typed fields to the mentor hop and
   print exactly one line -- ``Mentor told.`` or ``Mentor not told: <reason>``;
6. record the ``practice_check_events`` row and the attempt's own evidence; close the
   attempt when the phase was ``cleanup`` (whatever its exit) or a failed ``setup``. The
   disposable cluster is deleted whenever the attempt closes **and** on every failure path
   after it was created -- declined consent, a refusal after consent, a failed ``setup``, a
   ``check`` timeout, Ctrl-C or any other exception -- and a failed delete is printed as
   ``ERROR`` naming the cluster and makes the exit status 2 (spec: never hidden).

Exit status: 0 passed, 1 failed (task not complete) or a refusal/usage problem reported by
Click, 2 error (timeout, cap, non-zero setup/cleanup, check could not run, cluster teardown
failed) or consent declined.
"""

from __future__ import annotations

import dataclasses
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
from studyloop.modules import cluster, hop, runner
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
    TargetKind,
    record_phase,
)
from studyloop.modules.cluster import ClusterError, ClusterHandle
from studyloop.modules.consent import ConsentLedger, describe_consent

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from studyloop.content.schemas import PracticeTask
    from studyloop.modules.manifest import ModuleManifest

__all__ = [
    "ModuleNotInstalledError",
    "attempts_root",
    "drill_group",
    "locate_installed_module",
    "module_prerequisites",
    "module_target",
    "read_module_manifest",
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


def read_module_manifest(snapshot_dir: Path) -> ModuleManifest:
    """The installed module's ``module.yaml`` through lane C's ``ModuleManifest`` (``extra:
    forbid``). The snapshot passed ``module check`` at install, so a manifest that no longer
    validates means the snapshot was altered: refuse the phase rather than guess."""
    import yaml
    from pydantic import ValidationError

    from studyloop.modules.manifest import ModuleManifest

    manifest_path = snapshot_dir / "module.yaml"
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        return ModuleManifest.model_validate(raw)
    except (OSError, ValueError, yaml.YAMLError, ValidationError) as exc:
        raise click.ClickException(
            f"module.yaml in the installed snapshot does not validate ({exc}); "
            "re-run `studyloop module add` from the module's source"
        ) from exc


def module_prerequisites(snapshot_dir: Path) -> tuple[str, ...]:
    """``prerequisites[].id`` from the installed module's ``module.yaml``, in declared order."""
    return tuple(p.id for p in read_module_manifest(snapshot_dir).prerequisites)


def module_target(snapshot_dir: Path) -> TargetKind:
    """``target.kind`` from the installed module's manifest, as the runner's enum.

    W-review finding 8: the attempt records the module's declared target instead of defaulting
    to ``workdir``. For ``kubeconfig-context`` lane K0 (``modules/cluster.py``, wired in
    :func:`run_drill_phase`) provisions the §5.5 disposable cluster at ``setup`` and records
    the one-context ``KUBECONFIG`` on the attempt; ``runner.build_environment`` still refuses
    an attempt that carries none (the spec's "a missing kubeconfig is refused before spawn").
    """
    return TargetKind(read_module_manifest(snapshot_dir).target.kind)


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
    store: AttemptStore,
    phase: Phase,
    drill: DrillIdentity,
    snapshot_dir: Path,
    target: TargetKind = TargetKind.WORKDIR,
) -> tuple[Attempt, bool]:
    """Return ``(attempt, opened_here)`` per phase: setup opens, check reuses-or-opens,
    cleanup needs one. ``target`` is the manifest's ``target.kind``; ``kubeconfig`` is still
    ``None`` here -- for a ``kubeconfig-context`` attempt :func:`_provision_cluster` sets it
    right after ``setup`` opens the attempt (the cluster name derives from the attempt id).
    A ``check`` that opens a ``kubeconfig-context`` attempt here has no cluster: the caller
    records that attempt as refused and closes it (``test_module_lane_seams.py`` pins the
    record) -- only ``setup`` provisions (K0 brief item 5)."""
    current = store.current(drill)
    if phase is Phase.SETUP:
        if current is not None:
            raise click.ClickException(
                f"attempt {current.attempt_id} is already open for {drill.drill_id}; run "
                f"`studyloop drill cleanup {drill.module_id}/{drill.drill_id}` first"
            )
        return store.open(drill, snapshot_dir=snapshot_dir, target=target), True
    if phase is Phase.CLEANUP:
        if current is None:
            raise click.ClickException(
                f"no open attempt for {drill.module_id}/{drill.drill_id}; nothing to clean up"
            )
        return current, False
    if current is not None:
        return current, False
    return store.open(drill, snapshot_dir=snapshot_dir, target=target), True


# ---------------------------------------------------------------------------
# The disposable cluster's lifetime is the attempt's (lane K0, modules/cluster.py)
# ---------------------------------------------------------------------------


def _record_kubeconfig(store: AttemptStore, attempt: Attempt, kubeconfig: Path) -> Attempt:
    """Persist the core-written kubeconfig on the open attempt's record and return the attempt
    carrying it, so ``check``/``cleanup`` (later processes) find it through ``store.current``.

    :class:`AttemptStore` persists ``kubeconfig`` at ``open()`` and reads it back, but has no
    setter -- and the path cannot be known before ``open()`` mints the attempt id the cluster
    name derives from. The record is updated through the store's own sidecar primitives so its
    ``O_NOFOLLOW`` / ``O_EXCL`` / atomic-rename discipline is kept (the file is owned by lane R;
    a public ``set_kubeconfig`` is the coordinator's call).
    """
    path = store._record_path(attempt)
    record = store._read(path)
    if record is None:
        raise SidecarError(
            f"attempt record {path.name} vanished before the kubeconfig could be recorded"
        )
    record["kubeconfig"] = str(kubeconfig)
    store._write(path, record)
    return dataclasses.replace(attempt, kubeconfig=kubeconfig)


@dataclasses.dataclass
class _Disposable:
    """The attempt's disposable cluster and whether it has already been torn down.

    One object per CLI invocation so the normal path (``cleanup``, a failed ``setup``, a
    ``check`` timeout, declined consent) and the exceptional path (Ctrl-C, any error) cannot
    both issue a ``kind delete`` for the same cluster.
    """

    handle: ClusterHandle
    torn_down: bool = False

    def teardown(self, store: AttemptStore, attempt: Attempt, *, reason: str) -> bool:
        """Delete the cluster, remove its kubeconfig, close the attempt. Returns ``False`` when
        kind could not delete it -- after printing ``ERROR: ...`` naming the cluster and the
        by-hand command (never silently); the attempt is closed either way so the next
        ``setup`` can start clean."""
        if self.torn_down:
            return True
        self.torn_down = True
        ok = True
        try:
            cluster.teardown(self.handle)
            click.echo(f"Cluster {self.handle.name} deleted; its kubeconfig removed.")
        except ClusterError as exc:
            ok = False
            click.echo(f"ERROR: {exc}")
            reason = f"{reason}; cluster teardown failed: {exc}"
        store.close(attempt, reason=reason)
        return ok


def _provision_cluster(
    store: AttemptStore, attempt: Attempt, tools: Mapping[str, Path], live: list[_Disposable]
) -> tuple[Attempt, _Disposable]:
    """``setup`` on a ``kubeconfig-context`` attempt: create the cluster BEFORE the consent
    prompt (so the prompt names it) and record its kubeconfig on the attempt. A provisioning
    failure closes the just-opened attempt and is a Click error naming the cluster.

    The :class:`_Disposable` is appended to ``live`` the instant ``provision`` returns, so the
    caller's ``except BaseException`` can tear the cluster down whatever happens next -- a
    ``SidecarError`` writing the record, a ``KeyboardInterrupt`` landing between the two lines
    (K0-review F4). Nothing here catches the non-``ClusterError`` cases itself: the caller does,
    once, for every path.
    """
    try:
        handle = cluster.provision(attempt, tools=tools)
    except ClusterError as exc:
        store.close(attempt, reason=f"setup: cluster not provisioned: {exc}")
        raise click.ClickException(str(exc)) from exc
    disposable = _Disposable(handle)
    live.append(disposable)
    try:
        attempt = _record_kubeconfig(store, attempt, handle.kubeconfig)
    except SidecarError as exc:
        disposable.teardown(store, attempt, reason=f"setup: attempt record not updated: {exc}")
        raise click.ClickException(f"attempt record not updated: {exc}") from exc
    return attempt, disposable


def _consent_and_run(
    store: AttemptStore,
    attempt: Attempt,
    *,
    opened_here: bool,
    disposable: _Disposable | None,
    phase: Phase,
    argv: Sequence[str],
    digest: str,
    timeout: int,
    prerequisites: Sequence[str],
) -> int:
    """Steps 4-6 of the module docstring for an attempt that is open (and, for a
    ``kubeconfig-context`` target, whose cluster exists). Returns the exit status."""
    if disposable is not None:
        click.echo(
            f"Cluster:     {disposable.handle.name} (disposable kind cluster core created for "
            "this attempt; deleted after cleanup or on failure)"
        )
    click.echo(describe_consent(attempt, phase, argv, script_digest=digest))
    if not click.confirm("Run this phase now?", default=False):
        click.echo("Not confirmed -- nothing executed.")
        reason = f"{phase.value} not confirmed; nothing ran"
        if disposable is not None:
            # K0 brief item 3: consent refused on any phase after the cluster exists tears it
            # down -- a cluster nobody consented to work on does not stay up.
            disposable.teardown(store, attempt, reason=reason)
        elif opened_here:
            store.close(attempt, reason=reason)
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
        reason = f"{phase.value} refused before spawn: {exc}"
        if opened_here:
            if disposable is not None:
                disposable.teardown(store, attempt, reason=reason)
            else:
                store.close(attempt, reason=reason)
        raise click.ClickException(str(exc)) from exc

    _echo_result(result)
    fields = hop.check_result_fields(attempt, result)
    outcome = hop.post_check_result(fields)
    _echo_outcome(outcome)

    if record_phase(attempt, result, delivery=outcome) is None:
        click.echo(
            "practice_check event not recorded: the sessions database is unavailable", err=True
        )
    status = _exit_status(result)
    # The child has exited and been reaped (run_phase returned): safe to write the sidecar.
    try:
        store.record_evidence(attempt, result, delivery=outcome)
        closes = phase is Phase.CLEANUP or (
            phase is Phase.SETUP and result.exit_class is not ExitClass.PASSED
        )
        # K0 brief item 3: a check that timed out is a failure path for the cluster too (a
        # check that merely exits 1 -- task not complete -- keeps it for the next try).
        if disposable is not None and phase is Phase.CHECK and result.timed_out:
            closes = True
        if closes:
            if disposable is not None:
                if not disposable.teardown(store, attempt, reason=result.message):
                    status = 2
            else:
                store.close(attempt, reason=result.message)
    except SidecarError as exc:
        raise click.ClickException(f"attempt record not updated: {exc}") from exc
    return status


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
    # PATH and exposes to the child, and nothing else (M1 PATH ruling). The same read gives
    # the declared target kind the attempt records (W-review finding 8).
    manifest = read_module_manifest(installed.snapshot_dir)
    prerequisites = tuple(p.id for p in manifest.prerequisites)
    target = TargetKind(manifest.target.kind)

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
    attempt, opened_here = _open_attempt(store, phase, drill, installed.snapshot_dir, target)
    # The attempt's disposable cluster, registered by `_attach_cluster` the instant it exists
    # (a list, not a local assigned from a return value: a KeyboardInterrupt between the
    # return and the assignment would otherwise leave a cluster nobody can tear down -- F4).
    live: list[_Disposable] = []
    try:
        disposable: _Disposable | None = None
        if target is TargetKind.KUBECONFIG_CONTEXT:
            attempt, disposable = _attach_cluster(
                store, attempt, phase=phase, ref=ref, opened_here=opened_here, live=live
            )
        return _consent_and_run(
            store,
            attempt,
            opened_here=opened_here,
            disposable=disposable,
            phase=phase,
            argv=argv,
            digest=digest,
            timeout=timeout,
            prerequisites=prerequisites,
        )
    except BaseException as exc:
        # K0 brief item 3 / review F4: KeyboardInterrupt, click.Abort, a Click error after
        # consent, a SidecarError, any other failure -- the disposable cluster must not
        # outlive the attempt. The normal paths above have already torn down when they meant
        # to (`torn_down` makes this a no-op for them).
        for pending in live:
            if not pending.torn_down:
                pending.teardown(
                    store, attempt, reason=f"{phase.value} interrupted: {type(exc).__name__}"
                )
        raise


def _attach_cluster(
    store: AttemptStore,
    attempt: Attempt,
    *,
    phase: Phase,
    ref: str,
    opened_here: bool,
    live: list[_Disposable],
) -> tuple[Attempt, _Disposable]:
    """Give a ``kubeconfig-context`` attempt its disposable cluster, before any consent.

    ``setup`` provisions (K0 brief item 5); ``check``/``cleanup`` rebuild the handle from the
    attempt's recorded kubeconfig. A ``check`` that found nothing open has no cluster to run
    against and is refused here -- not after consent in the runner's missing-kubeconfig branch
    -- with the attempt it opened recorded and closed (``test_module_lane_seams.py`` pins that
    record). Core's own tools -- ``kind``, ``kubectl``, ``docker`` (brief item 6, M1 Q2) --
    are resolved on the learner's PATH here whatever the module declares; an unresolvable one
    refuses the phase naming the tool, closing the attempt this invocation opened.
    """
    if phase is Phase.CHECK and attempt.kubeconfig is None:
        reason = (
            f"no cluster for this attempt: a kubeconfig-context drill runs against the "
            f"disposable cluster `studyloop drill setup {ref}` creates -- run that first; "
            "refusing to spawn"
        )
        if opened_here:
            store.close(attempt, reason=reason)
        raise click.ClickException(reason)
    try:
        tools = runner.resolve_prerequisites(cluster.CLUSTER_TOOLS)
    except RefusalError as exc:
        if opened_here:
            store.close(attempt, reason=f"{phase.value} refused before consent: {exc}")
        raise click.ClickException(str(exc)) from exc
    if phase is Phase.SETUP:
        return _provision_cluster(store, attempt, tools, live)
    disposable = _Disposable(cluster.handle_for(attempt, tools=tools))
    live.append(disposable)
    return attempt, disposable


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
    "the attempt is not started. For a kubeconfig-context module the disposable kind "
    "cluster is created first and named in the prompt; it is deleted again if setup fails "
    "or is not confirmed. Exit 0 passed, 2 error or not confirmed.",
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
    "cleanup fails (the failure is shown). For a kubeconfig-context module the attempt's "
    "disposable kind cluster is deleted after the script runs; a failed delete is reported "
    "naming the cluster. Exit 0 passed, 2 error or not confirmed.",
)
