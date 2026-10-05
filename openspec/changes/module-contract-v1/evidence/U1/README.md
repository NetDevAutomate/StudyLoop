# Lane U1 evidence — reading guide

Transcripts: `<name>.red.txt` / `<name>.green.txt` pairs (command on line 1, sha + UTC on line 2),
`persona-a-*` / `persona-b-*` for the phase flips, `fixpass-*` for the U1-review fix pass, the
gate transcripts last. `forced-failure-bundle/` is one real failure bundle, committed verbatim.

## The forced-failure bundle's members (U1-review F1, F4)

- `server-log.txt` — the subprocess server's output. `.txt`, not `.log`: the repository ignores
  `*.log` (`.gitignore`, "Logs"), which is how the first bundle's manifest came to name a member
  the tree did not carry (F1).
- `labs-binding.json` — what a Labs start left behind: the state file's `labs_drill` record, the
  session it was bound to, the view's drill nonce (redacted) and the ids of every attempt the
  CLI opened. The first bundle called this `attempt-envelope.json`; it never was one (F4).
- `practice-envelope.json` — **absent by design**: it is the production `PracticeCheckEnvelope`
  the CLI posts after a drill phase ran, validated through
  `session.module_delivery.validate_envelope` before it is written, and **no persona executes a
  phase** (proposal §7: the browser never executes; the CLI phases are the kdrill live proof's).
  The writer path exists and is unit-tested (`TestBundleWriter`); a persona step that ever runs
  `studyloop drill check` will produce the member without further change (the world rebuilds it
  from the attempt sidecar the CLI wrote). The manifest records `practice_envelope: null`.
