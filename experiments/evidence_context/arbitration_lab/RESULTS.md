# Stage 6 observed results

Two synthetic development rounds: Qwen3-Coder, temperature 0, four cases × three
context conditions. All 24 responses parsed. No independent quality grade or
real-history efficacy is claimed. Inputs and outputs were preserved before tuning.

| Case | Keyword (both prompts) | Relationships/reference (both prompts) | Coordinator interpretation |
|---|---|---|---|
| Changed cache constraints | conditional; original assumption does not apply | B, reported_only, with caveats | Context introduces a plausible alternative. The explicit v2 conditional instruction was not reflected in the recommendation enum. Category mismatch alone is not proof of a bad rationale. |
| Retry correction with fixture check | insufficient; no check supplied | B, artifact_supported, scenario limits stated | Missing evidence explains the baseline's inability to make the fixture-supported choice. |
| Storage unequal evidence with fixture check | insufficient; no check supplied | B, artifact_supported, reopen-only scope | Similar retrieval effect. Conflict category varies (correction versus unequal_evidence), revealing taxonomy ambiguity. |
| Unsupported queue-speed disagreement | insufficient | B, correction, reported_only, no benchmarks admitted | Main failure: the model invents supersession from later advice despite both prompt versions warning against it. |

The queue/reference v2 rationale says the second report is "presented as a correction".
The source only says later advice claims B is faster and that no benchmark was run.
That supports the existence of disagreement, not a measured performance preference.
A caveat about missing benchmarks does not fix the unjustified recommendation.

All citation IDs existed and no artifact_supported answer lacked a cited fixture
artifact. Those mechanical checks therefore missed the queue semantic failure.
Three keyword answers had empty citation lists in v1; all answers cited sources in
v2. Better citation formatting did not resolve the central reasoning problem.

| Round | Gateway-reported total tokens | Gateway-reported cost USD |
|---|---:|---:|
| v1 | 10,787 | 0.00620464 |
| v2 | 13,134 | 0.00720604 |
| Total | 23,921 | 0.01341068 |

Relationship and reference messages are identical in all four cases in both rounds.
That gives eight distinct inputs per prompt; repeating them under two arm labels
does not create independent evidence of a retrieval effect.

Costs are the gateway response-cost values at run time, not an invoice or general
price quote. This excludes council review. One sample per condition, provider
caching and local load prevent latency or stability conclusions. Temperature zero
does not establish repeatability; actual outputs differ even with similar inputs.

## What these observations justify

They justify keeping retrieval failure separate from arbitration failure, retaining
raw evidence trails and testing enforcement/representation assumptions. They do
not establish that graphs help real questions, that a model family is generally
unreliable, or that SQLite is optimal. Both prompt versions and failed examples
are kept intact for learning and future regression use.
