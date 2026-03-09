# Brainstorm: v1.4 Features

**Date:** 2026-03-09
**Status:** Brainstorm (pre-plan)

---

## Feature Summary

Four interconnected features that deepen the mentor's pedagogical intelligence:

1. **Teach the Teacher** — Student explains concepts back; scored and tracked with spaced repetition
2. **Active Break Protocol** — Science-backed movement, hydration, and micro-break reminders during sessions
3. **Session Wind-Down** — End-of-session rest protocol with evidence-based timing for memory consolidation
4. **Dynamic Knowledge Bridging** — Rename to `/socratic-mentor`, add configurable knowledge domains beyond networking

---

## 1. Teach the Teacher

### The Problem

The mentor currently has four scaffolding levels (L1 Prompted → L4 Teaching), and at the 30-day spaced repetition interval it triggers a "teach-back session." But there's no formal scoring, no structured protocol for assessing the quality of the teach-back, and no mechanism to distinguish genuine understanding from memorisation. The teach-back is also only triggered at the 30-day mark — research says it should happen earlier and more frequently.

### What the Research Says

**The Protege Effect** (Chase et al., 2009): People learn more effortfully when they believe they are teaching someone else. Three mechanisms drive this:
- **Generative processing**: Explaining forces select → organise → integrate (beyond surface)
- **Metacognitive monitoring**: "Do I actually understand this well enough to explain it?"
- **Motivation shift**: Social obligation creates effort the learner wouldn't apply for themselves

**Kobayashi (2019) meta-analysis**: Preparing to teach promotes deep learning because teacher-role students use 1.3x more metacognitive strategies than those studying for themselves.

**Key insight**: The effect works even when teaching is *simulated*. Simply believing you're explaining to a teachable agent triggers deeper processing (Stanford, Chase et al., 2009). Our AI mentor is a perfect "teachable agent."

### Proposed Design

#### Teach-Back Scoring Rubric (5 dimensions, 4 levels)

| Dimension | 1 - Recitation | 2 - Paraphrase | 3 - Explanation | 4 - Teaching |
|---|---|---|---|---|
| **Accuracy** | Significant errors/omissions | Mostly correct, minor gaps | Accurate with nuance | Accurate + anticipates edge cases |
| **Own Words** | Verbatim repetition | Mixed own/parroted | Consistently own language | Creates novel analogies/framings |
| **Structure** | Disconnected facts | Some structure, unclear relationships | Clear logical flow (cause/effect) | Builds narrative for listener |
| **Depth** | States WHAT only | WHAT + partial HOW | WHAT, HOW, and WHY | WHY + tradeoffs + when NOT to use |
| **Transfer** | Cannot apply to new context | Applies with heavy hints | Independently applies to related scenario | Generates novel examples/counter-examples |

**Score ranges:**
- 5-8: Memorised, not understood → reset interval to 1 day
- 9-13: Partial understanding → same interval, probe the gaps
- 14-17: Solid understanding → extend interval
- 18-20: Mastery → maximum interval extension (90-day check-in)

#### Teach-Back Integration with Spaced Repetition

| Interval | Current Review Type | Proposed Teach-Back Addition |
|---|---|---|
| 1 day | 5-min recall quiz | No teach-back (too early) |
| 3 days | 10-min Socratic review | **Micro teach-back**: "In one sentence, explain [concept]." Score Accuracy + Own Words only. |
| 7 days | 15-min deep review | **Structured teach-back**: Full 5-dimension rubric. Vary question angle from last review. |
| 14 days | Apply to new problem | **Transfer teach-back**: "Explain how [concept] applies to [novel scenario]." Score Transfer + Depth. |
| 30 days | Teach-back session | **Full teaching episode**: Explain as if teaching someone new. All 5 dimensions. Score >= 14 → "mastered" with 90-day check-in. |

#### Detecting Understanding vs Memorisation

**Red flags (surface learning):**
- Uses exact same words as source material
- Cannot answer "what if?" variations
- Explanation breaks down with unseen examples
- Cannot explain WHY, only WHAT
- Confidence collapses when question angle changes

**Detection probes the agent should use:**
1. **"Explain it differently"**: "Now explain it as if I'm a network engineer / a 10-year-old / your manager"
2. **"Break it"**: "What happens if we remove [key component]?" / "When would this fail?"
3. **"Analogy generation"**: "Give me an analogy from [student's expert domain]"
4. **"Near transfer"**: Present a slightly different problem using the same principle

#### Avoiding Repetitiveness

The agent MUST vary the angle on each review. Track which angles have been used per concept:

- **Bloom's rotation**: Cycle through Remember → Understand → Apply → Analyse → Evaluate → Create
- **Context rotation**: Same concept, different scenario each review
- **Modality rotation**: Verbal → code exercise → diagram → debug broken code → teach-back → compare/contrast
- **Direction reversal**: "What is X?" → "When would you NOT use X?" → "What problem does X solve?"

#### Database Changes

New table: `teach_back_scores`

```sql
CREATE TABLE teach_back_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept TEXT NOT NULL,
    topic TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(id),
    score_accuracy INTEGER CHECK(score_accuracy BETWEEN 1 AND 4),
    score_own_words INTEGER CHECK(score_own_words BETWEEN 1 AND 4),
    score_structure INTEGER CHECK(score_structure BETWEEN 1 AND 4),
    score_depth INTEGER CHECK(score_depth BETWEEN 1 AND 4),
    score_transfer INTEGER CHECK(score_transfer BETWEEN 1 AND 4),
    total_score INTEGER GENERATED ALWAYS AS (
        score_accuracy + score_own_words + score_structure + score_depth + score_transfer
    ) STORED,
    review_type TEXT NOT NULL,  -- micro|structured|transfer|full
    question_angle TEXT,        -- bloom_level + modality used
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_teachback_concept ON teach_back_scores(concept, topic);
CREATE INDEX idx_teachback_date ON teach_back_scores(created_at);
```

Extend `study_progress` table:
```sql
ALTER TABLE study_progress ADD COLUMN last_teachback_score INTEGER;
ALTER TABLE study_progress ADD COLUMN angles_used TEXT;  -- JSON array of angles already tried
ALTER TABLE study_progress ADD COLUMN mastery_signals TEXT;  -- JSON: {accuracy_pct, transfer_success, independence_level}
```

#### CLI Addition

```bash
studyctl teachback CONCEPT -t TOPIC --score "3,3,4,3,2" --type structured --angle "apply_network_analogy"
studyctl teachback-history CONCEPT  # show score progression over time
```

### Open Questions

- Should the agent self-assess the teach-back score, or should it propose a score and ask the student to confirm/adjust? (Self-assessment is a metacognitive skill worth developing)
- Do we need FSRS (Free Spaced Repetition Scheduler) instead of fixed intervals? The `fsrs` Python package exists and adapts per-concept. Worth the complexity?
- Should teach-back scores feed into the existing `study_progress.confidence` levels, or remain a separate signal?

---

## 2. Active Break Protocol

### The Problem

The session protocol already has break reminders at 25/50/90 minutes, but they're passive text nudges. There's no science-backed reasoning communicated to the student, no differentiation between break types, and no ADHD-specific adaptations for when timers help vs when they break flow.

### What the Research Says

#### Movement Breaks

- **Sharpe et al. (2025, Frontiers in Psychology)**: Human sustained attention is limited to ~25 minutes before significant decline. "Perfect sustained attention is fundamentally impossible."
- **Ariga & Lleras (2011, Cognition)**: The vigilance decrement is NOT from "running out" of attention — it's from *habituation to the task goal*. Brief diversions **reactivate** the goal and completely prevent performance decline.
- **PMC (2024)**: 10-minute physical activity breaks significantly enhance selective attention and executive function vs no-break conditions.
- **Active > passive**: Evidence does NOT support passive breaks being as effective. Movement triggers increased cerebral blood flow, dopamine/norepinephrine/BDNF release, and cardiovascular oxygen delivery.

#### Hydration

- **Popkin et al. (2010)**: Even 1-2% body mass dehydration impairs concentration, reaction time, short-term memory, and mood.
- **Edmonds & Jeffes (2009)**: Simply drinking water improved visual attention even in mild (non-exercise) dehydration. Routine mild dehydration from not drinking during study is sufficient to impair cognition.
- **Chinese RCT (2021)**: 500mL water supplementation improved processing speed and working memory.
- **Practical threshold**: ~200-500mL per hour during cognitive work.

#### Walking and Thinking

- **Oppezzo & Schwartz (2014, Stanford)**: Creative output increased 60% while walking vs sitting. Walking on a treadmill facing a blank wall produced nearly the same benefit — the act of walking itself is the driver. Effect **persisted after walking** (elevated creativity in subsequent seated session). Walking improved *divergent thinking* (novel ideas) but not *convergent thinking* (single correct answer).
- **Huberman (Stanford)**: Walking creates optic flow that quiets stress responses — enhanced outdoors.
- **Nature walking**: Reduces cortisol, which impairs memory consolidation when elevated.

#### ADHD-Specific Break Patterns

- **Faster depletion**: ADHD brains deplete executive function faster ("smaller gas tank, burns fuel faster").
- **Shorter, more frequent breaks** (Hunter & Wu, 2016): Maximise resource recovery.
- **5-minute movement breaks every 20 minutes** improved attention/memory in university students — notably shorter than standard Pomodoro.
- **Hyperfocus trap**: ADHD brain can lock into tasks and ignore physical needs for hours. Non-negotiable hydration/movement alarms needed.
- **The transition problem**: For ADHD, restarting after a break is harder than the work itself. Break activities must be low-dopamine (walking, water, stretching — NOT phone, social media, rabbit holes).

### Proposed Design

#### Tiered Break System

```
MICRO-BREAK (every 20-25 min):
  Duration: 2-3 minutes
  Activities: Stand up, stretch, drink water (200mL)
  Agent behaviour: Gentle nudge, don't break mid-thought
  Implementation: 2-minute wrap-up buffer before break

SHORT BREAK (every 50-60 min / every 2-3 micro-breaks):
  Duration: 5-10 minutes
  Activities: Walk to another room, refill water, light movement
  Agent behaviour: Summarise progress, set re-entry point
  Implementation: Agent notes current concept for seamless resume

LONG BREAK (every 90-120 min):
  Duration: 15-20 minutes
  Activities: Walk outside if possible, change environment
  Agent behaviour: Full progress checkpoint, suggest what to tackle next
  Implementation: Auto-record session state for resume
```

#### ADHD Adaptations

| Energy Level | Micro-Break | Short Break | Long Break |
|---|---|---|---|
| High (7-10) | Every 25 min | Every 50 min | Every 90 min |
| Medium (4-6) | Every 20 min | Every 40 min | Every 75 min |
| Low (1-3) | Every 15 min | Every 30 min | Every 60 min |

**Hyperfocus override**: If student is in productive flow (responding quickly, making progress), use a "wrap-up buffer" instead of hard stops. "You've been going for 30 minutes — finish your current thought, then let's take a quick stretch." Don't destroy flow states.

**The "just water" minimum**: Even if the student resists a full break, the agent should insist on water. "I hear you — you're in the zone. At minimum, take a drink of water right now. We'll keep going."

#### Agent Prompt Additions

The agent should communicate the WHY, not just the instruction:

> "Quick science check: your brain habituates to tasks after about 25 minutes — attention doesn't deplete, it *tunes out*. Standing up for 2 minutes literally reactivates your focus. Let's take a micro-break — stand up, drink some water, and we'll pick up right where we left off."

> "You've been at this for 50 minutes. Stanford research shows walking increases creative thinking by 60% — and the effect persists after you sit back down. Walk to the kitchen, refill your water, and when you come back you'll see this problem differently."

#### State Tracking

```python
# In session state (written to state file for status line)
break_state = {
    "session_start": "2026-03-09T14:00:00",
    "last_micro_break": "2026-03-09T14:25:00",
    "last_short_break": None,
    "last_long_break": None,
    "water_reminders_sent": 2,
    "breaks_taken": 1,
    "breaks_skipped": 0,
    "energy_level": 7,
    "current_interval": "micro",  # next break type due
    "next_break_due": "2026-03-09T14:50:00",
}
```

### Open Questions

- Should the agent track actual break compliance (did the student actually take the break) or is that too surveillant?
- Integration with the existing status line — should break countdown show in the status line?
- For voice mode (`study-speak`), should break reminders be spoken aloud?

---

## 3. Session Wind-Down Protocol

### The Problem

The current end-of-session protocol records progress and suggests next review dates, but doesn't address what happens *immediately after* the session. The science on post-learning rest is compelling and largely unknown to most learners.

### What the Research Says

#### The NIH Wakeful Rest Discovery (Buch et al., 2021, Cell Reports)

This is the most important finding for post-session design:

- During wakeful rest, the brain **replays newly learned material at 20x speed**
- This replay occurs in the hippocampus and sensorimotor cortex
- The more replay during rest, the **greater the performance improvement** in subsequent practice
- **Wakeful consolidation is ~4x greater in magnitude** than overnight sleep consolidation
- You do NOT need to actively rehearse — consolidation happens automatically during quiet rest

#### Rest Type Matters

| Post-Session Activity | Effect on Memory |
|---|---|
| Quiet rest (eyes closed, low stimulation) | **Best** for declarative memory consolidation |
| Walking (low cognitive load) | **Good** — consolidation + movement benefits |
| Immediately starting new unrelated topic | **Interferes** with consolidation |
| Checking phone / social media | **Interferes** with consolidation |
| Sleep | Excellent for long-term systems-level consolidation |

**Dewar et al. (2012, Psychological Science)**: Brief wakeful rest boosts new memories over the **long term**, not just short-term. The effect does NOT depend on intentional rehearsal.

**Wamsley (2019)**: Even seconds-long rest breaks trigger memory-related brain activity that predicts later test performance. Rest during wakefulness is "a crucial and widely underappreciated contributor to long-term memory formation."

#### Optimal Post-Session Timing

Based on research synthesis:

- **Immediate post-session**: 10-15 minutes quiet/low-stimulation activity
- **Do NOT** immediately load new cognitive material
- **Walking is ideal**: Combines consolidation with movement benefits
- **Between major sessions**: 20-30 minute break minimum
- **After 3-4 hours total study**: Consider ending for the day or taking 1+ hour break

### Proposed Design

#### Wind-Down Protocol (Agent-Driven)

When the session approaches end (student signals, or 90+ min elapsed):

```
PHASE 1: Session Wrap (2-3 min, in-session)
  - Record progress: studyctl progress "concept" -t topic -c level
  - Surface parking lot items
  - Summarise what was covered + key insights
  - Set next review dates via spaced repetition

PHASE 2: Consolidation Guidance (spoken if voice mode active)
  Agent says something like:
  "Here's something most people don't know: your brain is about to replay
  everything we just covered at 20x speed — but only if you give it quiet
  space. For the next 10-15 minutes, avoid jumping into email or your phone.

  Best option: walk outside if you can. The movement helps and the change
  of scenery lets your brain consolidate.

  Second best: get up, make a tea or coffee, sit somewhere different from
  your desk for 10 minutes.

  What you want to avoid: immediately opening Slack, Twitter, or starting
  another intense task. That interferes with the replay process."

PHASE 3: Next Session Suggestion
  Based on spaced repetition schedule + time of day:
  - Morning session ending: "Your next session could be this afternoon
    after a 2-3 hour break, or tomorrow morning."
  - Afternoon session ending: "Let your brain consolidate overnight.
    Tomorrow is ideal for the next session."
  - If concepts are due for review tomorrow: mention them specifically
```

#### Rest Duration Recommendations

| Scenario | Minimum Rest | Ideal Rest | Activity |
|---|---|---|---|
| Between focus blocks (same session) | 5 min | 10 min | Stand, walk, water |
| End of study session | 10 min | 15-20 min | Walk outside, change environment |
| Between sessions (same day) | 30 min | 1-2 hours | Different activity entirely |
| After intensive session (2+ hours) | 1 hour | 2-3 hours | Exercise, meal, non-screen activity |

#### CLI Addition

```bash
studyctl wind-down  # Show post-session guidance based on session duration and time of day
```

### Open Questions

- Should `studyctl wind-down` be automatic at session end, or opt-in?
- Should it integrate with calendar to block "consolidation time" after study blocks?
- How do we handle the student who says "I'm fine, I want to keep going"? Respect autonomy while communicating the science.

---

## 4. Dynamic Knowledge Bridging (/socratic-mentor configure)

### The Problem

The current system hardcodes networking as the student's expert domain. Every analogy bridges from network concepts (ECMP, BGP, VLAN, etc.) to data engineering concepts. This works perfectly for you — but makes the tool useless for anyone whose background isn't networking. Even for you, there may be *other* domains you're comfortable with that could provide better bridges for specific concepts.

### What the Research Says

#### Analogical Reasoning (Gentner's Structure-Mapping Theory, 1983)

- **Surface vs structural similarity**: Novices match on surface features ("both involve water"). Experts match on relational structure ("both involve flow through constrained paths"). Good bridges must map *structure*, not surface.
- **Bridging analogies** (Clement, 1993): When target concept is too distant from known domain, create a chain of intermediate analogies. Multi-hop bridges.
- **Analogical encoding** (Gentner et al., 2004): Comparing two cases side-by-side leads to better transfer than studying each alone.

#### Knowledge Activation

- **Richland et al. (2019)**: Warm-up activities that activate prior knowledge before new material significantly improve transfer. The warm-up closes the gap between old and new learning.
- **Blanchette & Dunbar (2000)**: People produce more and better analogies when given the goal of creating a persuasive argument than a memory task.

### Proposed Design

#### Command Restructure

```
CURRENT:
  /audhd-socratic-mentor  (hardcoded to networking bridges)

PROPOSED:
  /socratic-mentor                     # Default: uses configured knowledge domain
  /socratic-mentor --domain networking  # Explicit domain override
  /socratic-mentor configure           # Interactive setup wizard
```

The `audhd-socratic-mentor` skill becomes the *engine* (questioning methodology, scaffolding, cognitive support) while the *knowledge bridges* become a configurable layer on top.

#### /socratic-mentor configure — Interactive Setup

The agent runs an interactive discovery session:

```
STEP 1: Background Discovery
  "What's your professional background? What have you spent the most
  years working with?"
  → Captures: primary expertise domain(s)

STEP 2: Comfort Mapping
  "Within [domain], what are the concepts you could explain in your
  sleep? The ones that are second nature?"
  → Captures: anchor concepts (Clement's "anchors")

  "What about outside your main field — any hobbies, interests, or
  other skills where you have deep intuitive understanding?"
  → Captures: secondary domains for cross-pollination

STEP 3: Bridge Generation
  Agent identifies structural mappings between student's known concepts
  and the target learning domain. Proposes initial bridge table.

  "Based on what you've told me, here are some concept bridges I think
  will work. Let me know if any feel wrong or forced:"

  | Your Experience | Maps To | Why |
  |---|---|---|
  | [known concept] | [target concept] | [structural similarity] |

  Student validates/rejects/modifies bridges.

STEP 4: Persist Configuration
  Writes to ~/.config/studyctl/config.yaml:

  knowledge_domains:
    primary: networking
    anchors:
      - concept: "ECMP load balancing"
        comfort: 10
      - concept: "BGP route propagation"
        comfort: 9
      - concept: "VLAN segmentation"
        comfort: 10
    secondary:
      - domain: "cooking"
        anchors: ["mise en place", "flavour balancing"]
    bridges:
      - source: "ECMP load balancing"
        target: "Spark partition distribution"
        quality: "validated"  # validated|proposed|rejected
      - source: "mise en place"
        target: "data pipeline staging"
        quality: "proposed"
```

#### Dynamic Bridge Evolution

Beyond the initial configure step:

1. **Student-generated analogies**: When the student produces a good analogy during a session, capture it:
   ```bash
   studyctl bridge add "TCP three-way handshake" "OAuth token exchange" --quality validated
   ```

2. **Bridge effectiveness tracking**: Did the analogy help or confuse?
   - If student grasped concept faster after bridge: mark as effective
   - If student got confused by the analogy: mark as misleading, try different angle

3. **Analogy fading**: Track scaffolding level per concept. At L1-L2, provide explicit bridges. At L3, ask "What does this remind you of?" At L4, expect student to generate bridges unprompted.

4. **Warm-up activation**: Before new material, spend 2 minutes activating relevant prior knowledge from the configured domain. "Before we dive into Spark DAGs, let's think about network topology and dependency graphs for a moment..."

#### Database Changes

New table: `knowledge_bridges`

```sql
CREATE TABLE knowledge_bridges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_concept TEXT NOT NULL,
    source_domain TEXT NOT NULL,
    target_concept TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    structural_mapping TEXT,        -- WHY they map (the relational structure)
    quality TEXT DEFAULT 'proposed', -- proposed|validated|effective|misleading|rejected
    times_used INTEGER DEFAULT 0,
    times_helpful INTEGER DEFAULT 0,
    created_by TEXT DEFAULT 'agent', -- agent|student|configure
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_bridge_target ON knowledge_bridges(target_concept, target_domain);
CREATE INDEX idx_bridge_source ON knowledge_bridges(source_domain);
```

#### Backward Compatibility

The existing `network-bridges.md` file becomes one *instance* of bridges — the networking domain. The shared agent files reference a configurable bridge source rather than hardcoding networking. For users who don't run `configure`, the default remains networking bridges (preserving current behaviour for you).

### Open Questions

- How many domains should we support simultaneously? Just primary, or allow multiple with priority ordering?
- Should the agent be able to *generate* bridge tables for new domains on the fly using its own knowledge, or should they always go through the configure validation step?
- For the rename: do we keep `/audhd-socratic-mentor` as an alias during a transition period, or clean break?
- Should `configure` re-run periodically as the student's comfort with target concepts grows? (Some bridges become unnecessary as the student develops direct understanding.)

---

## Cross-Cutting Concerns

### Feature Interactions

```
                    configure
                       |
                       v
              knowledge_domains
                    /     \
                   v       v
         teach-back -----> bridges (use domain-specific probes)
              |
              v
       spaced repetition (teach-back scores adjust intervals)
              |
              v
         break protocol (breaks timed around teach-back blocks)
              |
              v
        wind-down (consolidation advice references what was taught back)
```

- **Teach-back + bridges**: When asking "explain it using an analogy," pull from configured domain
- **Teach-back + breaks**: After a teach-back assessment, a short break aids consolidation of the self-assessment
- **Breaks + energy**: Break frequency already adapts to energy level
- **Wind-down + spaced repetition**: Post-session advice includes next review dates and what type of review (recall vs teach-back)

### Migration Strategy

1. **Database migration v10**: Add `teach_back_scores` + `knowledge_bridges` tables, extend `study_progress`
2. **Agent prompt updates**: All 7 agent configurations need the new protocols
3. **Shared framework**: New `teach-back-protocol.md` and `break-science.md` in `agents/shared/`
4. **CLI commands**: `studyctl teachback`, `studyctl bridge`, `studyctl wind-down`
5. **Config changes**: `~/.config/studyctl/config.yaml` gets `knowledge_domains` section

### Implementation Priority (Recommended)

| Priority | Feature | Why First |
|---|---|---|
| 1 | Active Break Protocol | Smallest scope, immediate health benefit, no schema changes needed (state file only) |
| 2 | Session Wind-Down | Builds on break protocol, small scope, high-value science communication |
| 3 | Teach the Teacher | Largest feature, needs schema migration, most complex agent prompt changes |
| 4 | Dynamic Knowledge Bridging | Depends on teach-back (bridges feed into teach-back probes), most architectural change |

### Estimated Scope

- **Break protocol**: Agent prompt changes + state tracking. ~Medium complexity.
- **Wind-down**: Agent prompt changes + 1 CLI command. ~Small complexity.
- **Teach the Teacher**: Schema migration + CLI commands + agent prompt changes + scoring logic. ~Large complexity.
- **Knowledge bridging**: Schema migration + CLI commands + interactive configure flow + agent prompt refactor + backward compat. ~Large complexity.

---

## Challenges Worth Debating

1. **Agent self-scoring teach-backs**: Can the AI reliably score a teach-back on 5 dimensions? It sees the text, not the understanding. Risk of students gaming the rubric. Counter-argument: even imperfect scoring creates metacognitive benefit.

2. **Break compliance vs autonomy**: How pushy should the agent be? ADHD brains often resist externally imposed breaks (PDA — pathological demand avoidance). The agent needs to be informative without being nagging.

3. **Fixed vs adaptive intervals**: The current 1/3/7/14/30 schedule is simple and predictable. FSRS would be more optimal but adds complexity and a dependency. Is the juice worth the squeeze for a study tool?

4. **Bridge generation at scale**: If someone configures "cooking" as their domain, can the agent generate useful structural bridges to data engineering on the fly? Or do we need curated bridge tables per domain?

5. **Multi-agent consistency**: All 7 agent configurations (Kiro, Claude, Gemini, OpenCode, Amp, Crush, RepoPrompt) need to implement these features consistently. The shared framework approach helps, but each agent has different capabilities.
