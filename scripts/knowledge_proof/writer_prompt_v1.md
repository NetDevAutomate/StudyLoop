# Writer prompt v1 (claims-writer-spec-v1)

You are distilling ONE coding-agent session into durable, citable claims for a learner who will
return to this topic weeks from now. You are given the session's prose as numbered evidence rows
(each has an `evidence_id`, the speaker role, and the exact text) and a few derived flags per
exchange (whether the learner asked a question, whether an error occurred, whether the exchange
resolved). You have no other context and must not assume any.

Write 0 to 8 claims. Fewer, well-grounded claims beat many weak ones. Write ZERO claims if the
session contains nothing a learner could act on later (greetings, probes, warm-ups, pure tool
chatter).

Each claim is ONE of:
- **Problem** — a difficulty the learner hit, stated as the learner would recognise it.
- **Finding** — a fact established in the session (what turned out to be true).
- **Decision** — a choice made and, if stated, why.
- **Procedure** — a sequence of steps that was actually carried out and worked.
- **Preference** — a stated preference of the learner (only if the learner states it).

Rules that are enforced mechanically — a claim that breaks one is discarded, not repaired:
1. Every claim has at least one citation. A citation is `{"evidence_id": ..., "quote": ...}` where
   `quote` is an EXACT, VERBATIM substring of that evidence row's text — same characters, same
   spacing, same punctuation. Do not paraphrase, trim internal words, or fix typos in the quote.
2. The quote must appear exactly once in that evidence row. If a phrase repeats, quote a longer
   span that is unique.
3. The `statement` must be ENTAILED by the quoted text: a careful reader given only the quote
   would agree the statement is true. Do not add facts the quote does not contain. Do not
   generalise beyond it. If you need two quotes to support one statement, give two citations.
4. `title` ≤ 120 characters; `statement` ≤ 500 characters; `tags` 2–5 short lower-case tokens;
   `confidence` between 0.5 and 1.0, where 1.0 means the quote states it outright and 0.5 means
   the quote strongly implies it.
5. Prefer quoting the learner's or the assistant's words about what happened over quoting
   instructions, briefs, or pasted documents.

Output ONLY this JSON, no prose before or after:

{"claims": [
  {"kind": "Finding", "title": "...", "statement": "...", "tags": ["...", "..."],
   "confidence": 0.9, "citations": [{"evidence_id": "...", "quote": "..."}]}
]}

If there is nothing worth keeping: {"claims": []}
