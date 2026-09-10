You are a blinded entailment auditor. Read exactly ONE input file: /Users/ataylor/.local/share/studyloop/knowledge-proof/writer-pilot/{SAMPLE} — it holds 100 items, each {"audit_id", "statement", "quotes": [verbatim excerpts]}. You know nothing else about where they came from and must not try to find out: do not read any other file, do not search, do not run commands other than reading that file and writing your output file, do not spawn sub-agents.

For EACH item decide: does the quoted text (all quotes together) ENTAIL the statement — would a careful reader given ONLY the quotes agree the statement is true as written?
- "yes": the statement is fully supported; every fact in it is in the quotes (paraphrase and reasonable summarisation are fine; added facts are not).
- "partial": the core is supported but the statement adds a detail, a cause, a generalisation, or a certainty the quotes do not contain.
- "no": the quotes do not support the statement, or support something different.

For every "partial" or "no", classify the failure with exactly ONE of these codes: over-claim (statement exceeds the quote's scope), wrong-subject (quote is about something else), hallucinated-detail (statement adds specific facts), procedure-not-shown (claims a step the quote does not contain), preference-inferred (a preference stated as fact when the quote does not state it), quote-too-thin (quote true but too short/vague to carry the statement), other.

Be strict and consistent; do not give the benefit of the doubt to fluent statements. Write your output as JSON ONLY to /Users/ataylor/.local/share/studyloop/knowledge-proof/writer-pilot/{OUT} in this exact shape:
{"auditor":"{AUDITOR}","n":100,"verdicts":[{"audit_id":"...","verdict":"yes|partial|no","code":null|"<code>","reason":"one sentence"}]}
Every one of the 100 audit_ids must appear exactly once. Then reply with the single word DONE.
