"""Doctor probes for installed modules' prerequisites (module-contract v1, proposal §5.4).

``studyloop doctor`` reports whether the external tools the *installed* modules declare in
``module.yaml`` ``prerequisites`` are present, and at what version. Three facts bound this:

- The enum is core's (:data:`studyloop.modules.manifest.PREREQUISITE_IDS`: ``docker``,
  ``kind``, ``kubectl``); a module cannot add a probe, only a core PR can.
- A probe runs ``<binary> --version`` and **nothing else**: no daemon call, no cluster or
  context is created, listed or switched. It is the one subprocess this module spawns.
- Probes run only for modules recorded in ``modules.lock.json``. With no module installed
  no binary is looked up and no subprocess runs, so a learner who never installed a module
  sees no module rows at all.

Results join the ``deps`` category (``doctor/models.py`` owns the category set and is not
this lane's file). Each row's ``name`` is ``module_prereq_<tool>``; a tool several modules
need is probed once and the row names every module that needs it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from studyloop.doctor.models import CheckResult
from studyloop.modules.manifest import PREREQUISITE_IDS, ModuleManifest
from studyloop.modules.store import StoreError, load_lockfile, snapshot_dir

if TYPE_CHECKING:
    from pathlib import Path

_VERSION = re.compile(r"\d+(?:\.\d+){1,3}")
_INSTALL_HINTS: dict[str, str] = {
    "docker": "Install Docker (https://docs.docker.com/get-docker/) and put `docker` on PATH",
    "kind": "Install kind (https://kind.sigs.k8s.io/docs/user/quick-start/#installation)",
    "kubectl": "Install kubectl (https://kubernetes.io/docs/tasks/tools/)",
}


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What ``<tool> --version`` said: ``found`` is the binary on PATH, ``version`` the parsed
    dotted number (``None`` when the output carried none or the command failed)."""

    tool: str
    found: bool
    version: str | None
    detail: str


def probe_tool(tool: str, *, path: str | None = None) -> ProbeResult:
    """Look ``tool`` up on ``path`` (default: the process PATH) and run ``<tool> --version``.

    ``tool`` must be one of :data:`PREREQUISITE_IDS`; anything else is refused before any
    lookup, so module text can never choose what gets executed.
    """
    if tool not in PREREQUISITE_IDS:
        raise ValueError(f"{tool!r} is not a prerequisite id ({', '.join(PREREQUISITE_IDS)})")
    binary = shutil.which(tool, path=path)
    if binary is None:
        return ProbeResult(tool, False, None, f"{tool} not found on PATH")
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProbeResult(tool, True, None, f"{tool} --version could not run: {exc}")
    output = (result.stdout + result.stderr).strip()
    match = _VERSION.search(output)
    if result.returncode != 0 or match is None:
        first_line = output.splitlines()[0] if output else "(no output)"
        return ProbeResult(
            tool, True, None, f"{tool} --version exited {result.returncode}: {first_line[:120]}"
        )
    return ProbeResult(tool, True, match.group(0), output.splitlines()[0][:120])


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _below_minimum(version: str, minimum: str) -> bool:
    try:
        have, want = _version_tuple(version), _version_tuple(minimum.lstrip("v"))
    except ValueError:
        return False
    width = max(len(have), len(want))
    return have + (0,) * (width - len(have)) < want + (0,) * (width - len(want))


def _installed_requirements(root: Path | None) -> dict[str, list[tuple[str, str | None]]]:
    """``tool -> [(module id, min version)]`` across the installed modules' manifests."""
    needs: dict[str, list[tuple[str, str | None]]] = {}
    for entry in load_lockfile(root):
        manifest_path = snapshot_dir(entry) / "module.yaml"
        try:
            manifest = ModuleManifest.model_validate(
                yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            )
        except Exception:  # a broken snapshot is reported by its own row below
            needs.setdefault("", []).append((entry.id, None))
            continue
        for prerequisite in manifest.prerequisites:
            if prerequisite.id in PREREQUISITE_IDS:
                needs.setdefault(prerequisite.id, []).append((entry.id, prerequisite.min))
    return needs


def check_module_prerequisites(
    *, store_root: Path | None = None, path: str | None = None
) -> list[CheckResult]:
    """One ``deps`` row per prerequisite tool the installed modules declare.

    No module installed -> no rows and no subprocess. ``store_root`` and ``path`` exist for
    tests (a tmp lockfile, a PATH holding fake binaries); the doctor calls it bare.
    """
    try:
        needs = _installed_requirements(store_root)
    except StoreError as exc:
        return [
            CheckResult(
                "deps",
                "module_prereq_lockfile",
                "fail",
                f"modules.lock.json is unreadable: {exc}",
                "Fix or remove the lockfile, then `studyloop module add` the modules again",
                False,
            )
        ]
    results: list[CheckResult] = []
    for module_id, _ in needs.pop("", []):
        results.append(
            CheckResult(
                "deps",
                f"module_prereq_{module_id}",
                "fail",
                f"installed module {module_id}: snapshot module.yaml is missing or invalid",
                f"studyloop module remove {module_id}, then add it again from its source",
                False,
            )
        )
    for tool in sorted(needs):
        requirers = needs[tool]
        by = ", ".join(sorted({module_id for module_id, _ in requirers}))
        probe = probe_tool(tool, path=path)
        name = f"module_prereq_{tool}"
        hint = _INSTALL_HINTS.get(tool, f"Install {tool}")
        if not probe.found:
            results.append(
                CheckResult("deps", name, "fail", f"{tool} not found (needed by {by})", hint, False)
            )
            continue
        if probe.version is None:
            results.append(
                CheckResult(
                    "deps",
                    name,
                    "warn",
                    f"{tool} is installed but its version is unknown: {probe.detail} "
                    f"(needed by {by})",
                    f"Run `{tool} --version` yourself; the module README names the version needed",
                    False,
                )
            )
            continue
        too_old = sorted(
            f"{module_id} needs >= {minimum}"
            for module_id, minimum in requirers
            if minimum and _below_minimum(probe.version, minimum)
        )
        if too_old:
            results.append(
                CheckResult(
                    "deps",
                    name,
                    "warn",
                    f"{tool} {probe.version} is below the minimum: {'; '.join(too_old)}",
                    f"Upgrade {tool}; {hint}",
                    False,
                )
            )
            continue
        results.append(
            CheckResult("deps", name, "pass", f"{tool} {probe.version} (needed by {by})", "", False)
        )
    return results
