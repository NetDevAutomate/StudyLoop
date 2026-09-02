"""Pure classification logic for the lane-ownership guard (M0 item 0.7).

No git, no filesystem I/O beyond the YAML map the caller loads and passes
in -- kept separate from test_lane_ownership.py so the branch-name rule and
the path-classification rule can each be unit-tested directly, without a
real git branch to diff against. See test_lane_ownership.py for the
git-driven integration test that calls these against the real repo.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

_LANE_BRANCH_RE = re.compile(r"^lane/m(\d+)-")


def lane_id_from_branch(branch: str) -> str | None:
    """Return the lane id (``"m3"``) for a lane branch, or ``None`` otherwise.

    ``None`` covers everything that isn't a lane branch at all (``main``,
    ``integration/...``, a throwaway probe branch with the wrong prefix) --
    the caller's job is to skip in that case, not fail.
    """
    match = _LANE_BRANCH_RE.match(branch)
    if not match:
        return None
    return f"m{match.group(1)}"


def _matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def owning_lanes(path: str, lanes: dict[str, list[str]]) -> list[str]:
    """Every lane whose glob list matches *path* (a file may be dual-owned)."""
    return [lane for lane, patterns in lanes.items() if _matches_any(path, patterns)]


@dataclass(frozen=True)
class LaneOwnershipResult:
    """Outcome of classifying one lane's changed files against the map."""

    violations: dict[str, list[str]] = field(default_factory=dict)  # path -> real owners
    unmapped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def classify_files(
    paths: list[str],
    lane: str,
    lanes: dict[str, list[str]],
    shared: list[str],
) -> LaneOwnershipResult:
    """Classify *paths* (a diff's changed files) for a lane branch.

    - Matches a shared pattern -> always OK, regardless of lane or map.
    - Matches this lane's own patterns (alone or jointly with others) -> OK.
    - Matches only *other* lanes' patterns -> a violation.
    - Matches no lane and isn't shared -> "unmapped": allowed, but the
      caller should log it so an out-of-date map is visible without ever
      failing the build over it.
    """
    violations: dict[str, list[str]] = {}
    unmapped: list[str] = []
    for path in paths:
        if _matches_any(path, shared):
            continue
        owners = owning_lanes(path, lanes)
        if not owners:
            unmapped.append(path)
            continue
        if lane not in owners:
            violations[path] = owners
    return LaneOwnershipResult(violations=violations, unmapped=unmapped)
