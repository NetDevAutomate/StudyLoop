"""The core-created disposable kind cluster behind ``target.kind: kubeconfig-context`` (K0).

Proposal §5.5 *Kubernetes identity*: the attempt's target is a cluster **core** creates for
that attempt alone; core writes a kubeconfig holding exactly that one context into the attempt
directory (mode ``0o600``) and the runner exports it as ``KUBECONFIG``
(``runner.build_environment``). Learner-owned contexts are never used; the disposable cluster
is the blast-radius boundary. §5.5 *Cleanup*: target teardown is a core operation, never
module shell. Spec: ``specs/drill-runner/spec.md``, "A kubeconfig-context attempt runs against
a core-created disposable cluster"; brief: ``briefs/K0-cluster-provisioning.md``.

What this module guarantees, each a contract item:

- *Name*: :func:`cluster_name` is ``studyloop-`` + the attempt id's first eight ``[a-z0-9]``
  characters -- derived from the attempt id, never from module text. A cluster already
  carrying that name is a :class:`ClusterError` (refused, never reused). The only listing
  (``kind get clusters``) is read-only and exists for that check alone: core never sweeps
  "stale" ``studyloop-*`` clusters -- the owner's live proof plants a sentinel cluster to
  catch exactly that (``tests/acceptance/test_module_kdrill_live.py``).
- *Create*: ``kind create cluster --name <name> --kubeconfig <attempt>/kubeconfig --wait 120s``
  through the ``kind`` binary core resolved on the learner's PATH up front
  (:func:`runner.resolve_prerequisites`, M1 Q2) -- argv as a list, ``shell=False``, stdin
  ``DEVNULL``, stdout/stderr captured and capped, a hard timeout, ``start_new_session=True``
  so a timeout kills the whole process group. After a create that did **not** succeed core
  deletes only when it can prove it created the cluster -- kind wrote the attempt's own
  kubeconfig naming ``kind-<name>`` (:func:`_proof_of_creation`); otherwise it re-lists
  read-only and reports the name and the by-hand command without deleting anything (spec
  scenario "a failed create never deletes a cluster core cannot prove it made"). After a
  create that succeeded, anything that goes wrong tears the cluster down again.
- *Kubeconfig*: kind writes a kubeconfig into the attempt directory; :func:`provision` then
  rewrites it to **exactly one context** -- the new cluster's ``kind-<name>``, its cluster
  and its user -- ``current-context`` set, mode ``0o600``, written through an ``O_EXCL`` temp
  file and an atomic rename. A kubeconfig in which that context is missing is an error (and
  the cluster is deleted again).
- *Teardown*: ``kind delete cluster --name <name> --kubeconfig <attempt>/kubeconfig`` with
  the same spawn discipline, then the kubeconfig file is removed. ``--kubeconfig`` is passed
  on delete too: without it kind opens the learner's default kubeconfig (``$KUBECONFIG`` or
  ``~/.kube/config``) to drop the context, which is a learner-owned file this module must
  never touch. A failed delete is a :class:`ClusterError` naming the cluster and the by-hand
  command; the CLI prints it as ``ERROR`` and exits non-zero -- never silent.
- *Environment of kind itself*: kind is **core's** tool, not module shell, and it has to
  reach the learner's Docker daemon (Docker Desktop contexts live under the learner's
  ``~/.docker``), so it runs with a copy of the learner's environment -- with ``KUBECONFIG``
  removed (belt and braces beside the explicit ``--kubeconfig``) and the resolved kind's own
  directory put first on ``PATH``. The scratch environment of §5.5 is the *drill script's*;
  it is built later by the runner and is untouched here.

Spawning goes through ``subprocess.Popen`` looked up on the module at call time so tests can
observe the exact spawn arguments by patching ``subprocess.Popen`` (same convention as
``runner.py``).
"""

from __future__ import annotations

import contextlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from studyloop.modules.attempt import Attempt

#: Every disposable cluster's name starts with this; the rest derives from the attempt id.
CLUSTER_PREFIX = "studyloop-"

#: The kubeconfig file name inside the attempt directory.
KUBECONFIG_NAME = "kubeconfig"

#: The tools core itself needs to provision and tear down the cluster (M1 Q2: resolved on
#: the learner's PATH up front, before any consent; an unresolvable one refuses the phase).
CLUSTER_TOOLS: tuple[str, ...] = ("kind", "kubectl", "docker")

#: ``kind create cluster --wait`` value: how long kind waits for the control plane.
KIND_WAIT = "120s"

#: Hard timeout for one ``kind`` invocation (create or delete).
KIND_TIMEOUT_SECONDS = 300

#: How many characters of the attempt id follow the prefix in the cluster name.
_NAME_ID_CHARS = 8

#: Bytes of each captured kind stream kept (the tail -- kind's error is at the end).
_OUTPUT_CAP = 16 * 1024

#: Grace between SIGTERM and SIGKILL when a kind call has to be stopped.
_TERMINATE_GRACE_SECONDS = 2.0

_NOT_NAME_CHARS = re.compile(r"[^a-z0-9]")


class ClusterError(RuntimeError):
    """Provisioning or teardown did not happen as required; ``cluster`` names the cluster."""

    def __init__(self, message: str, *, cluster: str | None = None) -> None:
        super().__init__(message)
        self.cluster = cluster


@dataclass(frozen=True)
class ClusterHandle:
    """What :func:`teardown` needs: the cluster's name, its kubeconfig, the ``kind`` binary."""

    name: str
    kubeconfig: Path
    kind: Path


@dataclass(frozen=True)
class _KindRun:
    """One finished (or stopped) ``kind`` invocation."""

    argv: tuple[str, ...]
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def describe(self, timeout_seconds: int) -> str:
        """The failure as one readable clause: what ran, how it ended, what it said."""
        command = " ".join(self.argv[1:])
        if self.timed_out:
            ending = f"timed out after {timeout_seconds}s and was killed"
        elif self.returncode is None:
            ending = "could not be started"
        else:
            ending = f"exited {self.returncode}"
        tail = (self.stderr or self.stdout).strip()
        return f"`kind {command}` {ending}" + (f": {tail}" if tail else "")


def cluster_name(attempt_id: str) -> str:
    """``studyloop-<attempt id prefix>`` -- derived from the attempt id, never from module text.

    kind cluster names must be lowercase ``[a-z0-9.-]``; the attempt id is a UUID4 in
    production, whose first eight hex characters are kept. Anything else is lower-cased and
    stripped to ``[a-z0-9]`` so the derivation is total; an id that leaves nothing is refused.
    """
    prefix = _NOT_NAME_CHARS.sub("", attempt_id.lower())[:_NAME_ID_CHARS]
    if not prefix:
        raise ClusterError(f"attempt id {attempt_id!r} yields no cluster name characters")
    return f"{CLUSTER_PREFIX}{prefix}"


def kubeconfig_path(attempt: Attempt) -> Path:
    """``<attempt dir>/kubeconfig``: where core writes the one-context kubeconfig."""
    return attempt.attempt_dir.resolve() / KUBECONFIG_NAME


def _kind_binary(tools: Mapping[str, Path]) -> Path:
    try:
        return Path(tools["kind"])
    except KeyError as exc:
        raise ClusterError(
            "kind was not resolved before provisioning; core resolves kind, kubectl and docker "
            "on your PATH before any kubeconfig-context phase"
        ) from exc


def handle_for(attempt: Attempt, *, tools: Mapping[str, Path]) -> ClusterHandle:
    """Rebuild the handle for an attempt whose cluster an earlier ``setup`` created.

    ``check`` and ``cleanup`` run in later processes: the name comes from the attempt id and
    the kubeconfig from the attempt's record (falling back to its canonical path) -- never
    from module text or from a listing.
    """
    kubeconfig = attempt.kubeconfig if attempt.kubeconfig is not None else kubeconfig_path(attempt)
    return ClusterHandle(
        name=cluster_name(attempt.attempt_id), kubeconfig=kubeconfig, kind=_kind_binary(tools)
    )


def _kind_env(kind: Path) -> dict[str, str]:
    """The learner's environment for core's own ``kind`` call, minus ``KUBECONFIG``, with the
    resolved kind's directory first on ``PATH`` (see the module docstring)."""
    env = dict(os.environ)
    env.pop("KUBECONFIG", None)
    inherited = env.get("PATH", "")
    env["PATH"] = f"{kind.parent}:{inherited}" if inherited else str(kind.parent)
    return env


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Terminate, then kill, the process group ``start_new_session=True`` created."""
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, 15)  # SIGTERM
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, 9)  # SIGKILL
    except (ProcessLookupError, PermissionError):
        process.kill()
    process.wait()


def _tail(raw: bytes) -> str:
    return raw[-_OUTPUT_CAP:].decode("utf-8", errors="replace")


def _run_kind(argv: Sequence[str], *, timeout_seconds: int) -> _KindRun:
    """Run one ``kind`` command with the spawn discipline the brief fixes (argv list, no shell,
    stdin DEVNULL, captured and capped output, hard timeout, own process group)."""
    items = tuple(argv)
    try:
        process = subprocess.Popen(
            list(items),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_kind_env(Path(items[0])),
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        return _KindRun(
            items, None, "", f"could not execute {items[0]}: {exc.strerror or exc}", False
        )
    timed_out = False
    try:
        out, err = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _stop(process)
        out, err = process.communicate()
    finally:
        if process.returncode is None:
            _stop(process)
    return _KindRun(items, process.returncode, _tail(out), _tail(err), timed_out)


def _existing_clusters(kind: Path, *, timeout_seconds: int) -> frozenset[str]:
    """Read-only: the cluster names kind knows. Used for the collision check and nothing else."""
    run = _run_kind([str(kind), "get", "clusters"], timeout_seconds=timeout_seconds)
    if not run.ok:
        raise ClusterError(
            f"could not list kind clusters to check for a name collision -- "
            f"{run.describe(timeout_seconds)}; nothing was created"
        )
    return frozenset(line.strip() for line in run.stdout.splitlines() if line.strip())


def _delete_argv(handle: ClusterHandle) -> list[str]:
    return [
        str(handle.kind),
        "delete",
        "cluster",
        "--name",
        handle.name,
        "--kubeconfig",
        str(handle.kubeconfig),
    ]


def _by_hand(name: str) -> str:
    return f"delete it by hand with `kind delete cluster --name {name}`"


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as a fresh ``0o600`` regular file: ``O_EXCL | O_NOFOLLOW``
    temp file beside it, fsync, atomic rename; the final mode is forced after the rename."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    os.chmod(path, 0o600)


def _one_context(doc: Any, context_name: str) -> dict[str, Any]:
    """The kubeconfig document reduced to ``context_name``, its cluster and its user."""
    if not isinstance(doc, dict):
        raise ValueError("kubeconfig is not a mapping")
    contexts = [c for c in doc.get("contexts") or [] if c.get("name") == context_name]
    if len(contexts) != 1:
        raise ValueError(
            f"expected exactly one context named {context_name!r}, found {len(contexts)}"
        )
    binding = contexts[0].get("context") or {}
    cluster_ref, user_ref = binding.get("cluster"), binding.get("user")
    clusters = [c for c in doc.get("clusters") or [] if c.get("name") == cluster_ref]
    users = [u for u in doc.get("users") or [] if u.get("name") == user_ref]
    if len(clusters) != 1 or len(users) != 1:
        raise ValueError(
            f"context {context_name!r} binds cluster {cluster_ref!r} and user {user_ref!r}; "
            f"found {len(clusters)} cluster(s) and {len(users)} user(s) by those names"
        )
    reduced = dict(doc)
    reduced["contexts"] = contexts
    reduced["clusters"] = clusters
    reduced["users"] = users
    reduced["current-context"] = context_name
    return reduced


def rewrite_kubeconfig(path: Path, name: str) -> str:
    """Reduce the kubeconfig kind wrote at ``path`` to exactly the new cluster's one context,
    ``kind-<name>``, with ``current-context`` set and mode ``0o600``. Returns the context name.

    The file must be a regular file (kind's own output; a symlink planted there is refused).
    """
    context_name = f"kind-{name}"
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise ClusterError(
            f"kind reported success but wrote no kubeconfig at {path} ({exc.strerror})",
            cluster=name,
        ) from exc
    if not stat.S_ISREG(st.st_mode):
        raise ClusterError(f"{path} is not a regular file; refusing to rewrite it", cluster=name)
    try:
        reduced = _one_context(yaml.safe_load(path.read_text(encoding="utf-8")), context_name)
        text = yaml.safe_dump(reduced, default_flow_style=False, sort_keys=False)
        path.unlink()
        _write_private(path, text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ClusterError(
            f"could not reduce {path} to the one context {context_name!r}: {exc}", cluster=name
        ) from exc
    return context_name


def provision(
    attempt: Attempt,
    *,
    tools: Mapping[str, Path],
    timeout_seconds: int = KIND_TIMEOUT_SECONDS,
) -> ClusterHandle:
    """Create the attempt's cluster and write its one-context kubeconfig (mode ``0o600``).

    Order: derive the name -> refuse if the kubeconfig already exists (an attempt provisions
    once) -> read-only listing, refuse a name collision -> ``kind create`` -> rewrite the
    kubeconfig to one context. A create that fails or times out is followed by
    :func:`_undo_after_failed_create` (a delete only with proof of creation); a kubeconfig that
    cannot be reduced after a successful create is followed by one ``kind delete``. Either way
    the :class:`ClusterError` names the cluster. Nothing here reads the attempt's record; the
    caller persists ``handle.kubeconfig`` on the attempt.
    """
    kind = _kind_binary(tools)
    name = cluster_name(attempt.attempt_id)
    kubeconfig = kubeconfig_path(attempt)
    handle = ClusterHandle(name=name, kubeconfig=kubeconfig, kind=kind)
    if kubeconfig.exists() or kubeconfig.is_symlink():
        raise ClusterError(
            f"{kubeconfig} already exists; an attempt provisions its cluster once", cluster=name
        )
    if name in _existing_clusters(kind, timeout_seconds=timeout_seconds):
        raise ClusterError(
            f"a kind cluster named {name} already exists; refusing to reuse it (if it is a "
            f"leftover from an earlier attempt, {_by_hand(name)} and run setup again)",
            cluster=name,
        )

    created = _run_kind(
        [
            str(kind),
            "create",
            "cluster",
            "--name",
            name,
            "--kubeconfig",
            str(kubeconfig),
            "--wait",
            KIND_WAIT,
        ],
        timeout_seconds=timeout_seconds,
    )
    if not created.ok:
        raise ClusterError(
            f"could not create the disposable cluster {name}: {created.describe(timeout_seconds)}"
            f"; {_undo_after_failed_create(handle, timeout_seconds)}",
            cluster=name,
        )
    try:
        rewrite_kubeconfig(kubeconfig, name)
    except ClusterError as exc:
        raise ClusterError(
            f"{exc}; {_undo_after_created(handle, timeout_seconds)}", cluster=name
        ) from exc
    return handle


def _proof_of_creation(handle: ClusterHandle) -> bool:
    """Did OUR ``kind create`` get as far as writing the attempt's kubeconfig for this cluster?

    The file at ``<attempt>/kubeconfig`` can only have been written by the kind invocation core
    just made (the attempt directory is core-created, ``0o700``, and ``provision`` refused to
    start while the path existed), and kind writes it naming the context ``kind-<name>``. That
    is the one unforgeable sign that the cluster carrying ``name`` is this attempt's.
    """
    try:
        if not stat.S_ISREG(os.lstat(handle.kubeconfig).st_mode):
            return False
        doc = yaml.safe_load(handle.kubeconfig.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    if not isinstance(doc, dict):
        return False
    contexts = doc.get("contexts")
    if not isinstance(contexts, list):
        return False
    return any(
        isinstance(item, dict) and item.get("name") == f"kind-{handle.name}" for item in contexts
    )


def _undo_after_failed_create(handle: ClusterHandle, timeout_seconds: int) -> str:
    """After a ``kind create`` that did NOT succeed: delete only what core can prove it made.

    Spec ("a failed create never deletes a cluster core cannot prove it made", K0-review F1):
    the collision check and the create are two separate calls, so a name that appears between
    them may belong to someone else. With :func:`_proof_of_creation` the delete is inside the
    blast radius and runs once. Without it nothing is deleted: core re-lists read-only and
    reports either that a cluster by that name exists which it cannot prove it created (with
    the exact by-hand command), or -- the name absent -- the create failure alone.
    """
    if _proof_of_creation(handle):
        return _undo_after_created(handle, timeout_seconds)
    try:
        listed = _existing_clusters(handle.kind, timeout_seconds=timeout_seconds)
    except ClusterError as exc:
        return f"nothing was deleted ({exc})"
    if handle.name in listed:
        return (
            f"a cluster named {handle.name} exists that core cannot prove it created, so it was "
            f"NOT deleted; if it is yours, {_by_hand(handle.name)}"
        )
    return "nothing was created"


def _undo_after_created(handle: ClusterHandle, timeout_seconds: int) -> str:
    """One ``kind delete`` for a cluster core knows is this attempt's (the create succeeded, or
    kind wrote the attempt's kubeconfig for it); returns what happened for the error text."""
    deleted = _run_kind(_delete_argv(handle), timeout_seconds=timeout_seconds)
    with contextlib.suppress(OSError):
        handle.kubeconfig.unlink(missing_ok=True)
    if deleted.ok:
        return f"anything kind had made for {handle.name} was deleted again"
    return (
        f"the follow-up `kind delete cluster --name {handle.name}` also failed "
        f"({deleted.describe(timeout_seconds)}) -- if `kind get clusters` lists it, "
        f"{_by_hand(handle.name)}"
    )


def teardown(handle: ClusterHandle, *, timeout_seconds: int = KIND_TIMEOUT_SECONDS) -> None:
    """Delete the attempt's cluster and remove its kubeconfig; a failure names the cluster.

    Deletes exactly ``handle.name`` -- no listing, no prefix sweep. The kubeconfig is removed
    whether or not kind succeeded (it holds admin credentials for a cluster the learner no
    longer wants); the :class:`ClusterError` tells the learner the cluster may still exist and
    how to delete it by hand.
    """
    deleted = _run_kind(_delete_argv(handle), timeout_seconds=timeout_seconds)
    with contextlib.suppress(OSError):
        handle.kubeconfig.unlink(missing_ok=True)
    if not deleted.ok:
        raise ClusterError(
            f"could not delete the disposable cluster {handle.name}: "
            f"{deleted.describe(timeout_seconds)} -- the cluster may still exist; "
            f"{_by_hand(handle.name)}",
            cluster=handle.name,
        )
