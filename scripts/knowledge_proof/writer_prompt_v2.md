# Writer prompt v2 (claims-writer-spec-v2)

You are distilling ONE coding-agent session into durable, citable claims for a learner who will
return to this topic weeks from now. You are given the session's prose as numbered evidence rows
(each has an `evidence_id`, the speaker role, and the exact text) and a few derived flags per
exchange. You have no other context and must not assume any.

Write 0 to 8 claims. Fewer, fully-grounded claims beat many. Write ZERO claims if the session
contains nothing a learner could act on later (greetings, probes, warm-ups, briefs addressed to
an agent, pure tool chatter).

Each claim is ONE of: **Problem** (a difficulty the learner hit), **Finding** (a fact established
in the session), **Decision** (a choice made and, if stated, why), **Procedure** (steps actually
carried out that worked), **Preference** (a preference the learner states in their own words).

THE ONE RULE THAT MATTERS MOST — a reader will be given ONLY your quotes and asked whether they
prove your statement. **Every factual element in the statement must be visible in a quote.**
Before you finish each claim, check it element by element: each number, name, cause, list item,
outcome and qualifier in the statement — which quote shows it? If a detail has no quote, either
add a citation that shows it or delete the detail from the statement. Do not summarise several
sentences of the session into one statement and then cite only one of them. Do not state as
fact what the session merely implies.

Rules that are enforced mechanically — a claim that breaks one is discarded, not repaired:
1. Every claim has 1 to 4 citations; **prefer 2 or 3** — one quote rarely covers a whole
   statement. A citation is `{"evidence_id": ..., "quote": ...}`.
2. `evidence_id` is the FULL 64-character hexadecimal id copied exactly from the row header
   `evidence_id=…`. Never the row number, never `E12`, never a shortened id.
3. `quote` is an EXACT, VERBATIM substring of that evidence row's text — same characters, same
   spacing, same punctuation. Do not paraphrase, trim internal words, or fix typos. The quote
   must occur exactly once in that row; if a phrase repeats, quote a longer span.
4. `statement` ≤ 300 characters (shorter than before, on purpose: a shorter statement is easier
   to cover completely). `title` ≤ 120. `tags` 2–5 short lower-case tokens. `confidence` 0.5–1.0,
   where 1.0 means every element is stated outright in the quotes.
5. Prefer quoting the learner's or the assistant's words about what happened over quoting
   instructions, briefs, or pasted documents.

Output ONLY this JSON, no prose before or after:

{"claims": [
  {"kind": "Finding", "title": "...", "statement": "...", "tags": ["...", "..."],
   "confidence": 0.9,
   "citations": [{"evidence_id": "<64 hex>", "quote": "..."}, {"evidence_id": "<64 hex>", "quote": "..."}]}
]}

If there is nothing worth keeping: {"claims": []}
