# Study Audio — TTS Study Summary Generation Skill

## Usage

```
/skill:study-audio
```

Use this skill to generate spoken study summaries from chapter content. Produces conversational audio files suitable for revision while walking, commuting, or doing chores.

## MCP Tools Used

- `get_chapter_text` — retrieve chapter content for summarisation

## CLI Commands Used

- `studyctl study-speak` — generate TTS audio from a text script

## Flow

### Step 1: Select Chapter

Ask the user which chapter or topic to generate audio for. Call `get_chapter_text` to retrieve the source material.

### Step 2: Write the Summary Script

Compose a spoken study summary from the chapter content. The script is plain text that will be read aloud by TTS.

**Script Structure:**
1. **Opening hook** (1-2 sentences) — State what this chapter covers and why it matters. Start with engagement, not a dry overview.
2. **Core concepts** (3-5 key ideas) — Explain each concept conversationally. Use analogies and concrete examples. Pause between concepts with transition phrases.
3. **Connections** — Link concepts to each other and to prior chapters. "Remember when we talked about X? This builds on that because..."
4. **Quick recall check** — Pose 2-3 questions for the listener to answer mentally. "Can you name the three types of...?" Leave a beat for thinking.
5. **Wrap-up** (1-2 sentences) — Summarise the takeaway and preview what comes next.

**Script Writing Rules:**
- Write for the ear, not the eye. Short sentences. No parenthetical asides.
- Use "you" and "we" — make it feel like a conversation, not a lecture.
- Avoid acronyms on first use — spell them out, then use the short form.
- No markdown formatting, bullet points, or special characters — pure spoken prose.
- Target 3-5 minutes of audio per chapter (~500-800 words).
- Include natural transitions: "So now that we've covered X, let's look at Y."

**Tone Guidelines:**
- Conversational and warm, like a knowledgeable friend explaining over coffee.
- Confident but not condescending. Assume the listener is smart but new to this topic.
- Inject genuine enthusiasm for interesting concepts. "This is where it gets clever..."
- Keep energy varied — monotone kills attention. Use rhetorical questions to re-engage.

### Step 3: Generate Audio

Run `studyctl study-speak` with the script to produce the audio file. The output goes to the course's `audio/` directory.

```
studyctl study-speak --course <name> --chapter <number> --script <script_path>
```

Confirm the output file path and duration with the user.

### Step 4: Offer Iteration

Ask:
- "Want to listen to a preview before I save the final version?"
- "Should I adjust the length — shorter for a quick refresher or longer with more detail?"
- "Want me to generate audio for the next chapter too?"

## AuDHD-Friendly Guidelines

- **Audio is ideal for AuDHD learners.** Movement + listening often beats sitting + reading. Frame this as a strength, not a workaround.
- **Keep it short.** 3-5 minutes is the sweet spot. Anything over 7 minutes risks losing attention. Offer to split longer chapters into parts.
- **Engaging beats comprehensive.** A summary that covers 80% of key ideas in an interesting way is better than a complete but dry recitation of 100%.
- **Varied pacing.** Mix explanation with questions. The listener's brain needs moments to process, not just receive.
- **Suggest pairing.** "Try listening to this on a walk, then do the flashcards when you get back" — multimodal reinforcement without pressure.
