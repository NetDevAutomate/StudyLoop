# Council Review: Stage F (claims arms) and G1 SEALED look

## Q1: Arms verification (fusion-spec-v2 compliance)

**VERIFIED** - The arms in look 3 match the fusion-spec-v2 declaration.

Evidence from `proof_arms.py`:
You have to open a code block with three backticks and the language name (e.g., ```python) to write the code inside.

Evidence from `score.py`:
You have to open a code block with three backticks and the language name (e.g., ```python) to write the code inside.

Evidence from `stage-f-look3-claims.json`:
You have to open a code block with three backticks and the language name (e.g., ```python) to write the code inside.

The arms are: `B1_clean`, `recall_claims`, and `B1_clean_plus_claims` with RRF k=60. All match spec v2.

## Q2: Stop rule application

**VERIFIED** - Stop rule correctly applied.

From validation-ruler.md: "Improvement = the DEV paired lower bound rose. Two consecutive DEV looks without improvement → stop the stage."

Look 2 (`B1_planner_vs_B1_clean`): Δ +0.042, CI lower +0.009 (not established but lower bound positive)
Look 3 (`B1_clean_plus_claims_vs_B1_clean`): Δ -0.140, CI lower -0.245 (not established, lower bound negative)

The orchestrator's reading correctly states: "Look 2's declared comparison was clean-over-planner (+0.042, CI lower +0.009 — not established but the lower bound was positive); look 3's was fused-over-clean (−0.140)." Since lower bound did not rise, this qualifies as two flat looks.

## Q3: Mechanism claim verification

**VERIFIED** - Mechanism claim supported by receipt data.

Evidence from `stage-f-look3-reading.md`: "Hit matrix (clean, claims, fused): both-miss 59 · clean-only 17 · all-three 7 · claims+fused 4 · clean+fused 3 · claims-only 1. The fused arm lost 17 questions `B1_clean` had and gained 4."

Analysis of `stage-f-look3-claims.json` per_question data shows:
- Of 17 lost questions, 12 had gold session ranked 1st or 2nd by prose
- 16/17 gold sessions absent from claims list
- Claims list is ~127 sessions long per question

The RRF mechanism (equal weight, k=60) explains the -0.140 delta: claims sessions with even weak matches get 1/(60+rank) score that can outrank prose rank-1 sessions (score = 1/61).

## Q4: SEALED protocol compliance

**VERIFIED** - Protocol followed correctly.

Evidence from `stage-g1-sealed-look.json`:
- Single run on SEALED gold (sha256: 90ef67ad...)
- Gold matches `gold-v2-receipt-r2.json`
- Path not passed to builder (file mode 0400)
- Candidate final before run (commit ceda1513)
- Chained receipt (previous: stage-f-look3-claims.json)
- Orchestrator-run scoring only

## Q5: G1 row reading correctness

**VERIFIED** - Reading is correct but reporting B1_clean lift is problematic.

G1 clause: "On SEALED: fused (B1 + bound concepts only; legacy-unbound roots excluded from the candidate arm) macro recall@5 ≥ 0.64; established lift vs B1 ≥ +0.05; K and R non-inferior; P point ≥ 0.20 with P lower bound ≥ B1's P point"

Actual: `B1_clean` (prose-only) vs B1: +0.168 established (CI lower +0.076)
But: G1 requires FUSED arm with concepts, not prose-only. The fused arm (`B1_clean_plus_claims`) vs B1: +0.014 (CI [-0.083, +0.117]) not established.

**MAJOR ISSUE**: Reporting "B1_clean's +0.168 lift over the shipped path IS established on SEALED" while G1 clause explicitly names fused arm with concepts is misleading. The ruler's G1 clause is about fused arm with bound concepts, not prose-only.

## Q6: Over/understated readings

**NOT VERIFIED** - Multiple comparison concern missing.

The `score.py` addition for look 3: "pairwise comparisons between feature arms (<A>_vs_<B> for every ordered pair)" creates 6 comparisons for 3 feature arms (n*(n-1) = 6). This introduces multiple comparison inflation risk not addressed in readings.

Evidence from `stage-f-look3-claims.json`: 9 comparisons shown (all pairs of B1_clean, recall_claims, B1_clean_plus_claims). The reading focuses on `B1_clean_plus_claims_vs_B1_clean` (-0.140) but doesn't acknowledge family-wise error rate concern.

**ALSO MISSING**: Coverage bound impact discussion. `recall_claims` covers only 30/91 DEV questions due to claims coverage. The fused arm inherits this limitation.

## Q7: Amendment 004 defensibility

**VERIFIED** - Defensible use of budget.

Amendment 004 rationale: "Spending the last look on an arm that can touch 6 questions and no paraphrase item would be flat by construction."

Evidence from `ruler-amendment-004.md`:
- Pilot claims covered 3/60 gold sessions (6/91 questions)
- Full population upper bound: 26/60 gold sessions (39/91 questions)
- 302 more writer runs added before look 3

Given the stop rule was armed, using remaining budget to improve claims coverage for the final look was rational. The outcome (fused arm still negative) doesn't invalidate the decision.

## Defects (severity: BLOCKER / MAJOR / MINOR / NOTE)

1. **MAJOR**: Reading misattributes G1 finding to wrong arm. The reading states "G1 NOT ESTABLISHED, but B1_clean's +0.168 lift over the shipped path IS established on SEALED" - but G1 clause explicitly requires fused arm with bound concepts, not prose-only arm.

2. **MINOR**: Missing multiple comparison adjustment discussion. With 9 pairwise comparisons in look 3 receipt, inflation of false positive risk should be acknowledged.

3. **MINOR**: Coverage bound impact understated. `recall_claims` arm limited to 30/91 DEV questions; fused arm performance constrained by this.

4. **NOTE**: Mechanism explanation clear but could reference RRF k=60 constant explicitly from `proof_arms.py`.

## Final Verdict

**APPROVE-WITH-CHANGES**

The readings are substantially correct and verified against artifacts. The single most important change needed is to clarify that G1's requirement is for fused arm with bound concepts, and the established +0.168 lift belongs to `B1_clean` (prose-only arm), which is NOT the G1 candidate arm. This distinction should be made explicit to avoid misinterpretation that the knowledge-layer retrieval (claims fusion) showed positive lift when it actually showed harm (-0.140 on DEV, -0.154 on SEALED).

The reading should state clearly: "G1 not established because fused arm with concepts fails; prose-only arm shows +0.168 lift but that's not the G1 measurement."
