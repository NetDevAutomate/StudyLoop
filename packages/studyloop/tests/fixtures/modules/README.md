# Module conformance fixtures (proposal §6, MC001–MC017)

`valid-scaffold/` is a complete, minimal, offline module: one `echo`-based drill whose
check is `scripts/check.sh` (exit 0), a `workdir` target, no prerequisites, the four
README headings, `LICENSE`, `CHANGELOG.md`, `mentor/brief.md`.

Each `mcNNN/` holds two full modules so that neither is nested inside the other
(MC009 and MC012 scan "anywhere in the module"):

- `mcNNN/broken/` — a copy of the valid scaffold breaking **exactly** rule `MCNNN`;
- `mcNNN/repaired/` — the minimal repair; a valid module (`valid-scaffold` itself, or a
  valid variant that keeps the broken twin's extra material).

`diff -r --no-dereference mcNNN/broken mcNNN/repaired` shows the repair and nothing else.

| Fixture | Broken twin | Repaired twin |
| --- | --- | --- |
| mc001 | `module.yaml` has an unknown key `homepage` (`extra: forbid`) | key removed |
| mc002 | `contract: 99` | `contract: 1` |
| mc003 | `CHANGELOG.md` missing | present |
| mc004 | task has an unknown key `difficulty` (`PracticeDeck` rejects it) | key removed |
| mc005 | `prerequisites: [{id: duckdb}]` (named as *not* in v1, §5.4) | `[{id: docker, min: "24"}]` |
| mc006 | deck uses `setupCommand: scripts/setup.sh`, `capabilities: [check]` | `capabilities: [setup, check]` |
| mc007 | `command: scripts/check-missing.sh` (relative, does not exist) | `scripts/check.sh` |
| mc008 | `target.kind: kubeconfig-context`, `command: scripts/check.sh --context prod` | override removed (kind unchanged) |
| mc009 | `scripts/check.sh` has `export PASSWORD="0123456789abcdef"` | line removed |
| mc010 | task has `solution` but no `scaffolding` | `scaffolding: guided` |
| mc011 | `README.md` lacks `## Limits` | heading present |
| mc012 | `setup.py` at the module root | file absent |
| mc013 | `scripts/check.sh` is a symlink to `check-impl.sh` | regular file |
| mc014 | task `id` missing | `id: echo-01` |
| mc015 | `command: scripts/check.sh && echo ok` (shell operator) | `scripts/check.sh` |
| mc016 | `capabilities: [check, cleanup]`, no deck uses `cleanupCommand` | `[check]` |
| mc017 | `target.kind: kubeconfig-context`, task has `setupCommand` but no `cleanupCommand` | `cleanupCommand: scripts/cleanup.sh` (+ `cleanup` capability, `scripts/cleanup.sh`) |

## What these fixtures pin for the engine (C2)

The rule table overlaps in places; each broken twin was chosen so that a correct engine
reports one rule id and nothing else. The choices imply:

- **MC001 vs MC002/MC005** — a bad `contract` or `prerequisites[].id` is reported as
  MC002/MC005, not as a manifest validation failure (keep `contract: int` and
  `prerequisites[].id: str` in the manifest model and check the sets separately, or map
  those validation errors to their rule ids).
- **MC004 vs MC010** — a missing `expectedLearningOutcome` or empty `successCriteria` is a
  schema rejection, so MC010's only single-rule fault is `solution` without `scaffolding`.
- **MC004 vs MC014** — under S2's `PracticeDeck`, duplicate or malformed ids are schema
  rejections; a *missing* id is accepted by the schema (`id: SlugId | None`) and is the
  MC014 fault used here. Reporting duplicate/malformed ids as MC014 needs an explicit
  mapping in the engine.
- **MC006 vs MC016** — a phase field without its capability is MC006; a capability with no
  deck using it is MC016. `terminal` is never used by a deck field; the fixtures avoid it.
- **MC017 vs MC008/MC016** — a `kubeconfig-context` task must carry `setupCommand` and
  `cleanupCommand` (the disposable cluster is created by `setup` and deleted after `cleanup`,
  K0-review F6), so every kubeconfig-context fixture -- mc008's twins included -- declares and
  uses all three phases; mc017/broken omits only `cleanupCommand` and its capability together,
  so MC016 stays quiet and MC017 is the one finding.
- **MC007 vs MC013 vs MC015** — commands are tokenised (mc008 and mc015 require it); a
  referenced script that does not exist is MC007 only; an existing path of the wrong kind
  (symlink here) is MC013 only; an operator token is MC015 only. No fixture uses an
  absolute path, which MC007 and MC015 would both flag.
- **MC009** — the fake secret is a hex sequence that detect-secrets' `is_sequential_string`
  heuristic filters at commit time (so the fixture commits). The engine runs the keyword
  detector family with those filters disabled (coordinator ruling, spec "optional-modules"),
  so `export PASSWORD="0123456789abcdef"` **is** flagged by `module check`; the finding names
  the keyword and the line, never the value.
