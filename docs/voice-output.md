# Voice Output

`study-speak` is a TTS CLI tool that speaks agent responses aloud using kokoro-onnx — an 82M parameter model with the `am_michael` voice. Designed for AuDHD learners who benefit from auditory reinforcement alongside visual text.

---

## Quick Start

### Install

```bash
uv tool install "./packages/agent-session-tools[tts]" --force
```

### Download Models

Models download automatically on first run. The install script also offers to pre-download them:

```bash
./scripts/install.sh  # prompts: "Download voice model now? [y/N]"
```

To download manually:

```bash
mkdir -p ~/.cache/kokoro-onnx && \
  curl -fsSL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
    -o ~/.cache/kokoro-onnx/kokoro-v1.0.onnx && \
  curl -fsSL https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin \
    -o ~/.cache/kokoro-onnx/voices-v1.0.bin
```

### Test

```bash
study-speak "Hello, can you hear me?"
```

---

## Agent Integration

Voice is **off by default**. Toggle it during a session:

=== "Kiro CLI"

    ```
    @speak-start    # enable voice
    @speak-stop     # disable voice
    ```

    Kiro uses a native MCP tool for speech.

=== "Claude Code"

    ```
    /speak-start    # enable voice
    /speak-stop     # disable voice
    ```

    Uses shell command `~/.local/bin/study-speak`.

=== "Gemini / OpenCode / Amp"

    ```
    @speak-start    # enable voice
    @speak-stop     # disable voice
    ```

    Uses shell command `~/.local/bin/study-speak`.

When enabled, the agent speaks core questions, answers, key principles, and teaching moments — **excluding code blocks, scaffolding, and long explanations**.

---

## Configuration

`~/.config/studyctl/config.yaml`:

```yaml
tts:
  backend: kokoro        # kokoro | qwen3 | macos
  voice: am_michael      # kokoro voices: am_michael, af_heart, bf_emma, etc.
  speed: 1.0             # 0.5 = slow, 1.0 = normal, 1.5 = fast, 2.0 = very fast
  macos_voice: Samantha  # fallback voice for macOS say
```

### Available Kokoro Voices

| Voice | Description |
|-------|-------------|
| `am_michael` | American male (default) |
| `af_heart` | American female |
| `bf_emma` | British female |

Pass any kokoro voice name with `-v` or set in config. See [kokoro-onnx voices](https://github.com/thewh1teagle/kokoro-onnx#voices) for the full list.

---

## MCP Server Setup

The study-speak MCP server lets AI agents call the TTS tool directly. The standalone server lives at `agents/mcp/study-speak-server.py`.

### Kiro CLI

Configured automatically via `agents/kiro/study-mentor.json`. No manual setup needed — the install script handles it.

### Claude Code / Gemini / OpenCode / Amp

Each agent has an `mcp.json` in its `agents/` directory. The server command uses `uvx` to run the standalone MCP server:

```json
{
  "mcpServers": {
    "speaker": {
      "command": "uvx",
      "args": ["--from", "mcp[cli]", "mcp", "run", "/absolute/path/to/agents/mcp/study-speak-server.py"]
    }
  }
}
```

Replace the path with your actual clone location. The `scripts/install-agents.sh` script sets this up automatically for detected AI tools.

---

## CLI Reference

```bash
study-speak "text"                                        # Speak text
study-speak -                                              # Read from stdin
study-speak "text" -v af_heart                            # Different voice
study-speak "text" -s 1.2                                 # Faster speed
study-speak "text" -b macos                               # Force macOS fallback
study-speak "text" -b qwen3 --instruct "speak warmly"    # Qwen3 with emotion
```

---

## Backends

| Backend | Model Size | Latency | Notes |
|---------|-----------|---------|-------|
| `kokoro` (default) | 82M params | ~1.5s | ONNX runtime on CPU. Best balance of quality and speed. |
| `qwen3` (via ltts) | 1.7B params | 30–60s | Highest quality. Emotional control via `--instruct`. Apple Silicon MPS. Only use when quality matters more than speed. |
| `macos` (say) | Built-in | Instant | Low quality. Last resort fallback. |

!!! tip "When to use qwen3"
    The 30–60s latency on Apple Silicon makes qwen3 impractical for live sessions. Use it for generating audio files or when you want emotional expression and don't mind waiting.

---

## Troubleshooting

**Crackling audio**
:   Automatic 24kHz→48kHz resampling should fix this. If it persists, check your audio output device settings.

**No sound**
:   Check for errors: `study-speak "test" 2>&1`. Verify models exist in `~/.cache/kokoro-onnx/`.

**AirPlay latency**
:   Short clips (<2s) may not play through AirPlay due to buffer timing. Use longer text or switch to local speakers.

---

## Why Voice Matters for AuDHD Learners

!!! energy-check "Dual coding = better retention"
    Hearing information while reading it activates two processing channels simultaneously. For AuDHD brains, this redundancy helps compensate for attention drift.

- **Auditory reinforcement** — dual coding (visual + auditory) improves retention
- **Processing support** — hearing questions spoken aloud helps with comprehension and focus
- **Reduces overwhelm** — breaks up the "wall of text" experience
- **Maintains engagement** — natural voice (not robotic) avoids sensory irritation
