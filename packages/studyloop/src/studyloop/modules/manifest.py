"""``module.yaml`` -- the manifest of an optional module (module-contract v1, proposal §5.2).

The manifest is validated by :class:`ModuleManifest`, a Pydantic model with ``extra: forbid``
like every content schema in core. Two fields are deliberately typed *wider* than the
contract allows so that the conformance checker (``studyloop.modules.check``) can report
them under their own, more specific rule ids instead of as a generic validation failure:

- ``contract`` is an ``int``; whether core speaks it is MC002 (:data:`SUPPORTED_CONTRACTS`).
- ``prerequisites[].id`` is a ``str``; whether it is in core's enum is MC005
  (:data:`PREREQUISITE_IDS`). The probe for each id lives in ``studyloop.doctor.modules``.

``capabilities`` *is* a closed set at the model level (:data:`CAPABILITIES`): an unknown
capability is a manifest that does not validate (MC001). ``terminal`` names the learner's
own session and is always in use; ``setup``, ``check`` and ``cleanup`` each correspond to one
deck phase field (``setupCommand``, ``command``, ``cleanupCommand``).

Core never imports, executes or evaluates anything a module ships; this model reads data.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from studyloop.content.schemas import (
    SlugId,  # noqa: TC001 - pydantic resolves the annotation at runtime
)

SUPPORTED_CONTRACTS: tuple[int, ...] = (1,)
"""Module-contract versions this StudyLoop speaks (MC002)."""

PREREQUISITE_IDS: tuple[str, ...] = ("docker", "kind", "kubectl")
"""Core's prerequisite enum, v1 (proposal §5.4; MC005). Adding one is a core PR."""

Capability = Literal["terminal", "setup", "check", "cleanup"]
CAPABILITIES: tuple[str, ...] = ("terminal", "setup", "check", "cleanup")
"""The closed capability set. Order is the runner's phase order."""

PHASE_CAPABILITIES: dict[str, str] = {
    "setupCommand": "setup",
    "command": "check",
    "cleanupCommand": "cleanup",
}
"""Deck ``verification`` field -> the capability it needs (MC006 / MC016)."""

TargetKind = Literal["workdir", "kubeconfig-context"]


class Maintainer(BaseModel):
    """One maintainer; ``github`` is the handle, when there is one."""

    name: str = Field(min_length=1)
    github: str | None = None

    model_config = {"extra": "forbid"}


class Prerequisite(BaseModel):
    """One external tool the module needs; ``min`` is the minimum version as written."""

    id: str = Field(min_length=1)
    min: str | None = None

    model_config = {"extra": "forbid"}


class Target(BaseModel):
    """Where a drill runs: a per-attempt working directory or a disposable cluster."""

    kind: TargetKind

    model_config = {"extra": "forbid"}


class ModuleManifest(BaseModel):
    """The validated shape of ``module.yaml`` (proposal §5.2)."""

    id: SlugId
    contract: int
    version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    license: str = Field(min_length=1)
    maintainers: list[Maintainer] = Field(min_length=1)
    prerequisites: list[Prerequisite] = Field(default_factory=list)
    capabilities: list[Capability] = Field(default_factory=list)
    target: Target

    model_config = {"extra": "forbid"}

    def declared_phase_capabilities(self) -> set[str]:
        """The declared capabilities that a deck phase can use (``terminal`` excluded)."""
        return {capability for capability in self.capabilities if capability != "terminal"}
