# Stage19: scope before retrieval

Stage18 protected the new canonical store. The older query interfaces still read
the same `sessions.db`, so they also need the scope boundary. This stage connects
one policy to the existing CLI, MCP, lexical search, vector candidate reads and
attached full database. It is a production increment, not full shipping acceptance.

## Run the lesson

From the evaluation worktree:

```sh
uv run python -m experiments.evidence_context.scope_boundary.runner --output /tmp/evidence-stage-19
open /tmp/evidence-stage-19/walkthrough.html
uv run pytest experiments/evidence_context/tests/test_scope_boundary.py packages/agent-session-tools/tests/test_context_scope.py packages/agent-session-tools/tests/test_context_public_scope.py packages/agent-session-tools/tests/test_context_policy_cli.py -q
```

Use a fresh output directory. The runner creates three fictional conversations,
an isolated config and a disposable database. Eight real Python CLI subprocesses
exercise preview, apply, retrieval and reclassification. There are no model calls,
installed hook changes or reads from the owner's conversations.

## The problem this solves

Codex, Claude Code and Kiro can each contain personal and work conversations. A
harness name therefore cannot establish the boundary. A project filter such as
`--project /work/project` is a search request, not permission to change context.

Think of scope like a routing domain: a destination filter narrows what you seek
inside the permitted domain. It does not move the request into another domain.
Here this is a local process policy, not protection from an OS user who can read
the database directly or change the configuration.

## Configuration owns the classification

The fixture starts with:

```yaml
memory:
  default_scope: personal
  projects:
    demo-personal:
      scope: personal
      roots: [/demo/personal]
    demo-work:
      scope: work
      roots: [/demo/work]
```

Project IDs are stable names. Roots are local machine paths. The most specific
configured root wins; `/demo/personal-sibling` is not beneath `/demo/personal`.
Explicit per-session assignments outrank root defaults. Harness, hostname and
words in the conversation never select a scope.

Request scope comes from an explicit owner process setting
`SESSION_CONTEXT_SCOPE`, then the current directory's configured root, then the
explicit `memory.default_scope`. The shipped default is null: missing policy
raises a useful error. An owner may deliberately choose `unclassified` as their
default, but it is not silently selected by the product. MCP tool arguments do
not expose an override.

## Why preview and apply are distinct commands

```sh
session-context policy plan --db /path/to/sessions.db
session-context policy apply --db /path/to/sessions.db
```

`plan` backs up the database into memory, migrates that copy if needed and reports
the proposed classifications. The source schema, conversations and audit history
stay unchanged. `apply` upgrades the selected database and atomically stores
classification changes, an actor-labelled audit and the policy fingerprint.

The fingerprint identifies the applied project definitions: IDs, scopes and
roots. It does not attest every session assignment, and it does not include the
current request scope. Merely switching from a personal request to a work request
should not reclassify stored conversations.

If config changes before apply, readers stop with an actionable error. This
avoids interpreting newly edited config against stale stored classifications.
If an audit insert fails, project and session changes roll back together.

## What the eight commands demonstrate

| Step | Observation | Meaning |
|---|---|---|
| Query before apply | Exit 2; policy error | Config presence does not prove classification was applied. |
| Preview | Four proposed changes; zero audit writes | Two projects and two matching sessions would be classified. |
| Apply | Changes committed with audit | Sources are classified by explicit roots. |
| Personal search | One personal result | All three records use the same harness; only scope distinguishes them. |
| Work project filter | Empty result | Search filters cannot widen the request scope. |
| Edit personal project to work, then query | Exit 2 | Drift is withheld until applied. |
| Apply reclassification | Project audit records added | Source bodies are not rewritten. |
| Next personal query | Empty result | Reclassification affects the next request. |

The final JSON configuration shows both projects as work because it records the
end of this journey. Earlier command outputs preserve the original personal
classification. All three source bodies remain stored: withholding is not deletion.

## Where the guard runs

The existing CLI search/list/show/context/continue/stats paths, direct and prefix
ID resolution, MCP tools, file hotspots, FTS and vector candidates now apply the
predicate before selecting source bodies. Prefix ambiguity is computed only from
visible IDs. Each attached full database also needs an applied compatible policy.
The shared guard starts a read transaction before checking policy and reading bodies;
configuration is reloaded on the next request.

Tests include the real MCP stdio protocol in a child process, not only Python
function calls. They cover negative bodies, references, reclassification, attached
databases, vector candidates and actual CLI results. A successful stdio test in the
workspace is still not proof of a freshly installed wheel or harness registration.

## Older databases and removed projects

An older database without scope tables is inspectable as explicit unclassified
only when there are no configured projects. With configured projects, run plan
and apply first. A classified request against a table-less database is an error,
not an empty search that could be mistaken for missing history.

Removing a root unassigns matching root-derived assignments. Explicit and synced
assignments are retained when no local root matches. If their project is removed
from configuration, that project is stored as unclassified and its remaining
assignments are withheld from all ordinary queries. To inspect them, explicitly
restore that stable project ID in config with `scope: unclassified` and apply.
This prevents an absent project definition from silently broadening access.

Tombstones exclude a session in every scope. This check is a read guard; complete
forgetting, exporter suppression and sync/restore propagation remain separate work.

## Why keep SQLite

The missing capability was consistent policy enforcement across readers. Changing
the engine would leave the same bypasses unless every interface adopted the rule.
SQLite already supports indexed assignment lookups and atomic audit writes in the
canonical database. This stage tests correctness; it does not compare large-scale
query latency or establish superiority over a graph database.

## Evidence and limits

The final package regression passed 1,190 tests. The independently runnable
Stage19 check passed 35 tests, and the experiment suite passed 252 with one optional
dependency skip. Workspace pyright and lint passed. See the council decision for
exact review coverage.

Still required for the full production goal: StudyLoop-specific consumers, native
capture into canonical sources, complete derived-data ownership, protected sync,
forget/restore, selectable installation and installed-package journeys. Existing
`session-clean` still needs complete canonical-copy lifecycle integration. None of
these are implied complete by this stage's scope tests.

The earlier stages and the Stage8 exercise remain unchanged.
