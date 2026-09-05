# Recovering project history across paths

Exporters preserve the project path recorded by the source harness. To retrieve
one project's history after a move, username change, or known worktree change,
add explicit aliases to the shared StudyLoop `config.yaml`:

```yaml
project_aliases:
  /Users/current/code/personal/tools/studyloop:
    - /Users/previous/code/personal/tools/studyloop
    - /Volumes/Development/code/personal/tools/studyloop
    - -Users-previous-code-personal-tools-studyloop
    - /Users/current/.codex/worktrees/known-id/studyloop
```

Use the canonical full path or any listed alias in the MCP `session_search` or
`session_list` project filter, the hybrid search project filter, or the CLI:

```sh
session-query search "closure" --project /Users/current/code/personal/tools/studyloop
```

The previous `search-cmd` command remains a compatibility alias. Each matches
all explicitly listed paths plus slash-delimited descendants (including legacy
Claude subagent paths). A similarly named `studyloop-other` project does not
match. A simple name such as `studyloop` retains substring search behavior.

Only add paths verified to represent the same project. There is no automatic
basename matching, work/personal merging, username substitution, or destructive
rewriting of historical paths. Copy the configuration to another machine and add
its local project path to the same group. No database migration is required.
