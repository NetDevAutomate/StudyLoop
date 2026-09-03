# Security Policy

## Supported versions

StudyLoop is pre-1.0. Security fixes target the `0.1.x` line only — there is
no older release to backport to.

## Reporting a vulnerability

Please do not open a public GitHub issue for a security concern. Instead, use
[GitHub's private vulnerability reporting](https://github.com/NetDevAutomate/StudyLoop/security/advisories/new)
for this repository, or email the maintainer listed on the
[GitHub profile](https://github.com/NetDevAutomate). Include what you found,
how to reproduce it, and the affected version or commit. We aim to acknowledge
reports within a few days; StudyLoop is a small open-source project run by one
maintainer plus contributors, so please be patient with fix timelines.

## Security model, briefly

StudyLoop is local-first: `studyloop web` binds to `127.0.0.1` by default, and
`--lan` opts in to exposing it on the local network behind HTTP Basic Auth with
a random 128-bit password generated per session unless `lan_password` is set
in `config.yaml`. Provider API keys are encrypted at rest (Fernet, key derived
via HKDF-SHA256 from a local seed file) to protect against someone who can
read `~/.config/studyloop/` but cannot execute code on the machine — it is not
a defense against an attacker who already has a shell there. See
`docs/architecture/current.md` and `packages/studyloop/src/studyloop/secrets.py`
for the full threat model.
