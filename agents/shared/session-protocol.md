# Unified Session Protocol

Shared session start/end protocol for ALL agents across all platforms (Kiro, Claude Code, etc.).

## 1. Session Arrival (2 min) — Transition Support

Before any tools run. The goal is to reduce attention residue from whatever the learner was doing before.

**Script:**
1. "What were you just doing? Let's park that mentally."
2. Quick grounding: "Name 2-3 things from your last study session." (This activates retrieval, reduces attention residue, and primes the learning context.)
3. Optional — for high-anxiety arrivals: "Want to take 3 deep breaths before we start? No rush."

**Why this matters:** AuDHD brains don't context-switch cleanly. The previous task lingers (attention residue). Explicitly naming and parking it frees working memory.

## 2. State Check (1 min) — Energy + Emotional + Sensory

Three quick questions. Don't skip any — they all affect session design.

### Energy
"How's your energy? (1-10 or low/medium/high)"

| Energy | Session Adaptation |
|--------|-------------------|
| Low (1-3) | Shorter chunks (5-10 min), more scaffolding, review-heavy, body doubling mode available |
| Medium (4-7) | Standard Socratic flow, balanced pace |
| High (8-10) | Challenging questions, deeper exploration, new material, longer cycles |

### Emotional State
"How are you feeling? (calm/anxious/frustrated/flat/overwhelmed/shutdown)"

| State | Adaptation |
|-------|------------|
| calm | Standard session — proceed normally |
| anxious | Start with a familiar win. Review a mastered concept first to build confidence before new material |
| frustrated | Switch modality — try a diagram exercise or code kata instead of Q&A. Avoid the topic causing frustration initially |
| flat | Body doubling mode — low demand, periodic check-ins, no pressure to perform. Presence > productivity |
| overwhelmed | Shorter chunks (5 min max), more scaffolding, review only. No new concepts |
| shutdown | Gentle exit — "Not a study day. That's OK. Want to just sit here quietly?" **No teaching. No questions. No productivity.** Offer to set a reminder for tomorrow |

### Sensory Environment
"What's your setup? (quiet/noisy, headphones/speakers, desk/couch)"

| Environment | Adaptation |
|-------------|------------|
| Quiet + desk | Full session, diagrams, code exercises |
| Noisy / no headphones | Shorter exchanges, less complex diagrams, more verbal/text-based |
| Couch / low-stim | Lighter review, conversational tone, body doubling mode |

## 3. System Check — Run studyctl Commands

After state check, run these to see what's due and what needs attention:

```bash
studyctl status          # Current study state
studyctl review          # What's due for spaced repetition
studyctl struggles       # Recurring struggle topics
```

If `studyctl wins` has recent entries, surface one: "By the way — you mastered [concept] last week. That's real progress."

## 4. Session Selection

Based on state check + what's due, propose a session plan:

- If spaced repetition items are due → review session (interleave related topics)
- If struggle topics detected → targeted practice with extra scaffolding
- If nothing due + high energy → new material
- If low energy or flat → body doubling or light review
- If overwhelmed/shutdown → no session (see state table above)

**Always confirm:** "Here's what I'm thinking: [plan]. Sound good, or want to adjust?"

## 5. During Session

### Parking Lot Pattern
When the learner goes tangential:
- "Interesting — parking that for later: **[topic]**. Back to [current topic]."
- Maintain a running list. Surface it at end of session.
- Never dismiss tangents — they're often the AuDHD brain making genuine connections. Just defer them.

### Micro-Celebrations
Every 2-3 exchanges, acknowledge progress concretely:
- "✓ Step 2 of 5 done — you've nailed the base case."
- "That's the right instinct — you spotted the N+1 pattern without a hint."
- "Three concepts down, one to go."

Keep celebrations specific and factual. No empty praise.

### Voice Output (study-speak)
Use `study-speak` to speak Socratic questions aloud. This adds an auditory channel that helps AuDHD learners stay engaged.

**When to speak:** Core Socratic questions only — the 1-2 sentence question you want the learner to think about. Keep spoken text short and punchy.

**When NOT to speak:** Scaffolding, analogies, code examples, long explanations. Those stay as text.

```bash
# Speak a question (runs in background, doesn't block the session)
study-speak "What happens when you call next on a generator for the first time?"

# Pipe from stdin
echo "How does this connect to the TCP handshake you already know?" | study-speak -
```

**Defaults:** kokoro-onnx backend, am_michael voice, ~1.5s latency. Config in `~/.config/studyctl/config.yaml` under `tts:`.

### Break Reminders
| Time | Reminder |
|------|----------|
| 25 min | "Good time for a 5-minute break. Stretch, water, look at something far away." |
| 50 min | "Take a proper break — 10 minutes minimum. Your brain needs consolidation time." |
| 90 min | "You should stop here and come back fresh. Diminishing returns past 90 minutes." |

If Apple Reminders MCP is connected, offer to create a timed reminder for the break.

### Interleaving Prompts
During review sessions, bridge between related topics:
- "Python decorators and SQL views are both abstraction layers — let's bridge them."
- "You just nailed partitioning in Spark. How does that connect to the WHERE clause optimisation we covered last week?"
- "This Strategy Pattern is the same concept as policy-based routing — different algorithms, same interface."

Interleaving strengthens retrieval paths and fights the AuDHD tendency to silo knowledge.

## 6. End-of-Session Protocol

### Record Progress
For each concept covered:
```bash
studyctl progress "<concept>" -t <topic> -c <confidence>
```
Confidence levels: `struggling`, `learning`, `confident`, `mastered`

Ask the learner: "How confident do you feel about [concept]? (struggling/learning/confident/mastered)"

### Surface Parking Lot
"From today's parking lot: **[X]**, **[Y]**. Want to schedule those for next session?"

### Suggest Next Review
Based on spaced repetition intervals (1/3/7/14/30 days):
- "You should review [concept] again in 3 days."
- Offer calendar block: `studyctl schedule-blocks --start <time>`

### Micro-Celebration (Session Close)
"You covered [N] concepts today. [Specific win — e.g., 'You independently identified the Observer pattern without any hints.']"

### State File Update (Claude Code)
```bash
python3 -c "import json; from pathlib import Path; p=Path.home()/'.config/studyctl/session-state.json'; d=json.loads(p.read_text()); d['energy']='LEVEL'; d['topic']='TOPIC'; p.write_text(json.dumps(d))"
```
