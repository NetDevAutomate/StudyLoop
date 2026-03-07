---
name: study-speak
description: Speak Socratic questions aloud using text-to-speech (kokoro-onnx, am_michael voice)
---

## Voice Output Tool

**Command**: `~/.local/bin/study-speak "<text>"`

Speaks text aloud through the learner's speakers using kokoro-onnx TTS (am_michael voice, ~1.5s latency).

---

## Toggle Commands

The learner controls voice with these commands in chat:

- `@speak-start` — enable voice output
- `@speak-stop` — disable voice output

Voice is **off by default**. Do not speak unless the learner has said `@speak-start`.

---

## When Voice is Enabled

**MUST execute** this shell command every time you ask a Socratic question:

```bash
~/.local/bin/study-speak "Your question here"
```

### What to speak
- The core Socratic question only (1-2 sentences)

### What NOT to speak
- Scaffolding, analogies, code examples, explanations — those stay as text

---

## Example Flow

```
Learner: @speak-start

Agent (text): Here's an analogy. Think of a Python generator like a
bookmark in a book — it remembers where you left off.

Agent (text): Now here's the question:

Agent (executes): ~/.local/bin/study-speak "What happens the first time you call next on a generator? Does the function run from the beginning or from somewhere else?"

Learner: @speak-stop

Agent: (continues text-only)
```

---

## If the Command Fails

Continue the session without voice. Never let TTS errors block teaching.
