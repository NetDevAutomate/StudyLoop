"""The UAT (sign-off) tier — lane B4.

The UAT tier has its OWN additional opt-in on top of acceptance
(``STUDYLOOP_UAT=1``, enforced by ``conftest.py`` in this package) and
lives under this subtree specifically so that a plain ``testacc``-shaped
invocation never collects it — see the ``--ignore`` flag on the
``testacc`` recipe and the dedicated ``testuat`` recipe in the Justfile,
and ``docs/acceptance-testing.md``.

What lives here:

- :mod:`acceptance.uat.bundle` — the full evidence-bundle writer (manifest
  schema, file inventory with sha256s, the durable-root resolution rule).
- :mod:`acceptance.uat.redaction` — the versioned, hash-pinned redaction
  rule list and the redacted-summary generator ``releases/`` may ingest.
- :mod:`acceptance.uat.rubric` — the versioned, hash-pinned sign-off
  rubric loader.
- :mod:`acceptance.uat.strict_runner` — the strict "no skipped required
  cells, zero-selected fails" sign-off semantics (council D-13).
- ``test_journey_smoke.py`` — a CI-safe mechanics smoke test wiring the
  three above together against the hermetic server + a scripted actor.

Every mechanism above ALSO has an ungated unit-test twin living directly
under ``tests/`` (``test_uat_bundle_writer.py``,
``test_uat_redaction.py``, ``test_uat_rubric_loader.py``,
``test_uat_strict_runner.py``) — council D-19/D-26: a drift guard gated
behind an opt-in nobody sets in CI never actually guards anything, so the
MECHANISM tests run in every ``just test``, and only the live-ish journey
smoke test lives here, behind both opt-ins.
"""

from __future__ import annotations
