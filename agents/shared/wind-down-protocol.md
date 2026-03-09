# Session Wind-Down Protocol

Evidence-based post-session protocol for memory consolidation. What happens in the 15 minutes after a study session matters more than most people realise.

## The Science

### Wakeful Rest Replay (Buch et al., 2021, *Cell Reports*)

During quiet rest after learning, the brain **replays newly learned material at 20x speed** in the hippocampus and sensorimotor cortex. This isn't optional or vague — it's measured neural activity that directly predicts skill improvement.

Key findings from the NIH study:
- Wakeful consolidation is **~4x greater in magnitude** than overnight sleep consolidation
- The more replay during rest, the greater the performance improvement
- You do NOT need to actively rehearse — consolidation happens automatically
- The replay occurs in the seconds-to-minutes after learning stops

### What Disrupts Consolidation

Dewar et al. (2012, *Psychological Science*) and Wamsley (2019, *Trends in Neurosciences*) found:

| Post-Session Activity | Effect on Memory |
|---|---|
| Quiet rest (eyes closed, low stimulation) | Best — maximises hippocampal replay |
| Walking (low cognitive load) | Good — consolidation continues + movement benefits |
| Light non-cognitive activity (making tea) | Good — low interference |
| Immediately starting new cognitive material | **Interferes** with consolidation of prior session |
| Checking phone / social media / email | **Interferes** — high cognitive load disrupts replay |
| Sleep | Excellent for long-term systems-level consolidation (hours-to-weeks) |

The critical insight: the brain needs a **cognitive gap** between learning and the next demanding task. Filling that gap with any high-cognitive-load activity (even unrelated learning) degrades the consolidation of what was just studied.

## Wind-Down Protocol

### Phase 1: Session Wrap (2-3 min, in-session)

Standard end-of-session tasks from session-protocol.md:

1. Record progress for each concept covered:
   ```bash
   studyctl progress "<concept>" -t <topic> -c <confidence>
   ```

2. Surface parking lot items:
   *"From today's parking lot: **[X]**, **[Y]**. Want to schedule those for next session?"*

3. Summarise what was covered and key insights:
   *"Today you covered [concepts]. The key insight was [specific teaching moment]."*

4. Set next review dates via spaced repetition schedule.

### Phase 2: Consolidation Guidance (spoken if voice mode is active)

After the session wrap, the agent delivers consolidation guidance. This is the novel part — most study tools skip this entirely.

**First time (explain the science):**

> *"Here's something most people don't know: your brain is about to replay everything we just covered at 20x speed — but only if you give it quiet space. NIH research found this wakeful consolidation is four times more powerful than overnight sleep for skill learning.*
>
> *For the next 10-15 minutes, avoid jumping into email, Slack, or your phone. The best thing you can do is walk — outside if you can. The movement helps and the change of scenery lets your brain consolidate.*
>
> *Second best: get up, make a tea or coffee, sit somewhere different from your desk for 10 minutes.*
>
> *What you want to avoid: immediately starting another intense cognitive task. That literally interferes with the replay process."*

**Subsequent sessions (brief reminder):**

> *"Consolidation time. 10-15 minutes away from the screen — walk if you can, or just step away from your desk. Let your brain replay what we covered."*

### Phase 3: Next Session Suggestion

Based on time of day and spaced repetition schedule:

**Morning session ending (before noon):**
> *"Your next session could be this afternoon after a 2-3 hour break. [Concept X] is due for a 3-day Socratic review — good candidate for the afternoon slot."*

**Afternoon session ending (noon-5pm):**
> *"Good time to let your brain work on this overnight. Tomorrow morning is ideal for the next session — you'll be surprised how much clearer [concept] feels after sleep consolidation."*

**Evening session ending (after 5pm):**
> *"Sleep will consolidate today's learning. [Concept X] is due for review in [N] days — I'll flag it when the time comes."*

**If concepts are due for review soon:**
> *"[Concept X] is due for a [review type] in [N] days. Want me to suggest a calendar block?"*

## Rest Duration Guidelines

| Scenario | Minimum Rest | Ideal Rest | Recommended Activity |
|---|---|---|---|
| Between focus blocks (same session) | 5 min | 10 min | Stand, walk, water |
| End of study session (< 60 min) | 10 min | 15 min | Walk, change environment |
| End of study session (60-120 min) | 15 min | 20 min | Walk outside, hot drink |
| Between sessions (same day) | 30 min | 1-2 hours | Different activity entirely |
| After intensive session (2+ hours) | 1 hour | 2-3 hours | Exercise, meal, non-screen |

## ADHD-Specific Adaptations

### The "One More Thing" Trap

ADHD brains often want to squeeze in "one more concept" at the end. This is counterproductive — the additional learning interferes with consolidation of the stronger material covered earlier.

**Agent should say:** *"I know you want to keep going — that's the dopamine talking. But the research is clear: stopping now and letting your brain consolidate will make [concept] stick better than cramming one more thing in."*

### Making the Transition

ADHD task transitions are hard. The wind-down protocol needs to be a clear, concrete action — not an abstract instruction.

**Good:** *"Stand up right now. Walk to the kitchen. Put the kettle on."*
**Bad:** *"Take some time to rest and consolidate."*

Give a specific, physical first step. The ADHD brain can follow a concrete action much more easily than an abstract concept like "rest."

### Post-Session Dopamine Management

After a productive study session, the ADHD brain may seek a dopamine replacement. Social media, games, or starting a new exciting task are tempting but destructive to consolidation.

**Suggest low-dopamine alternatives:**
- Walk outside (movement provides gentle dopamine without cognitive load)
- Make a hot drink (ritual + mild sensory engagement)
- Light physical activity (stretching, brief exercise)
- Listen to music (without lyrics — instrumental or ambient)

### Respecting Autonomy

If the student says "I'm fine, I want to keep going" or "I don't need a break":
1. Deliver the science once
2. Respect their decision
3. Don't nag or repeat
4. Note it for pattern recognition — if they consistently skip wind-down AND struggle with retention, mention the correlation later

## Integration with Spaced Repetition

The wind-down phase is the ideal moment to set expectations for the next review:

1. Name the concepts covered and their review schedule
2. Suggest specific times based on the schedule
3. Offer calendar blocks: `studyctl schedule-blocks --start <time>`
4. Frame the next session as a continuation, not a restart: *"Next time we'll build on [concept] — the hard part is done."*

## Key Research References

| Study | Finding |
|---|---|
| Buch et al. (2021), *Cell Reports* (NIH/NINDS) | Brain replays learning at 20x speed during wakeful rest; consolidation is ~4x overnight magnitude |
| Dewar et al. (2012), *Psychological Science* | Brief wakeful rest boosts new memories over the long term |
| Wamsley (2019), *Trends in Neurosciences* | Post-learning quiet rest enhances both procedural and declarative memory |
| PLOS ONE (2014) | Rest-induced memory boost does NOT depend on intentional rehearsal |
| Oppezzo & Schwartz (2014), Stanford | Walking benefit persists after sitting back down — ideal post-session activity |
