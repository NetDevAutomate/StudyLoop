# Teach-Back Protocol

Structured protocol for "Teach the Teacher" — when the student explains concepts back to the mentor. Based on the Protege Effect (Chase et al., 2009): people learn more deeply when they believe they are teaching.

## When to Trigger Teach-Back

Teach-back is layered into spaced repetition at increasing depth:

| Interval | Review Type | Teach-Back Level |
|---|---|---|
| 1 day | 5-min recall quiz | None — too early for teach-back |
| 3 days | 10-min Socratic review | **Micro**: "In one sentence, explain [concept] to me." Score Accuracy + Own Words only. |
| 7 days | 15-min deep review | **Structured**: Full 5-dimension rubric. Vary question angle from last review. |
| 14 days | Apply to new problem | **Transfer**: "Explain how [concept] applies to [novel scenario]." Score Transfer + Depth. |
| 30 days | Teach-back session | **Full**: Student explains as if teaching someone new. All 5 dimensions scored. |

Additionally, trigger an **ad-hoc teach-back** when:
- The student reaches L3 Independent or L4 Teaching scaffolding level on a concept
- The student says something like "I think I get it" or "that makes sense now"
- A concept has appeared in 3+ sessions (recurring struggle — try teach-back as a different approach)

## Scoring Rubric (5 Dimensions, 4 Levels)

| Dimension | 1 - Recitation | 2 - Paraphrase | 3 - Explanation | 4 - Teaching |
|---|---|---|---|---|
| **Accuracy** | Significant errors or omissions | Mostly correct, minor gaps | Accurate with nuanced detail | Accurate and anticipates edge cases |
| **Own Words** | Verbatim repetition of source material | Mixed: some own words, some parroted | Consistently uses own language | Creates novel analogies or framings |
| **Structure** | Disconnected facts, no logical flow | Some structure but relationships unclear | Clear logical flow showing cause/effect | Builds narrative sequenced for the listener |
| **Depth** | States WHAT only | States WHAT and partially HOW | Explains WHAT, HOW, and WHY | Addresses WHY, tradeoffs, when NOT to use |
| **Transfer** | Cannot apply to new context | Applies with heavy hints | Independently applies to related scenario | Generates novel examples or counter-examples |

### Score Interpretation

| Total Score | Meaning | Spaced Repetition Action |
|---|---|---|
| 5-8 | Memorised, not understood | Reset interval to 1 day. Try different angle next time. |
| 9-13 | Partial understanding | Same interval. Probe the specific gaps. |
| 14-17 | Solid understanding | Extend interval. Concept progressing well. |
| 18-20 | Mastery demonstrated | Maximum interval extension (90-day check-in). Move to `mastered` confidence. |

### Micro Teach-Back (3-day review)

Only score 2 dimensions: Accuracy and Own Words (max 8 points).

| Score | Meaning | Action |
|---|---|---|
| 2-3 | Surface recall only | Flag for deeper review at 7-day mark |
| 4-5 | Partial | Note gaps, continue schedule |
| 6-7 | Good recall in own words | On track |
| 8 | Strong | Consider accelerating interval |

## Detecting Understanding vs Memorisation

### Red Flags (Surface Learning)

- Uses the exact same words, phrases, or sentence structures as the source material
- Cannot answer "what if?" variations on the concept
- Explanation breaks down when asked for an unseen example
- Can state WHAT but not WHY
- Treats concept as isolated fact, no connections to other concepts
- Confidence collapses when question angle changes

### Detection Probes

Use these probes after a teach-back to test depth. Rotate between them — don't use the same probe twice in a row.

1. **"Explain it differently"**: "Now explain it as if I'm a [different audience]."
   - Options: network engineer, junior dev, non-technical manager, 10-year-old
   - Why: Genuine understanding allows register-shifting. Memorisation produces the same explanation regardless of audience.

2. **"Break it"**: "What would happen if we removed [key component]?" or "When would this approach fail?"
   - Why: Understanding includes boundary knowledge. Memorisation cannot reason about failure modes.

3. **"Analogy generation"**: "Can you give me an analogy from [student's expert domain]?"
   - Why: Generating a novel analogy requires structural understanding, not surface recall.

4. **"Near transfer"**: Present a slightly different problem that uses the same underlying principle.
   - Why: Memorisers match on surface features and fail with different surface details. Understanders recognise the deep structure.

5. **"Counter-example"**: "When would you NOT use this? What's the wrong situation for this approach?"
   - Why: Knowing when NOT to apply is a strong signal of genuine understanding.

6. **"Connection"**: "How does this relate to [previously covered concept]?"
   - Why: Isolated memorisation produces no connections. Understanding creates a web.

## Varying the Question Angle

The agent MUST vary the angle on each review to avoid repetitive drilling. Track which angles have been used per concept.

### Bloom's Rotation

Cycle through Bloom's Taxonomy levels across reviews:

| Review | Bloom's Level | Example Question |
|---|---|---|
| 1st | Remember + Understand | "What is [concept]? Explain in your own words." |
| 2nd | Apply | "How would you use this to solve [specific scenario]?" |
| 3rd | Analyse | "What are the components? How do they relate?" |
| 4th | Evaluate | "What are the tradeoffs vs [alternative]?" |
| 5th | Create | "Design a solution for [novel problem] using this." |

### Context Rotation

Same concept, different scenario each review:
- Review 1: "Explain Spark partitioning."
- Review 2: "You have a 2TB skewed dataset on customer_id. Design the partitioning."
- Review 3: "Your colleague chose hash partitioning. What are the tradeoffs vs range here?"
- Review 4: "Explain Spark partitioning using a networking analogy."

### Modality Rotation

Switch between delivery modes:
- Verbal explanation
- Code exercise (implement it)
- Diagram interpretation or creation
- Debug a broken implementation
- Teach-back to the mentor
- Compare/contrast with alternative approach

### Direction Reversal

Flip the question orientation:
- "What is X?" → "When would you NOT use X?"
- "How does X work?" → "What problem does X solve?"
- "Implement X" → "What existed before X? Why was it insufficient?"

## Recording Teach-Back Scores

After each teach-back, record the score:

```bash
studyctl teachback "<concept>" -t <topic> --score "3,3,4,3,2" --type structured --angle "apply_network_analogy"
```

The agent should:
1. Assess the teach-back internally using the rubric
2. Propose the score to the student: "I'd score that as: Accuracy 3, Own Words 3, Structure 4, Depth 3, Transfer 2 — total 15/20. That's solid understanding with room on the transfer dimension. What do you think?"
3. Adjust if the student disagrees (metacognitive calibration)
4. Record the agreed score

### Score Transparency

Share the score with the student. This builds metacognitive awareness — the ability to accurately self-assess. Over time, the student's self-assessment should converge with the agent's assessment.

If there's a consistent gap (student rates higher than agent's assessment), address it: "You're rating your understanding higher than what I'm seeing in the explanation. Let me probe a specific area..."

## Avoiding Repetitiveness

NSW Education Department principle: "Scaffolding questions allows repetition without being repetitive. Each time you lead students to a different level of question, they revisit what they know and use it differently."

**Rules:**
- Never ask the same question twice across reviews
- Track `angles_used` per concept and rotate through Bloom's levels, contexts, modalities, and directions
- If a concept has been reviewed 3+ times, require a different modality each time
- If a concept has been through all standard angles, use interleaving: bridge to a related concept

## Integration with Confidence Levels

Teach-back scores provide a richer signal than the binary confidence levels:

| Confidence Level | Teach-Back Threshold |
|---|---|
| struggling | Score < 9 on any teach-back |
| learning | Score 9-13, OR passed micro but not structured |
| confident | Score 14-17 on structured or transfer teach-back |
| mastered | Score 18-20 on full teach-back, sustained across 2+ reviews |

The agent should use teach-back scores to validate (or challenge) self-reported confidence. If a student says "confident" but scores 10 on a teach-back, there's a gap to address.

## Key Research References

| Study | Finding |
|---|---|
| Chase et al. (2009), *J Science Education & Technology* | The Protege Effect — learning by teaching triggers deeper processing |
| Kobayashi (2019), meta-analysis | Preparing to teach uses 1.3x more metacognitive strategies |
| Cohen, Kulik & Kulik (1982), meta-analysis | Tutors gain academic benefit, not just tutees |
| Karpicke & Blunt (2011), *Science* | Testing effect works for conceptual knowledge, not just facts |
| Matuschak (2020) | Spaced repetition can develop conceptual understanding with proper prompt design |
