# Stage 16 results

The model followed captured origin in many cases but still promoted copied, missing
or rejected evidence into observed claims. The predeclared criterion for promotion
to an integration therefore **failed**. This is a useful experiment result, not a
reason to change the frozen prompt until these examples pass.

## Live annotation trial

Ten controlled development cases, text/capture arms, two repeats, forty Qwen3-Coder
calls. All forty returned original JSON with valid schema and exact source substrings.
Six processes were actually run by the local recorder; they emitted synthetic fixture
text. Four fixtures were narrative records. This did not validate real application
behaviour, historical exports or installed harness capture. Labels were coordinator-
authored and model-reviewed before calls, not independently adjudicated human gold.

| Information-available annotation measure | Text only / 20 | Capture metadata / 20 |
|---|---:|---:|
| State matches | 18 | 20 |
| Basis matches | 2 | 14 |
| Target matches | 20 | 20 |
| Scope matches | 18 | 20 |
| All four fields match | 0 | 14 |
| Exact quote substrings | 20 | 20 |
| Unsupported origin assignments | 18 | 6 |
| Invented missing targets | 0 | 0 |

Text-only basis must be unknown because origin metadata is absent. Sixteen responses
instead chose observed; two chose reported. The latter also guessed personal scope
from first-person wording (A07/A24). A constant-unknown baseline gets 10/10 raw basis
and scope fields but 0/10 state fields, making clear that raw basis agreement alone is
not intelligence or efficacy. The model did retain literal target identity in all cases.

The two text state mismatches (A29/A35) chose unknown when an untargeted source said
execution ended. They are conservative applicability interpretations against the frozen
source-state convention, not unsafe completion promotions. These label-sensitive cases
should not carry a general answer-quality claim.

## Where captured origin helped and failed

- **Identical real output versus quoted report:** A03/A11 used observed for the actual
  process; A17/A36 used reported for the conversation fixture. This is the intended
  origin distinction, with no high-level expected labels supplied in the payload.
- **Missing receipt, A06/A32:** both chose observed even though their rationale said
  origin was unknown. Code returned missing_receipt.
- **Rejected body, A01/A13:** both chose observed from PASS/exit-status wording despite
  a failed body check. Code returned body_changed. The model did not detect tampering;
  code had already removed the invalid envelope.
- **Spoof in narrative text, A15/A20:** both chose observed against a verified
  conversation_message receipt. A15 explicitly preferred the quoted process_exit
  wording; A20 misdescribed that wording as the receipt's origin. Code returned
  origin_mismatch. These two cases lost otherwise useful reported claims.
- **Failed process, A21/A28:** both retained completed command execution with an
  observed basis and exit status 3. Neither rationale asserted successful outcome.
  The text-only failed-exit drafts also retained the failure but incorrectly inferred
  observed origin from exit-status wording.

All capture-state/target/scope matches are fixture conformance. Most origin mapping
is mechanically derivable from low-level receipts; this trial does not establish that
an LLM is needed for it. Temperature zero did not guarantee identical rationale text.

## Separate release measurement

| Adapter result | Text arm | Capture arm |
|---|---:|---:|
| Justified full-capture assertion instances available | 10 | 10 |
| Justified instances released | 2 | 8 |
| Inapplicable instances released | 0 | 0 |

The adapter has the trusted receipts in both arms. Text-only coverage loss is largely
expected because the model lacks provenance/scope. Its two releases came from guessed
scope/origin that happened to match the hidden receipt, which the adapter checked.
They are not justified text-only inferences. Do not substitute 2/10 versus 8/10 for
annotation accuracy, or claim a causal improvement in general reasoning quality.

Wrong revision, wrong scope and missing invocation target were withheld. That is
adapter behaviour; correctly withholding them is not counted as model annotation skill.
The work-labelled fixture was synthetic and deliberately presented to the model. This
checks output applicability, not pre-retrieval work/personal access isolation.
There were no live narrative state/target overclaims in the releasable fixtures, but
the offline controls below demonstrate that this adapter can release those mistakes.

## Integrity versus interpretation controls

Fourteen controls comprise four honest claims, four post-capture/binding/seal defects,
four correctly sealed but source-contradicting annotations, and two correctly sealed
narrative misinterpretations.

| Acceptance path | Honest accepted / 4 | Incorrect accepted / 10 |
|---|---:|---:|
| Annotation + source/receipt integrity only | 4 | 6 |
| Integrity plus source-origin/applicability gate | 4 | 2 |

Twelve ordinary expectations matched. Two deliberate semantic failures survived:
wrong narrative state and wrong narrative target. Both keep valid hashes and genuine
quote substrings. They are false semantic releases, explicitly retained as known gaps.
Integrity alone is insufficient, and adding origin checks is still insufficient for
narrative entailment. A compromised recorder/manifest is outside the trusted-root model.

## Verification and preserved evidence

247 evidence-context tests passed, including all earlier stages. Browser checks
covered forty actual cards, four filtered spoof cases, expansion, ten offline reference
cards, fourteen controls, mobile width and no page errors. Ruff passed. The executed
source, shared Stage15 gate, prompt and frozen input bundle stayed unchanged after
execution. The private archive retains raw outputs, low-level receipts and council
responses; public observations.json contains measurements from synthetic material.

Gateway-reported answer cost was $0.011697 for forty calls, excluding council calls.
This is not a reconciled provider bill. No sessions.db, installed harness configuration,
production schema, prior stage or saved exercise was modified by this experiment.
Read COUNCIL-DECISION.md for review coverage, disagreements and the next bounded test.
