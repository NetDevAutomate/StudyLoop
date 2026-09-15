"""Domain errors raised by :class:`~studyloop.planning.application.PlanApplication`.

These carry no CLI, HTTP or MCP vocabulary. Each adapter maps them exactly
once (design §2): the Web API to a status code, the CLI to an exit code and a
message, an MCP tool to a ``ToolError``. Keeping the mapping in the adapter
is what lets the same refusal — say, "this plan is not ready to activate" —
read identically on every surface without the domain knowing any of them.

Naming: these are the names the council arbitration fixed (D-3), without the
``Error`` suffix pep8-naming asks for. The suffixed forms already exist in
:mod:`studyloop.planning.store` (``PlanNotFoundError``, ``InvalidPlanIdError``,
``PlanExistsError``) with stdlib bases, are re-exported from the same package,
and are what the store raises *to* the seam; a second family with the same
names and a different base would be a trap for every ``except`` clause.
"""

# ruff: noqa: N818

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .views import ReadinessView


class PlanError(Exception):
    """Base class for every plan-domain failure an adapter may see."""


class PlanNotFound(PlanError):
    """No plan document resolves to the given id."""


class InvalidPlanId(PlanError):
    """The id is malformed or would escape the plans directory."""


class PlanConflict(PlanError):
    """A create would clobber an existing plan id and ``overwrite`` was not set."""


class InvalidField(PlanError):
    """A supplied value is unusable: unknown status, empty title, bad phase…"""


class PlanNotReady(PlanError):
    """The resulting document would be active but fails the readiness check.

    Carries the :class:`~studyloop.planning.views.ReadinessView` so an adapter
    can show *what* blocks activation, not just that something does. Raised
    before any write, on every path that could make a plan active.
    """

    def __init__(self, readiness: ReadinessView) -> None:
        super().__init__("plan is not ready to activate")
        self.readiness = readiness


class InvalidMilestone(PlanError):
    """The milestone index does not exist on the plan."""
