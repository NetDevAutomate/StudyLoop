"""Helpers for the Persona A / Persona B scripted acceptance journeys (module-contract v1, U1).

``test_module_personas.py`` is the test; this package is what it stands on:

- :mod:`.bundle` -- the failure bundle: the four members design.md §6 adds (server log, CLI
  transcript, ``modules.lock.json`` diff, attempt envelope) plus the browser artefacts,
  redacted and then verified with the UAT tier's own detector (``acceptance/uat/redaction.py``,
  imported, never copied).
- :mod:`.world` -- one persona's world: the hermetic server (``tests/e2e/_env.py``), the
  learner's CLI with every call transcribed, the browser helpers lane W's e2e journey keeps
  private (copied, as the brief allows; the journey itself is never edited or imported for
  them), the wall-clock budget and the phase runner that writes the bundle on failure.
- :mod:`.modules` -- the "missing kind" fixture module built from ``valid-scaffold``.

Nothing here is a test: pytest collects ``test_*`` files only, and none live in this package.
"""
