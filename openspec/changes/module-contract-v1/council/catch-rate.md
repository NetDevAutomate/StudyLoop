# Review catch-rate ledger — module contract v1

One row per review in `design.md` §7. Filled by the coordinator **after** verifying every
finding against the tree. "Coordinator call" is written **before** the review is dispatched,
so the ledger measures what the review added, not what it confirmed. M2 reads this table and
says whether the cadence earned its cost; a seat whose verified rate stays low is dropped.

Columns: raised = findings the seat(s) made; verified = confirmed against source or a test;
acted = changed code, tests or docs; discounted = false or unverifiable, with the reason.

| Review | Date | Seat(s) | Coordinator call (before) | Raised | Verified | Acted | Discounted (why) | Pointer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-review | 2026-10-04 | gpt-5.6-sol | Diff is small and mechanical (S1 `ea56f656` guard re-key, S2 `b462ed42` six fields). Expect 0–2 findings, verdict `merge` or `merge after fixes` on evidence only: (a) S1 has no red transcript under `evidence/S/` — the S brief asked for tests but not a saved red, while design.md's red-first rule does; (b) next-lane risks are the new public names `SlugId` / `SLUG_PATTERN` / `ScaffoldingLevel` in `content/schemas.py` that C's MC014 will import, and the `lane_ownership.yaml` glob transcription for files C/R/T create. I do not expect an ownership or scope finding. | | | | | |
| M0 transport decision | | | | | | | | |
| C-review | | | | | | | | |
| M1 runner security | | | | | | | | |
| T-review | | | | | | | | |
| W-review | | | | | | | | |
| M2 release proof | | | | | | | | |

## Baseline: the two 2026-10-04 rounds (for calibration)

| Round | Seats | Raised (approx.) | Verified and acted | Discounted (why) |
| --- | --- | --- | --- | --- |
| proposal review | gpt-5.6-sol, glm-5, deepseek-3.2, qwen3-coder-next | ~40 | shell=True seam, learner observation written by `practice verify`, mentor delivery unbacked, estimate low, six fields not three, duckdb target kind, MC013–MC016 | DeepSeek: `doctor/` "two files" (eleven); Qwen: `agents/shared/` "absent" (fourteen entries) |
| plan review | same four | ~35 | GPT's sequencing and lane structure; no pre-push stage; `ActiveSession.transport` already exists | GLM: answered from a lost context (whole seat); DeepSeek: `"modules": []` key in `_options.py` (does not exist) |
