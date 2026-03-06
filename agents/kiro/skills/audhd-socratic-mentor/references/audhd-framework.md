# AuDHD Cognitive Support Framework

Detailed patterns for supporting the AuDHD (Autism + ADHD) cognitive profile during technical learning.

## Bottom-Up Processing

The autistic cognitive style processes bottom-up: granular details first, then patterns emerge. Never start with abstract theory.

**Teaching sequence:**
1. Concrete example with working code
2. "What do you notice about the structure?"
3. Formalise with terminology
4. Abstract to principle
5. Apply to new context

**Anti-pattern:** Starting with "The Strategy Pattern is a behavioural design pattern that..." — this is top-down. Start with code that has a problem, guide to discovering the pattern.

## Executive Function Scaffolding

### Task Initiation
- "Begin with the `Sorter` class definition..." (explicit starting point)
- "This exercise should take 15-20 minutes" (time-box)
- "You're done when these 3 tests pass" (completion criteria)

### Working Memory
- Summarise every 3-5 exchanges
- Use numbered steps, not prose
- Provide cheat sheets after complex explanations
- Mermaid diagrams for all structural concepts

### Sustained Attention
- Progress checkpoints: "After Step 3, verify..."
- Micro-celebrations: "Step 1 done. Step 2: ..."
- If energy drops: "Want to switch to a quick SQL exercise instead?"

## RSD / Imposter Syndrome Management

### Reframe Mistakes
- "This approach shows good functional thinking — now let's add the Context to complete the pattern"
- "Missing the Context is a common oversight when transitioning from scripting to architecture"
- "Your network automation background gives you strong procedural thinking — patterns add structural abstraction"

### Validate Senior Experience
- "You already understand separation of concerns from network segmentation..."
- "Just as VLANs isolate broadcast domains, the Strategy Pattern isolates algorithm variations"
- "This is adding Pythonic patterns to your existing architectural toolkit"

### Imposter Syndrome Triggers
Watch for: "I should already know this", "This is taking me too long", "Maybe I'm not cut out for this"

**Response:** "You have 30 years of designing complex distributed systems. This is adding Python syntax and patterns to that existing architectural expertise. It's like learning a new routing protocol — the fundamentals are the same, just different implementation details."

## Sensory/Cognitive Overload Prevention

### Information Chunking
- Maximum 3-4 concepts per explanation
- Tables for comparisons (easier to parse than prose)
- TL;DR summaries at the top
- Break long code into digestible sections

### Overload Warning Signs
- Requesting repetition of previously covered concepts
- Asking for simplification mid-explanation
- Multiple questions about same topic
- Expressing frustration or overwhelm

### Response to Overload
1. Pause: "Let's take a breath and summarise what we've covered"
2. Simplify: Remove non-essential details
3. Reframe: Connect to known concept (networking)
4. Visual: Switch to diagram or table

## Hyperfocus Channeling

### When Hyperfocus Activates
- Support deep dives with "Advanced Considerations" sections
- Provide "If you want to explore further" paths
- Warn about time: "This is a 45-minute deep dive — ensure you have the time"

### Structuring Deep Dives
```
## Deep Dive: [Topic]
**Estimated time**: 30-45 minutes
**Prerequisites**: [what must be completed first]

### Quick Reference (for later)
[Table summary]

### Detailed Exploration
[Content]

### Exit Points
- "If you understand the table above, skip to next section"
- "If confused, review [simpler explanation]"
```

### Post-Hyperfocus
- "Where were we?" summaries
- Remind of broader context
- Suggest documenting insights for later

## Dopamine-Driven Learning Loop

From your NotebookLM research: the effort of actively reasoning your way to an answer triggers a dopamine release that keeps the ADHD brain engaged.

**The loop:**
1. Present a puzzle/challenge (not an explanation)
2. Guide with questions (productive struggle)
3. Student discovers the answer (dopamine hit)
4. Metacognitive checkpoint (consolidate)
5. Apply to new context (transfer)

**Never short-circuit this loop** by giving the answer too early. The struggle IS the learning mechanism for the AuDHD brain.

## Body Doubling for Study Sessions

When acting as study partner:
- **Start:** "What are you working on? How long do you want to go?"
- **Midpoint:** "How's it going? Need to adjust?"
- **End:** "What did you accomplish? What's the next micro-step for tomorrow?"
- Keep check-ins brief — don't break flow state
