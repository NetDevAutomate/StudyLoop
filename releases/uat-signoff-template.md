# UAT sign-off evidence template

This is a TEMPLATE, not a real sign-off record: it documents the exact
shape a real run's REDACTED summary carries into a release note, produced
by `tests/acceptance/uat/redaction.py`'s `redact_summary()` from a private
evidence bundle (`tests/acceptance/uat/bundle.py`). No raw transcript,
screenshot, absolute home path, or key ever appears here — only the
allowlisted, structured fields pinned in `redaction_rules_v1.yaml`.

See `docs/acceptance-testing.md`'s "The UAT (sign-off) tier" section for
the full mechanism, and council rulings D-13/D-14/D-22 (kimi F12/F13) in
`reviews/2026-09-15-acceptance-harness/` for why the shape below is
exactly this and no more.

## Fields

| Field | Meaning |
| --- | --- |
| `run_id` | This run's identifier — also the private bundle's directory name under the durable evidence root. |
| `date` | Runner-injected ISO 8601 timestamp. |
| `repo_sha` | The commit this run was cut against. |
| `harness` | Which coding harness played the mentor. |
| `harness_version` | That harness's own reported version, or `null` if unknown. |
| `actor_backend` | Which learner backend drove the conversation (`scripted`, `gateway`, `direct`, `harness`). |
| `actor_model` | The model behind that backend, or `null` (e.g. `scripted` has none). |
| `rubric_version` | Which pinned rubric version graded this run. |
| `rubric_hash` | That rubric file's pinned sha256, so a reader can verify it against the committed rubric. |
| `journeys` | Per-journey pass/fail (never "skipped" for a REQUIRED journey — a sign-off with any required skip never reaches this template at all, per the strict runner). |
| `per_criterion_scores` | Every rubric criterion's score, with a reference into the (private) evidence bundle a reader with access could inspect — never the evidence itself. |
| `arbitration_note` | The coordinator's arbitration summary across council seats. |
| `private_bundle_digest` | A digest identifying the private bundle this summary was redacted from, without exposing its contents or location. |

## Example (illustrative values only)

```json
{
  "run_id": "uat-2026-09-30-0001",
  "date": "2026-09-30T14:02:11Z",
  "repo_sha": "abc1234",
  "harness": "kiro",
  "harness_version": "1.4.2",
  "actor_backend": "gateway",
  "actor_model": "gpt-5.6-sol",
  "rubric_version": 1,
  "rubric_hash": "<sha256 of the rubric version above, e.g. rubric_registry.json's pinned value>",
  "journeys": {
    "session_lifecycle": "passed",
    "wind_down_resume": "passed",
    "embeddings_semantic_participation": "passed"
  },
  "per_criterion_scores": {
    "accuracy": 5,
    "pedagogy": 4,
    "session_lifecycle": 5
  },
  "arbitration_note": "Unanimous pass; pedagogy docked one point for a missed comprehension check after turn 4.",
  "private_bundle_digest": "sha256:9f1c2e..."
}
```
