---
title: "Phase 2 Complete — Multi-Agent Support (Gemini, Kiro, OpenCode)"
date: 2026-04-04
---

# Session Handoff — 2026-04-04

## What Was Done

### Phase 2: Multi-Agent Support (complete)

| Commit | Description |
|--------|-------------|
| `55a2ae2` | feat: Phase 2 multi-agent support — wire Gemini, Kiro, OpenCode adapters |
| (pending) | fix: doctor Kiro binary name + agent smoke tests |

### Architecture After This Session

```
agent_launcher.py (single file, ~460 lines)
├── AgentAdapter          frozen dataclass with setup/launch/teardown/mcp callables
├── _claude_setup()       temp .md file + --append-system-prompt-file flag
├── _gemini_setup()       GEMINI.md in session cwd (auto-loaded) + .gemini/settings.json
├── _kiro_setup()         atomic JSON update at ~/.kiro/agents/ + backup + teardown
├── _opencode_setup()     .opencode/agents/*.md with YAML frontmatter + opencode.json
├── AGENTS registry       dict[str, AgentAdapter] — 4 agents, insertion order = priority
├── detect_agents()       configurable priority (config.yaml + STUDYCTL_AGENT env var)
├── build_canonical_persona()  agent-agnostic persona builder
└── backward-compat wrappers   build_persona_file(), get_launch_command()
```

### Per-Agent Mechanisms (Verified)

| Agent | Binary | Persona | Resume | MCP Config |
|-------|--------|---------|--------|------------|
| Claude | `claude` | `--append-system-prompt-file {temp}` | `claude -r` | `mcp.json` in session dir |
| Gemini | `gemini` | `GEMINI.md` in cwd | `gemini -r` | `.gemini/settings.json` |
| Kiro | `kiro-cli` | JSON at `~/.kiro/agents/` with `file://` prompt | `kiro-cli chat --resume` | `mcpServers` in agent JSON |
| OpenCode | `opencode` | `.opencode/agents/study-mentor.md` + YAML frontmatter | `opencode -c` | `opencode.json` (array cmd, `enabled`, `environment`) |

### Key Design Decisions

1. **Frozen dataclass with callables** (not Protocol) — 3 reviewers recommended this for 4 static adapters in a single file
2. **No package split** — `agent_launcher.py` stays as one file (~460 lines)
3. **Kiro atomic write** — backup existing JSON, write to temp, `os.replace()`, teardown restores backup
4. **OpenCode MCP schema differs** — `command` is array, `enabled` not `disabled`, `environment` not `env`
5. **Config is YAML** — `AgentsConfig` dataclass with `priority: list[str]`, env var override via `STUDYCTL_AGENT`

### Test Suite

```
532+ tests collected (CI-safe, excluding tmux integration)
  45 agent launcher unit tests (from 10)
  11 doctor agent tests (from 7)
   8 multi-agent integration tests (new, in test_study_integration.py)
   0 failures
```

### Files Changed

| File | Change |
|------|--------|
| `agent_launcher.py` | Replaced dict registry with AgentAdapter dataclass + 4 adapters |
| `cli/_study.py` | Dynamic --agent choices, adapter callables, teardown wiring |
| `settings.py` | AgentsConfig dataclass, agents: YAML key, default config template |
| `session/cleanup.py` | Adapter teardown in session end path |
| `doctor/agents.py` | Fixed kiro → kiro-cli, added smoke test checks, registered in doctor |
| `cli/_doctor.py` | Registered check_agent_smoke_tests |
| `test_agent_launcher.py` | 45 tests: registry, detection, adapters, env var, canonical persona |
| `test_doctor_agents.py` | 11 tests: kiro-cli binary, smoke test success/failure/timeout |
| `test_study_integration.py` | 8 tests: multi-agent session launch with artifact verification |

## What's NOT Done

- **Git push not done** — 2 commits on `feat/multi-agent` branch, not pushed
- **Plan docs not committed** — `docs/plans/2026-04-03-feat-multi-agent-support-plan.md` is untracked
- **Agent-native MCP tools** — `list_available_agents()`, `set_agent_preference()`, `run_doctor_checks()` via MCP. Roadmap item.
- **Agent switching mid-session** — Switch agents within an active tmux session. Roadmap item.
- **Per-agent persona tuning** — Gemini/Kiro may respond differently to certain prompt structures

## Known Issues

1. **Kiro global state** — `_kiro_setup()` writes to `~/.kiro/agents/study-mentor.json` (global side effect). Mitigated with atomic write + backup + teardown, but a crash mid-session could leave modified config. The `STUDYCTL_KIRO_AGENTS_DIR` env var redirects this for testing.
2. **OpenCode least tested** — Adapter is implemented from research + `--help` output. Needs validation with a real OpenCode binary when installed.
3. **Gemini MCP path** — Uses absolute `_REPO_ROOT` path for the studyctl-mcp server. Works for dev installs but may need adjustment for pip installs.

## Next Phase: Phase 3 — Devices (ttyd + LAN)

From the roadmap:
- ttyd via nginx/Caddy proxy
- `studyctl study --lan` flag
- Docker `studyctl-web` image (deferred from Phase 6)

### Suggested Starting Point

1. Read this handoff document
2. Push `feat/multi-agent` to remote: bundle+scp to user@192.168.1.22
3. Merge to main or keep as feature branch
4. Start Phase 3 brainstorm with `/workflows:brainstorm`

### Also Consider

- Merge `feat/multi-agent` → `main` and tag v2.3.0
- Run integration tests (`test_study_integration.py`) with real tmux to validate multi-agent sessions end-to-end
- Install Gemini CLI or OpenCode to validate adapters against real binaries
