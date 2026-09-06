# The exact synthetic source grammar

This is a format contract for a tiny log adapter, not a grammar for arbitrary coding
conversations. Unsupported formats need their own adapter; guessing is not parsing.

- Lines follow Python `str.splitlines()` boundaries. Offsets count Python string
  characters in the original text, not UTF-8 bytes. Source versions cover id, kind
  and text. Target versions cover its complete field map.
- Exactly one line equals `[observed]` and one equals `[/observed]`, in that order.
  Whitespace around markers is not stripped. Multiple/unclosed/reversed markers fail.
- Inside that block, a declaration is a full line matching
  `(revision|workload|environment|metric|winner): (\S.*)`.
  The colon is followed by exactly one space before the non-whitespace-starting value.
  Key and value case are preserved. Trailing spaces in values are preserved.
- Other lines, including unknown keys and comments, are ignored. A malformed known-key
  line does not count as a declaration. This is a narrow recognition rule, not a
  claim that the whole artifact conforms to a general data format.
- Declaration order does not matter. Each of the five fields must have exactly one
  recognized declaration, even if repeated values agree. Duplicates remain ambiguous.
- A value's exact string must equal its target for all four scope fields. No trimming,
  alias matching, case folding, semantic similarity or latest-revision inference.
- Winner must equal A or B. Source kind must equal artifact. Kind is supplied by the
  fixture envelope and is not authenticated by parsing text.
- Outside-block lines never establish or duplicate an observed declaration.
- Target has exactly four nonempty string fields; invalid target is an input error,
  not an abstention. Model draft text never provides missing target metadata.

Candidate checks use Stage 10's verifier. An invalid proposal schema rejects all its
fields. Conservative acceptance uses only matched fields. Source-adapter acceptance
constructs a new derivation from source text and does not overwrite candidate status.
This intentionally permits recovery from an omitted or fabricated extraction when the
original structured source itself supplies unique, matching values.

The shared Stage 8 measured policy determines recommendation from that derivation.
A missing/invalid winner or unsupported source kind cannot be encoded as a made-up
valid source, so the policy receives no eligible source and the trace retains why.
