"""The core-created disposable kind cluster behind ``target.kind: kubeconfig-context`` (K0).

Proposal §5.5 *Kubernetes identity*: the attempt's target is a cluster **core** creates for
that attempt alone; core writes a kubeconfig holding exactly that one context into the attempt
directory (mode ``0o600``) and the runner exports it as ``KUBECONFIG``. Learner-owned contexts
are never used; the disposable cluster is the blast-radius boundary. §5.5 *Cleanup*: target
teardown is a core operation, never module shell.

Interface stub -- every body raises :class:`NotImplementedError` (red-only commit).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

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


def cluster_name(attempt_id: str) -> str:
    """``studyloop-<attempt id prefix>`` -- derived from the attempt id, never from module text."""
    raise NotImplementedError


def kubeconfig_path(attempt: Attempt) -> Path:
    """``<attempt dir>/kubeconfig``: where core writes the one-context kubeconfig."""
    raise NotImplementedError


def handle_for(attempt: Attempt, *, tools: Mapping[str, Path]) -> ClusterHandle:
    """Rebuild the handle for an attempt whose cluster an earlier ``setup`` created."""
    raise NotImplementedError


def provision(
    attempt: Attempt,
    *,
    tools: Mapping[str, Path],
    timeout_seconds: int = KIND_TIMEOUT_SECONDS,
) -> ClusterHandle:
    """Create the attempt's cluster and write its one-context kubeconfig (mode ``0o600``)."""
    raise NotImplementedError


def teardown(handle: ClusterHandle, *, timeout_seconds: int = KIND_TIMEOUT_SECONDS) -> None:
    """Delete the attempt's cluster and remove its kubeconfig; a failure names the cluster."""
    raise NotImplementedError
