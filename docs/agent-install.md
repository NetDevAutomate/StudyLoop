# Agent Installation Guide

How to set up the AI mentor agents for kiro-cli, Claude Code, Gemini CLI, OpenCode, and Amp.

## Table of Contents

- [What are AI Agents?](#what-are-ai-agents)
- [Automatic Installation](#automatic-installation)
- [Kiro CLI Setup](#kiro-cli-setup)
- [Claude Code Setup](#claude-code-setup)
- [Gemini CLI Setup](#gemini-cli-setup)
- [OpenCode Setup](#opencode-setup)
- [Amp Setup](#amp-setup)
- [Local LLMs (Ollama / LM Studio)](#local-llms-ollama--lm-studio)
- [Agent Descriptions](#agent-descriptions)
- [Skills Reference](#skills-reference)
- [Uninstalling](#uninstalling)

## AI-Guided Setup (Recommended for New Users)

The **install-mentor agent** can guide you through the entire setup process conversationally. It detects your environment, installs packages, configures studyctl, and verifies everything works using `studyctl doctor`.

The prompt lives at [`agents/shared/install-mentor.md`](../agents/shared/install-mentor.md) and works with any AI coding tool. To use it:

```bash
# In Claude Code — just ask:
# "Read agents/shared/install-mentor.md and follow it to set up studyctl"

# Or in any AI tool that can run shell commands, paste the prompt contents
```

The install-mentor uses `studyctl doctor --json` as its contract — it parses the health check output and fixes issues automatically (up to 3 iterations).

## What are AI Agents?

AI agents are custom personas you load into tools like kiro-cli or Claude Code. Instead of a generic assistant, you get a Socratic mentor that knows your learning style, tracks your progress, and teaches through questioning rather than lecturing.

This project ships agents for five platforms:
- **study-mentor** (kiro-cli) — full study pipeline with spaced repetition
- **socratic-mentor** (Claude Code) — Socratic questioning with AuDHD-aware pedagogy
- **mentor-reviewer** (Claude Code) — autonomous code review with scoring
- **study-mentor** (Gemini CLI) — Socratic study sessions with energy-adaptive teaching
- **study-mentor** (OpenCode) — AuDHD-aware study mentor with spaced repetition
- **AGENTS.md** (Amp) — Socratic mentoring loaded automatically from project context

## Automatic Installation

The install script detects which AI tools you have and symlinks the agent definitions:

```bash
./scripts/install-agents.sh
```

It checks for `~/.kiro/`, `~/.claude/`, and `~/.gemini/` directories, and `opencode`/`amp` commands on PATH. If found, it creates symlinks from the repo's `agents/` directory into the tool's config.

Options:

```bash
./scripts/install-agents.sh --kiro      # Kiro CLI only
./scripts/install-agents.sh --claude    # Claude Code only
./scripts/install-agents.sh --gemini    # Gemini CLI only
./scripts/install-agents.sh --opencode  # OpenCode only
./scripts/install-agents.sh --amp       # Amp only
./scripts/install-agents.sh --uninstall # Remove all agent links
```

## Kiro CLI Setup

### Prerequisites

- [kiro-cli](https://github.com/aws/kiro-cli) installed
- `~/.kiro/` directory exists

### What gets installed

The script creates symlinks for:

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/kiro/study-mentor.json` | `~/.kiro/agents/study-mentor.json` | Agent definition |
| `agents/kiro/study-mentor/` | `~/.kiro/agents/study-mentor/` | Agent persona and resources |
| `agents/kiro/skills/study-mentor/` | `~/.kiro/skills/study-mentor/` | Session workflow skill |
| `agents/kiro/skills/audhd-socratic-mentor/` | `~/.kiro/skills/audhd-socratic-mentor/` | Teaching methodology skill |
| `agents/kiro/skills/tutor-progress-tracker/` | `~/.kiro/skills/tutor-progress-tracker/` | Progress tracking skill |

### Starting a session

```bash
kiro-cli chat --agent study-mentor
```

The agent will automatically:
1. Run `studyctl status` to check sync state
2. Run `studyctl review` to find what's due for spaced repetition
3. Run `studyctl struggles` to identify recurring struggle areas
4. Ask your energy level to match session type

### Customizing

Edit the persona at `agents/kiro/study-mentor/persona.md` to adjust:
- Session start behaviour
- Teaching style preferences
- Which CLI commands run automatically

Edit skills in `agents/kiro/skills/` to modify:
- Socratic questioning patterns
- Network→Data Engineering bridges
- Progress tracking thresholds

## Claude Code Setup

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed
- `~/.claude/` directory exists

### What gets installed

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/claude/socratic-mentor.md` | `~/.claude/agents/socratic-mentor.md` | Socratic teaching agent |
| `agents/claude/mentor-reviewer.yaml` | `~/.claude/agents/mentor-reviewer.yaml` | Code review agent |

### Starting a session

```bash
# Socratic mentor — guided learning
/agent socratic-mentor

# Code reviewer — autonomous review with scoring
/agent mentor-reviewer
```

### Customizing

- **socratic-mentor**: Edit `agents/claude/socratic-mentor.md` — it's a markdown file with the full persona, questioning techniques, and learning session orchestration
- **mentor-reviewer**: Edit `agents/claude/mentor-reviewer.yaml` — configure output directories, scoring methodology, and review format

The mentor-reviewer supports environment variable configuration:
- `MENTOR_REVIEW_OUTPUT_DIR` — where review reports are saved (default: `./reviews`)
- `MENTOR_TUTORIAL_DIR` — where tutorials are generated (default: `./tutorials`)

## Gemini CLI Setup

### Prerequisites

- [Gemini CLI](https://github.com/google-gemini/gemini-cli) installed
- `~/.gemini/` directory exists

### What gets installed

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/gemini/study-mentor.md` | `~/.gemini/agents/study-mentor.md` | Subagent definition |
| `agents/gemini/GEMINI.md` | `GEMINI.md` (project root) | Project-level Gemini instructions |
| `agents/shared/` | `~/.agents/shared/` | Shared framework (cross-tool) |

The installer also creates `~/.gemini/settings.json` with `experimental.enableAgents` enabled (required for subagent support). If the file already exists, you'll be prompted to add the setting manually.

### Auto-install

```bash
./scripts/install-agents.sh --gemini
```

### Manual install

```bash
# Create directories
mkdir -p ~/.gemini/agents

# Symlink agent definition
ln -s "$(pwd)/agents/gemini/study-mentor.md" ~/.gemini/agents/study-mentor.md
ln -s "$(pwd)/agents/gemini/GEMINI.md" ./GEMINI.md

# Symlink shared framework
mkdir -p ~/.agents
ln -s "$(pwd)/agents/shared" ~/.agents/shared

# Enable subagents in settings
cat > ~/.gemini/settings.json << 'EOF'
{
  "experimental": {
    "enableAgents": true
  }
}
EOF
```

### Starting a session

```bash
gemini
# Then ask for a study session — the study-mentor subagent is auto-detected
```

## OpenCode Setup

### Prerequisites

- [OpenCode](https://github.com/opencode-ai/opencode) installed
- `opencode` command available on PATH

### What gets installed

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/opencode/study-mentor.md` | `~/.config/opencode/agents/study-mentor.md` | Agent definition |
| `agents/shared/` | `~/.agents/shared/` | Shared framework (cross-tool) |

OpenCode discovers agents from `.opencode/agents/*.md` (project-level) or `~/.config/opencode/agents/*.md` (global). The installer uses the global path.

### Auto-install

```bash
./scripts/install-agents.sh --opencode
```

### Manual install

```bash
# Create directories
mkdir -p ~/.config/opencode/agents

# Symlink agent definition
ln -s "$(pwd)/agents/opencode/study-mentor.md" ~/.config/opencode/agents/study-mentor.md

# Symlink shared framework
mkdir -p ~/.agents
ln -s "$(pwd)/agents/shared" ~/.agents/shared
```

### Starting a session

```bash
opencode
# Press Tab to switch to the study-mentor agent
```

## Amp Setup

### Prerequisites

- [Amp](https://ampcode.com) installed
- `amp` command available on PATH

### What gets installed

| Source | Target | Purpose |
|--------|--------|---------|
| `agents/amp/AGENTS.md` | `AGENTS.md` (project root) | Project-level agent instructions |
| `agents/shared/` | `~/.agents/shared/` | Shared framework (cross-tool) |

Amp reads `AGENTS.md` from the project root automatically — no additional configuration needed.

### Auto-install

```bash
./scripts/install-agents.sh --amp
```

### Manual install

```bash
# Symlink AGENTS.md to project root
ln -s "$(pwd)/agents/amp/AGENTS.md" ./AGENTS.md

# Symlink shared framework
mkdir -p ~/.agents
ln -s "$(pwd)/agents/shared" ~/.agents/shared
```

### Starting a session

```bash
amp
# AGENTS.md is loaded automatically — just start asking for a study session
```

## Local LLMs (Ollama / LM Studio)

studyctl can use local LLMs as the study mentor backend instead of cloud Claude. This uses Claude Code as the frontend but points it at a local model server via environment variables.

### Honest expectations

Local models are a **cost/privacy trade-off with significant capability regression**:

- **Works well**: Simple tasks, single-turn questions, code explanation, light review
- **Works poorly**: Multi-file refactors, complex agentic loops, subagent coordination, test-fix cycles
- **Rough quality**: Best local models (Qwen3-Coder 30B, Devstral 24B) are approximately Claude Haiku 3.5 quality for agentic tasks

If you need reliable multi-step study sessions, cloud Claude is substantially better. Local LLMs are best for privacy-sensitive work, offline use, or cost-free experimentation.

### API compatibility

Claude Code requires the **Anthropic Messages API format** (`/v1/messages`). Not all local backends support this:

| Backend | Anthropic API? | Notes |
|---------|---------------|-------|
| **LM Studio 0.4.1+** | Native | Simplest path. Just load a model and point studyctl at it. |
| **llama.cpp server** | Native (since Nov 2025) | Low-level, good for headless servers. |
| **LiteLLM proxy** | Translates | Bridges Ollama's OpenAI API to Anthropic format. |
| **Ollama (direct)** | No | Only speaks OpenAI format. Needs LiteLLM as a proxy. |

### Recommended models

Models ranked by suitability for studyctl's agentic, multi-turn workflow:

| Model | VRAM/RAM | Context | Best for |
|-------|----------|---------|----------|
| **Qwen3-Coder 30B** | ~19 GB | 256K | Best open-source for coding. Explicit tool-use training. |
| **Devstral 24B** | ~14 GB | 128K | Top SWE-bench open-source. Runs on 32 GB Mac. Apache 2.0. |
| **DeepSeek-Coder-V2 16B** | ~9 GB | 160K | Good at the 16B weight class. |

**Minimum context window**: 64K tokens. Claude Code's system prompt, CLAUDE.md, tool definitions, and file reads consume 20K-50K tokens before your conversation even starts. Models with <32K context will truncate constantly.

**Not recommended**: CodeLlama (superseded), minimax m2.7 (known freeze bug), anything <10B parameters.

### Option A: LM Studio (simplest)

1. Install [LM Studio](https://lmstudio.ai) (0.4.1+)
2. Download and load a model (e.g., Qwen3-Coder 30B)
3. Start the local server (LM Studio > Developer tab > Start Server)
4. Run studyctl:

```bash
studyctl study "Python decorators" --agent lmstudio
```

Config (`~/.config/studyctl/config.yaml`):
```yaml
agents:
  priority: [lmstudio, claude]  # prefer local, fall back to cloud
  lmstudio:
    model: qwen3-coder           # must match what's loaded in LM Studio
    # base_url: http://localhost:1234  # default
```

### Option B: Ollama via LiteLLM proxy

Ollama doesn't speak Anthropic API natively. You need [LiteLLM](https://docs.litellm.ai/) as a translation layer.

1. Install Ollama and pull a model:
```bash
ollama pull qwen3-coder:30b
```

2. Install and configure LiteLLM:
```bash
pip install litellm
```

Create `litellm-config.yaml`:
```yaml
model_list:
  - model_name: qwen3-coder
    litellm_params:
      model: ollama_chat/qwen3-coder:30b
      api_base: http://localhost:11434
```

3. Start LiteLLM:
```bash
litellm --config litellm-config.yaml --port 4000
```

4. Run studyctl:
```bash
studyctl study "SQL window functions" --agent ollama
```

Config:
```yaml
agents:
  priority: [ollama, claude]
  ollama:
    model: qwen3-coder
    # base_url: http://localhost:4000  # default (LiteLLM proxy)
```

### Option C: llama.cpp server (headless)

For servers without a GUI:

```bash
llama-server -m qwen3-coder-30b.gguf --port 8080 --ctx-size 131072
```

Use the LM Studio adapter with a custom base_url:
```yaml
agents:
  lmstudio:
    model: qwen3-coder
    base_url: http://localhost:8080
```

### Known issues

- **Malformed tool calls**: Local models emit invalid tool-use JSON more often than cloud Claude. Claude Code may crash with `Cannot read properties of undefined`. Workaround: `export CLAUDE_CODE_USE_POWERSHELL_TOOL=0`
- **No prompt caching**: Every turn processes the full context from scratch. Sessions feel slower as context grows.
- **No extended thinking**: The effort slider and thinking modes are Claude-specific features.
- **Background tasks use local model**: Claude Code routes statusline updates and codebase searches through the "haiku" model tier. With tier-pinning (which studyctl sets automatically), all of these hit your local GPU.

### Verifying your setup

```bash
studyctl doctor
```

The doctor checks will report:
- Whether ollama/lms binaries are installed
- Whether the local server is responding
- Whether Claude Code is installed (required as the frontend)

## Agent Descriptions

### study-mentor (kiro-cli)

The primary study agent. Integrates with the full studyctl pipeline:

- Checks spaced repetition schedule before each session
- Detects struggle topics from your session history
- Syncs notes to NotebookLM and queries them during teaching
- Records progress via `tutor-checkpoint`
- Adapts session type to your energy level (deep study, light review, body doubling)
- Uses network→data engineering analogies for concept bridging

### socratic-mentor (Claude Code)

A focused Socratic teaching agent with AuDHD-aware pedagogy:

- Teaches through progressive questioning (observation → pattern → principle → application)
- Embeds knowledge from Clean Code (Robert C. Martin) and GoF Design Patterns
- Adapts question difficulty based on demonstrated understanding
- Tracks principle mastery: discovered → applied → mastered
- Never gives direct answers unless explicitly asked (or after 4+ rounds stuck)

### mentor-reviewer (Claude Code)

An autonomous code reviewer that runs without prompting:

- Reads all code files, analyzes against SOLID/OWASP/testing standards
- Scores across 5 categories (1-10): Architecture, Testing, Code Quality, Security, Performance
- Generates detailed reports with critical issues, improvements, and learning opportunities
- Creates tutorials for concepts scoring below 5/10
- Tracks score trends across reviews with evidence-based assessments
- Brutally honest — no praise for mediocre code

## Skills Reference

Skills are modular knowledge packages that agents load for specific capabilities.

### audhd-socratic-mentor

The core teaching methodology skill. Defines:
- Socratic questioning framework (70% questions / 30% strategic info drops)
- AuDHD cognitive support patterns (executive function scaffolding, overload prevention)
- Network→Data Engineering concept bridges (BGP→event streaming, VLAN→data lake zones)
- The golden rule: never give direct answers, guide discovery through productive struggle

### study-mentor

Session workflow and pipeline integration. Defines:
- Session start protocol (status → review → struggles → energy check)
- Spaced repetition schedule and review types
- NotebookLM query integration
- Session type selection based on energy level

### tutor-progress-tracker

Cross-agent progress tracking. Provides:
- Shared assessment database for skill scores
- `tutor-checkpoint` CLI integration
- Score history and trend tracking
- Skill-specific progress queries

## Uninstalling

Remove all symlinks created by the installer:

```bash
./scripts/install-agents.sh --uninstall
```

This only removes symlinks that point into this repo. It won't touch agent files you've created manually or from other sources. Any existing files that were backed up during installation (with `.bak` suffix) remain untouched.
