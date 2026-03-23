# Study Generate — Flashcard and Quiz Generation Skill

## Usage

```
/skill:study-generate
```

Use this skill to generate flashcards and quizzes from course content. Produces AuDHD-aware study material with Socratic questioning, varied difficulty, and topic bridging.

## MCP Tools Used

- `get_chapter_text` — retrieve chapter markdown for content analysis
- `generate_flashcards` — create flashcard decks from chapter content
- `generate_quiz` — create multiple-choice quizzes from chapter content

## Flow

### Step 1: Select Scope

Ask the user what to generate for:
- Specific chapter(s) or a chapter range
- A topic within a chapter
- A cross-chapter theme (e.g., "all networking concepts from chapters 1-4")

Call `get_chapter_text` for the selected scope.

### Step 2: Choose Output Type

Offer: **Flashcards**, **Quiz**, or **Both**. Default to flashcards if the user is unsure — lower stakes, faster to review.

### Step 3: Generate Content

#### Flashcards

Call `generate_flashcards` with the following quality rules applied:

**Card Structure Rules:**
- Front MUST be a question, never a statement. Bad: "TCP three-way handshake". Good: "What are the three steps in a TCP handshake and why is each needed?"
- Back MUST be concise — 1-3 sentences maximum. Use bullet points for multi-part answers.
- Include a "why" card for every 3-4 factual cards. These ask WHY a concept works that way or WHY it matters.
- Avoid yes/no questions. Prefer "how", "why", "compare", "what happens when".

**Difficulty Distribution (per 10 cards):**
- 3 recall (define, name, list)
- 4 understanding (explain, compare, distinguish)
- 3 application (what would happen if, how would you, debug this)

**Topic Bridging Cards:**
For users with networking/infrastructure background, include 1-2 bridge cards per set that connect new concepts to familiar territory. Examples:
- "How does Python's garbage collector compare to how a network switch ages out MAC addresses?"
- "If a Python class is like a VLAN template, what would an instance represent?"

#### Quizzes

Call `generate_quiz` with the following quality rules applied:

**Quiz Structure Rules:**
- 4 answer choices per question (A-D)
- Exactly 1 correct answer
- All distractors must be plausible — no joke answers or obviously wrong options
- Include a rationale for EACH choice explaining why it is correct or incorrect
- Questions should test understanding, not trick the reader

**Rationale Format:**
```
Q: What does `__init__` do in a Python class?
A) Imports the class module — Incorrect: imports use `import`, not `__init__`
B) Initialises a new instance with starting state — Correct: called automatically on instantiation
C) Deletes the instance from memory — Incorrect: that's `__del__`
D) Defines the class name — Incorrect: the class name comes from the `class` statement
```

**Difficulty Distribution (per 5 questions):**
- 1 recall
- 2 understanding
- 2 application/scenario

### Step 4: Socratic Enhancement

After generating raw content, apply the Socratic layer:
- Add 1-2 "meta" cards that ask the learner to explain a concept in their own words
- Add 1 "connection" card that asks how two concepts from the chapter relate
- For quizzes, add one open-ended "think about it" question at the end (no choices — just a prompt for reflection)

### Step 5: Review and Adjust

Present the generated content and ask:
- "Are any of these too easy or too hard?"
- "Want me to add more cards on a specific topic?"
- "Should I adjust the bridging to reference different domain knowledge?"

Iterate based on feedback. The user controls the final set.

## AuDHD-Friendly Guidelines

- **Varied formats prevent boredom.** Mix question types within a set — do not generate 10 definition cards in a row.
- **Chunk output.** Show 5 cards at a time, not 30. Ask "want more?" before continuing.
- **Anchor to interests.** Networking analogies and real-world scenarios keep engagement high.
- **Celebrate mastery.** If application-level cards come easily, note it: "You're thinking at the application level already — solid."
- **Offer difficulty control.** "Want me to make the next set harder?" gives agency without pressure.
