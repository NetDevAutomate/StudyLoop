---
title: "Unified session architecture: 9 research agents corrected 5 plan assumptions"
category: architecture-decisions
tags:
  - tmux
  - ttyd
  - age
  - agent-launcher
  - ipc
  - security
  - simplicity
  - studyctl
module: "studyctl/study (planned)"
symptom: |
  Implementation plan contained incorrect or unnecessarily complex assumptions:
  (1) ttyd TTYD_CREDENTIAL env var assumed to exist but does not in official builds;
  (2) age CLI assumed to be automatable via subprocess but requires a TTY;
  (3) all AI CLIs assumed to support --system-prompt-file but only Claude does;
  (4) tmux -f flag assumed to apply to a running server but is server-level only;
  (5) timer state assumed to need a distributed design (sidebar writes, web resyncs on drift)
    but both consumers can compute from the same state file independently.
root_cause: |
  Plan written before hands-on research against actual tool APIs and docs.
  ttyd's auth is reverse-proxy-delegated (Unix socket + nginx/Caddy htpasswd), not env-var.
  age requires interactive TTY for passphrase; pyrage (Python bindings) + macOS Keychain is
  the correct automation path.
  Agent CLI flags diverge per tool: Claude uses --append-system-prompt-file; Gemini needs
  GEMINI.md; Kiro uses .kiro/agents/*.json; OpenCode uses .opencode/agents/*.md.
  tmux -f is a server-start flag; source-file is required on a running server.
  The distributed timer introduced accidental complexity — a single state file with
  started_at + paused_at + total_paused_seconds lets every consumer compute elapsed
  identically, making drift and resync logic unnecessary.
date: 2026-03-29
---

# Parallel Research Catches Pre-Implementation Assumptions

## Problem

Nine architectural assumptions underpinning the unified session dashboard plan were unverified before planning. During the parallel research and review phase (9 agents: tmux scripting, ttyd auth, AI CLI invocation, 1Password/age, catppuccin tmux, security sentinel, architecture strategist, performance oracle, code simplicity reviewer), five critical assumptions proved false. Each was capable of causing runtime failures, security issues, or unnecessary complexity if implemented as designed.

## Investigation

Nine parallel research agents probed the following areas:

- ttyd process credential passing mechanisms
- age/rage encryption CLI automation
- AI agent CLI flag support for system prompt injection
- tmux `-f` flag behaviour with running servers
- Distributed timer state coordination patterns
- Catppuccin tmux theme vendoring and configuration
- Security review of LAN exposure, IPC files, iframe embedding
- Performance review of SSE polling, tmux status bar, Rich sidebar rendering
- Simplicity review of scope, phasing, and abstraction choices

## Root Cause

Each false assumption shared the same failure mode: relying on GitHub issue discussions, documentation fragments, or intuitive CLI design rather than verifying actual implemented behaviour against installed binaries.

## Solution

### Finding 1: ttyd Authentication

**False assumption**: `TTYD_CREDENTIAL` environment variable passes auth credentials without `ps aux` exposure.

**Reality**: `TTYD_CREDENTIAL` was mentioned in a GitHub issue (#872) but never merged into official ttyd. The `--credential user:password` flag is the only built-in auth, and it exposes the password in `ps aux`.

**Correct pattern**: Unix socket + reverse proxy with htpasswd:
```bash
# ttyd binds to socket only — never touches credentials
ttyd --interface /tmp/ttyd-studyctl.sock -W tmux attach -t study

# nginx handles auth
location /terminal/ {
    auth_basic "Study Session";
    auth_basic_user_file /home/user/.config/studyctl/.ttyd-htpasswd;
    proxy_pass http://unix:/tmp/ttyd-studyctl.sock;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    add_header Content-Security-Policy "frame-ancestors 'self'" always;
}
```

### Finding 2: age Encryption CLI Automation

**False assumption**: `age --decrypt` can be driven via subprocess to retrieve passwords programmatically.

**Reality**: The age CLI opens `/dev/tty` directly for passphrase input. There is no stdin/flag path for the passphrase — subprocess automation is blocked by design.

**Correct pattern**: `pyrage` (Python bindings to Rust `rage`) + macOS Keychain:
```python
from pyrage import passphrase as age_passphrase
import subprocess

# Retrieve encryption key from macOS Keychain (Touch ID unlock)
result = subprocess.run(
    ["security", "find-generic-password", "-a", "studyctl", "-s", "studyctl-age-key", "-w"],
    capture_output=True, text=True
)
enc_key = result.stdout.strip()

# Decrypt in-process — no subprocess, no /dev/tty
encrypted = Path("~/.config/studyctl/lan.age").expanduser().read_bytes()
password = age_passphrase.decrypt(encrypted, enc_key).decode()
```

### Finding 3: AI Agent CLI System Prompt Injection

**False assumption**: All AI agent CLIs support system prompt injection via a CLI flag.

**Reality**:

| Agent | Persona mechanism |
|-------|------------------|
| Claude | `--append-system-prompt-file /path/to/file` (preserves built-in tool awareness) |
| Gemini | `GEMINI.md` file in working directory (auto-loaded) |
| Kiro | `.kiro/agents/*.json` config file with `"prompt"` field |
| OpenCode | `.opencode/agents/*.md` config file with YAML frontmatter |

**Correct pattern**: Two-phase launcher — ensure config files exist, then spawn:
```python
def launch_agent(agent: str, session_dir: Path, persona_file: Path) -> None:
    # Phase 1: ensure agent config exists in tool-specific location
    match agent:
        case "claude":
            pass  # uses --append-system-prompt-file at spawn time
        case "gemini":
            (session_dir / "GEMINI.md").write_text(persona_file.read_text())
        case "kiro":
            kiro_dir = session_dir / ".kiro" / "agents"
            kiro_dir.mkdir(parents=True, exist_ok=True)
            (kiro_dir / "study.json").write_text(
                json.dumps({"prompt": persona_file.read_text()})
            )
    # Phase 2: spawn with agent's own invocation pattern
    ...
```

Ship Claude-only initially. Add other agents as their invocation patterns are verified against actual binaries.

### Finding 4: tmux Config Overlay

**False assumption**: `tmux -f custom.conf new-session` applies a per-session config.

**Reality**: `-f` is a server-level flag. If a tmux server is already running when the command is issued, `-f` is **silently ignored** — the existing server config wins.

**Correct pattern**:
```python
import subprocess, os

# Create session first, then apply config via source-file
subprocess.run(["tmux", "new-session", "-d", "-s", session_name], check=True)
subprocess.run(["tmux", "source-file", "/path/to/studyctl-tmux.conf"], check=True)

# Capture pane IDs at creation — NEVER reference by index (they shift)
result = subprocess.run(
    ["tmux", "split-window", "-h", "-P", "-F", "#{pane_id}", "-t", session_name],
    capture_output=True, text=True, check=True,
)
pane_id = result.stdout.strip()  # e.g. "%3" — stable for pane lifetime

# Attach by replacing the current process (no zombie parent)
os.execvp("tmux", ["tmux", "attach-session", "-t", session_name])
```

### Finding 5: Distributed Timer State

**False assumption**: The sidebar process is the authoritative timer, writing `elapsed_seconds` to the state file every 60s. The web dashboard resyncs when drift exceeds 30s.

**Reality**: This is a distributed state coordination problem for a personal timer where +/-30s accuracy is irrelevant. The complexity has no payoff.

**Correct pattern**: Store instants, compute elapsed everywhere:
```json
{
  "started_at": "2026-03-28T09:00:00Z",
  "paused_at": null,
  "total_paused_seconds": 0
}
```

```python
from datetime import datetime, timezone

def compute_elapsed(state: dict) -> float:
    started = datetime.fromisoformat(state["started_at"])
    if state["paused_at"]:
        end = datetime.fromisoformat(state["paused_at"])
    else:
        end = datetime.now(timezone.utc)
    return (end - started).total_seconds() - state["total_paused_seconds"]
```

Both the sidebar and web dashboard call `compute_elapsed()` independently against the same state file. Because `started_at` is the single source of truth, both surfaces produce identical values — zero drift by construction. The reconciliation protocol is deleted entirely.

## Prevention Strategies

### The Core Pattern: Unverified CLI Capability Assumptions

Before encoding any CLI tool behaviour as a plan assumption, treat it as an untested hypothesis. The cost of a 5-minute verification is trivially lower than discovering the assumption is wrong mid-implementation.

### Per-Finding Prevention

**1. ttyd TTYD_CREDENTIAL**: For any CLI tool's configuration interface (env vars, flags, config files), verify against `--help` output or the tool's man page before committing it to a plan. Environment variable support is rarely documented in `--help` but is often absent.

```bash
ttyd --help 2>&1 | grep -i cred
strings $(which ttyd) | grep -i credential  # last resort
```

**2. age requires TTY**: Any tool that handles secrets or passphrases has a high prior probability of requiring TTY interaction intentionally (as a security feature). Always verify non-interactive invocation is supported before designing an automation flow around it.

```bash
echo "test" | age --passphrase - /dev/null 2>&1  # does it accept stdin?
age --help 2>&1 | grep -iE 'passphrase|batch|non-interactive|stdin'
```

**3. Agent CLI flags diverge**: Agent CLI interfaces are not standardised. Treat each agent binary as a separate verification target. Create a capability matrix at design time.

```bash
claude --help 2>&1 | grep -i system
gemini --help 2>&1 | grep -i system
# If the flag doesn't appear in --help, it doesn't exist.
```

**4. tmux `-f` is server-level**: For any tool that distinguishes server/session/window/pane scope, verify which scope a configuration mechanism applies to before using it for isolation.

```bash
tmux new-session -d -s test1
tmux -f /tmp/other.conf new-session -d -s test2 2>&1  # silently ignored?
tmux show-options -g | head -5  # confirm options reflect running server
```

**5. Distributed timer unnecessary**: Before designing a synchronisation protocol, ask: "can this be computed from a single source of truth rather than merged from multiple sources?" Write the read-side formula first. If it's `f(shared_state, now())` with no merge logic, reconciliation is unnecessary.

### General Protocol for Plan Authorship

1. **List all CLI tools the plan depends on.** For each, identify every capability being assumed.
2. **Classify each assumption** as: *Verified* (ran the command), *High-confidence* (in `--help`/man page), or *Assumed* (inferred from docs/memory/similar tools).
3. **Promote every *Assumed* item to a pre-implementation spike.** A 10-line bash script that exercises exactly the capability the plan requires.
4. **Security and TTY assumptions deserve extra scepticism.** Tools handling secrets are intentionally hostile to automation. Assume they require TTY unless proven otherwise.
5. **Scope assumptions deserve extra scepticism.** Multiplexers, daemons, and servers frequently have server/session/process distinctions that are non-obvious.

**The meta-pattern**: A plan that cannot be verified incrementally against real binaries before implementation begins is a plan that contains hidden integration tests. Surface them early.

## Related Documentation

- **Brainstorm (session architecture)**: `docs/brainstorms/2026-03-29-unified-session-architecture-brainstorm.md`
- **Plan (partially deepened)**: `docs/plans/2026-03-29-feat-unified-session-architecture-plan.md`
- **Original dashboard brainstorm**: `docs/brainstorms/2026-03-28-live-study-session-dashboard-brainstorm.md`
- **Security review**: `docs/reviews/2026-03-15-security-review-unified-study-platform.md`
- **Architecture review**: `docs/reviews/2026-03-15-architecture-review.md`
- **Marathon session learnings**: `docs/solutions/2026-03-13-marathon-session-learnings.md`
- **FastAPI+HTMX research**: `docs/research/fastapi-htmx-best-practices.md`
