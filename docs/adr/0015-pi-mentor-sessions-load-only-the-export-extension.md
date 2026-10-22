# ADR-0015: pi mentor sessions load StudyLoop's export extension and no other

**Status:** Accepted, 2026-10-22 (proposed and implemented the same day; the owner accepted the
eight pass-3 records together at 16:36 BST) · **Date:** 2026-10-22 · **Deciders:** council pass 3
of the 2026-10-21 full-repository review (five no-tool seats: kimi-k3, gpt-6-astra, grok-4.6,
deepseek-r1, mistral-large-3), arbitrated by argument by the review coordinator under the owner's
standing delegation; accepted by Andy Taylor (owner). · **Change:** 2026-10-22 council pass 3, ruling D3 (the council split (a)/(c) only on a
fact the coordinator then verified); implemented in `bd3557e9`, merge `e4360e64` (lane F).

The council record (`reviews/2026-10-21-full-repo-review/`, gitignored, owner's machine only)
holds the seat transcripts; everything this record relies on is restated here. Symbols were read
at `309074c7`.

## Context

`studyloop study` launches pi with `--no-extensions`. That was deliberate and documented
(`docs/architecture/pi-harness-integration.md`): the learner's own pi extensions, including any
that choose a model, must not load into a mentor session, so the launch is extension-independent
and model-neutral. The documented cost was that StudyLoop's **own** `session_shutdown` export
extension (installed at `~/.pi/agent/extensions/studyloop-session-export.ts` by
`studyloop install agents --tool pi`) did not load either, so the session export in a mentor
session "depends on the agent following the mandate" in `~/.pi/agent/session-db.md`. The
review's survey finding F-CLI-03 called this a defect; it was a trade-off, and the question was
whether it was the right one.

The fact that decided it was verified on the machine, not assumed: `pi --help` documents
`--extension, -e <path>` ("Load an extension file … can be used multiple times") and
`--no-extensions, -ne` ("Disable extension discovery … **explicit -e paths still work**"). So
"load exactly one extension and suppress discovery of the rest" is a combination pi supports by
design. Two seats had guessed at a flag name (`--load-extension=<path>`) that pi does not have;
the claim behind the guess was true.

## Decision

`_pi_launch` (`adapters/pi.py`) builds

```
pi --no-extensions -e <installed export extension path>        # start
pi --no-extensions -e <installed export extension path> --continue   # resume
```

when `installers._pi_hook_path()` exists (the adapter imports the path helper rather than
duplicating the literal), with the path `shlex.quote`d. When the extension is **not** installed the
launch falls back to plain `pi --no-extensions` and the mandate is the only export path, exactly
as before.

The ruling also adopted (a)'s second half: an **end-of-session check** that the export landed,
with a visible warning if not, because a reliability feature must not depend on an agent obeying
prose, and even a loaded extension can fail. **That check is not built.** The lane found it needs
`session/cleanup.py` and the summary screen, which it did not own, and that the adapter hook runs
before tmux is killed, which is the wrong moment to check. It is ledgered for a lane that owns the
teardown. Until it lands, the mandate remains the fallback for the export, as the architecture
document says.

Grounding adopted: least functionality (nothing but StudyLoop's extension loads, so the
model-neutrality `--no-extensions` protected is kept) and fail-safe defaults (verify the export,
do not trust the prompt).

## Alternatives considered

- **(a) Keep plain `--no-extensions`; strengthen the fallback (persona mandate plus the
  end-of-session check).** Preferred by seats that treated single-extension loading as unknown.
  Once verified, (c) dominates it: the export runs by code rather than by compliance, and (a)'s
  check is kept anyway.
- **(b) Drop `--no-extensions` so the export extension loads along with everything else.**
  Rejected under every value of the fact: it lets the learner's model-choosing extensions into a
  mentor session, which is the very thing the flag exists to prevent.

## Consequences

- In a StudyLoop-launched mentor session the export extension **is** loaded; the mandate is the
  fallback, not the mechanism. `docs/architecture/pi-harness-integration.md` and
  `test_release_harnesses.py` were updated from the old contract (exact `pi --no-extensions`
  strings) to the new one, both branches.
- The adapter now depends on `installers._pi_hook_path()` for the installed location; moving the
  extension means changing one helper, not two literals.
- A pi upgrade that changes the semantics of `-e` under `--no-extensions` would silently return
  mentor sessions to mandate-only export. The end-of-session check is what would detect that;
  until it exists, the per-harness probe in the release checklist is the only guard.

## Verification

`packages/studyloop/tests/test_release_harnesses.py`: with the extension file present the command
carries `-e <path>` and `--no-extensions`; absent, `--no-extensions` and no `-e`; resume appends
`--continue` in both cases. Coordinator probe on the lane tree: all three launch strings
(extension absent, present, resume) rendered as specified.
