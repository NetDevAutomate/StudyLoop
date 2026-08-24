"""Collection-time plugin: record which test items could actually RUN.

Why this exists
---------------
The coverage gate (``test_e2e_coverage_gate.py``) asks, for every route / nav
view / CLI command / multiplexer / render surface the live app exposes, "is
this reachable by a test?". Until this plugin existed it answered that by
searching test **source text**, so a test carrying ``@pytest.mark.skip`` still
certified a surface: the string was in the file, and nothing observed whether
the test could execute. Quarantining a suite therefore kept the gate green
while the real proof disappeared -- precisely the false green the gate exists
to prevent.

This plugin writes a manifest of every collected test item together with
whether it is *eligible* to serve as coverage evidence. Eligibility is decided
by **pytest's own marker evaluation**, never by re-reading decorators: by the
time ``pytest_collection_finish`` runs, pytest has already merged module-level
``pytestmark``, class decorators, function decorators, marks added by hooks,
and ``pytest.param(..., marks=...)`` onto each concrete item. Re-implementing
those rules would create a second, incomplete pytest.

Deliberate policy
-----------------
* An active ``skip`` or active ``skipif`` makes an item non-covering.
* An active ``xfail`` makes an item non-covering **even with ``run=True``**: a
  failure that cannot fail CI is not a gate.
* An *inactive* conditional ``skipif`` / ``xfail`` leaves the item covering.
* Parametrised items are judged independently -- one skipped parameter does not
  disqualify a sibling that runs.
* ``skipif`` conditions are evaluated in the current environment, exactly as
  pytest would. A platform-gated test counts on the platform where it runs and
  not on the one where it is skipped. That environment dependence is
  intentional: the gate reports whether *this* environment has an executable
  proof. CI is the canonical answer.
* Imperative ``pytest.skip()`` inside a test or fixture body is **not**
  detected. Collection cannot know whether that branch executes. Closing that
  residual gap needs runtime reports and is out of scope here.

Failure policy: if marker evaluation or manifest writing fails, abort loudly.
Never fall back to raw source scanning -- a silent fallback would restore the
false green this plugin removes.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

MANIFEST_ENV = "STUDYLOOP_COVERAGE_MANIFEST"


def _serialise_params(item: pytest.Function) -> dict[str, str]:
    """Parameter values for one concrete item, as strings.

    Values reach the manifest as ``repr`` output because the gate only ever
    substring-searches them (a route string passed via ``pytest.param`` is
    evidence for that route). Nothing downstream needs the live object, and
    ``repr`` keeps the manifest JSON-serialisable whatever the fixture yields.
    """
    callspec = getattr(item, "callspec", None)
    if callspec is None:
        return {}
    out: dict[str, str] = {}
    for name, value in getattr(callspec, "params", {}).items():
        try:
            out[str(name)] = repr(value)
        except Exception:  # pragma: no cover - defensive: repr should not raise
            out[str(name)] = "<unrepresentable>"
    return out


def _eligibility(item: pytest.Function) -> tuple[bool, str, str]:
    """Return ``(eligible, exclusion_kind, reason)`` using pytest's evaluators.

    Imported lazily and from ``_pytest.skipping`` deliberately. These helpers
    are pytest-internal, but they are the *only* correct implementation of
    marker semantics; the alternative is guessing. The import is asserted at
    plugin load (see :func:`pytest_configure`) so a pytest upgrade that moves
    them fails immediately and visibly rather than silently degrading the gate.
    """
    from _pytest.skipping import evaluate_skip_marks, evaluate_xfail_marks

    skipped = evaluate_skip_marks(item)
    if skipped is not None:
        return False, "skip", str(getattr(skipped, "reason", "") or "")

    xfailed = evaluate_xfail_marks(item)
    if xfailed is not None:
        # Non-covering even when run=True: an xfailing test cannot fail the
        # build, so it proves nothing about the surface staying reachable.
        return False, "xfail", str(getattr(xfailed, "reason", "") or "")

    return True, "", ""


def pytest_configure(config: pytest.Config) -> None:
    """Fail fast if the manifest path is missing or the internals moved."""
    if not os.environ.get(MANIFEST_ENV):
        raise pytest.UsageError(
            f"{MANIFEST_ENV} must be set when loading the coverage collector "
            "plugin; it names the file the manifest is written to."
        )
    try:
        from _pytest.skipping import (  # noqa: F401
            evaluate_skip_marks,
            evaluate_xfail_marks,
        )
    except ImportError as exc:  # pragma: no cover - pytest upgrade guard
        raise pytest.UsageError(
            "coverage collector needs _pytest.skipping.evaluate_skip_marks and "
            f"evaluate_xfail_marks, which are unavailable: {exc}. The coverage "
            "gate cannot judge marker eligibility without them -- fix this "
            "rather than skipping it, or the gate silently starts crediting "
            "quarantined tests again."
        ) from exc


def pytest_collection_finish(session: pytest.Session) -> None:
    """Write one manifest record per collected test function."""
    target = os.environ.get(MANIFEST_ENV)
    if not target:  # pragma: no cover - guarded in pytest_configure
        raise pytest.UsageError(f"{MANIFEST_ENV} is not set")

    records: list[dict[str, Any]] = []
    for item in session.items:
        if not isinstance(item, pytest.Function):
            continue

        eligible, kind, reason = _eligibility(item)
        function = getattr(item, "function", None)
        firstlineno = getattr(getattr(function, "__code__", None), "co_firstlineno", None)

        records.append(
            {
                "path": str(item.path),
                "nodeid": item.nodeid,
                "qualname": getattr(function, "__qualname__", item.name),
                "name": item.originalname or item.name,
                "firstlineno": firstlineno,
                "fixtures": sorted(getattr(item, "fixturenames", ()) or ()),
                "params": _serialise_params(item),
                "eligible": eligible,
                "exclusion_kind": kind,
                "exclusion_reason": reason,
            }
        )

    try:
        with open(target, "w", encoding="utf-8") as handle:
            json.dump({"items": records}, handle)
    except OSError as exc:
        raise pytest.UsageError(
            f"coverage collector could not write its manifest to {target}: {exc}"
        ) from exc
