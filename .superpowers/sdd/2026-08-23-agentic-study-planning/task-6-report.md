# Task 6 report — confined Architect runtime contract

## Outcome

StudyLoop now owns an installed, provider-neutral Architect boundary without
depending on a coding harness, ACP, MCP, or an external agent installation. The
release-one model surface is deliberately small: one packaged prompt, one
versioned streaming port, and exactly three deeply immutable capabilities
pre-bound to one lifecycle request/run.

This is the foundational contract, not the finished conversation product. The
durable live conversation runtime remains Task 7; learner-decision provenance
and browser workflow remain Tasks 8-9.

## Delivered behavior

- The wheel includes `architect.md` with a machine-validated contract header.
  The prompt starts from a free-text/spoken dump, normally asks one high-value
  question, permits no more than three tightly coupled questions, produces a
  provisional plan by clarification turn three, enforces the Rule of Three,
  treats course/note/transcript material as untrusted tier-four context, and
  states explicitly that notes are not progress.
- `PlanningModelPort` carries correlated, schema-versioned requests and
  text/tool/completion events. `ScriptedPlanningModel` implements the same port
  and validates turn ID, attempt ID, wire version, and strictly increasing event
  sequence without loading a provider.
- `PlanningModelProfile` stores a normalized fixed HTTP(S) base URL, selected
  model, timeouts, and only an `env:` or encrypted `secret:` reference. Unknown
  profile fields and URL credentials/query/fragment are refused. Readiness
  probes resolve the reference ephemerally and never return or log plaintext.
- Local LiteLLM detection uses only a finite tuple of literal `127.0.0.1`/`::1`
  candidates. It disables proxy-environment inheritance, refuses redirects,
  checks the connected socket peer while the stream remains open, and pins the
  normalized gateway/model. It performs no DNS, LAN, multicast, or filesystem
  discovery.
- `PLANNING_CAPABILITY_SCHEMAS` is a deeply immutable, exact three-entry tuple:
  `prepare_plan`, `submit_plan_proposal`, and `get_plan_proposal`. The exhaustive
  dispatcher has no dynamic registry/import surface, model-supplied actor, or
  decision/import/status/evidence-recorder/progress/shell/file/browser/HTTP
  capability. It binds the model actor, lifecycle request, and run on the
  server. `Resource.url` is strictly validated inert proposal data; no runtime
  code dereferences it.
- Setup adds no curriculum/intake question. Notes remain optional. It runs the
  provider-free preflight, preserves a valid existing fixed model profile,
  supports explicit CLI profile options, and otherwise auto-detects only the
  literal-loopback candidates. Coding-harness discovery is labelled as study
  integration and never contributes to planning readiness.
- Doctor reports prompt version, exact schema catalogue, scripted preflight,
  model configuration/reachability, and the final `scripted only` versus
  `live certified` state separately without rendering secret references.
- LAN cleanup removes the plaintext credential feedback DTO and returned
  plaintext lines. Human-entered passwords stay inside credential preparation;
  only a newly generated one-time password may cross the immediate output
  callback. Credential-bearing mapping/array/scalar session-state shapes are
  atomically scrubbed. CLI runtime output and all adjacent public workflows now
  warn that plain HTTP has no transport confidentiality and weak-password
  verifiers are offline guessable.
- Credential-FD transport still conveys only bounded access-control material.
  It cannot construct a learner `ActorContext` or add a planning capability.

## Authority and adversarial evidence

The negative suite submits explicit attempts to decide, approve, import,
transition status, record trusted evidence, mark progress/completion, run shell
or file operations, drive a browser, perform HTTP/URL requests, invoke
`__import__`, call a dynamic registry, inject credentials/actors, and use a
foreign run ID. Every attack is refused before a lifecycle call. Nested actor
and HTTP-like fields are rejected as closed-schema violations. A validated
HTTP(S) `Resource.url` is accepted only as inert citation content.

The allowed-path test passes all three calls through the same dispatcher and
lifecycle seam, proving the negatives do not describe a dead interface.

## TDD evidence

### RED

1. The first focused run produced 33 failures because the prompt package,
   configuration/port, capability catalogue, scripted adapter, and doctor check
   did not exist. Setup and LAN tests also failed on their old contracts before
   production code was changed.
2. A real loopback HTTP-server regression disproved the first peer-verification
   implementation: detection returned `None` because HTTPX socket metadata was
   queried after the response context had closed. The implementation now uses a
   streamed response and validates the peer before reading/closing it.
3. Authenticated readiness tests failed because probes did not resolve secret
   references and attempted network access when a reference was missing. The
   probe now resolves only validated references, passes a transient Bearer
   header, and fails closed before creating a client.
4. An exact-config negative showed that an unknown plaintext `api_key` field
   was silently ignored while the remaining profile was accepted. Config
   decoding now refuses every field outside the five-field profile contract.

### GREEN

```text
rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning_model_config.py \
  packages/studyloop/tests/test_planning_capabilities.py \
  packages/studyloop/tests/test_planning_prompt_package.py \
  packages/studyloop/tests/test_planning_scripted_model.py \
  packages/studyloop/tests/test_setup_wizard.py \
  packages/studyloop/tests/test_learner_credentials.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_web_runtime_feedback.py -q
# 99 passed

rtk uv run --group dev pytest packages/studyloop/tests/test_doctor_planning.py -q
# 4 passed

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_planning*.py \
  packages/studyloop/tests/test_plan_agent_harness.py \
  packages/studyloop/tests/test_doctor_planning.py \
  packages/studyloop/tests/e2e/test_plans_api.py -q
# 350 passed, 12 deselected

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_doctor*.py \
  packages/studyloop/tests/test_setup_wizard.py \
  packages/studyloop/tests/test_learner_credentials.py \
  packages/studyloop/tests/test_session_state.py \
  packages/studyloop/tests/test_web*.py -q
# 656 passed, 295 deselected, one pre-existing Starlette/httpx warning

rtk uv run --group dev pytest \
  packages/studyloop/tests/test_cli*.py \
  packages/studyloop/tests/test_study*.py \
  packages/studyloop/tests/test_setup_wizard.py \
  packages/studyloop/tests/test_learner_credentials.py \
  packages/studyloop/tests/test_session_state.py -q
# 195 passed, 54 deselected

rtk uv run mkdocs build --strict
# passed; existing Material/MkDocs compatibility, nav, and stale-link notices

rtk uv run --group dev pyright <changed Task 6 source files>
# 0 errors, 0 warnings, 0 informations
```

Targeted Ruff check/format, Python compilation, `git diff --check`, prompt wheel
build/resource inspection, and changed-file detect-secrets also pass. The
repository-wide detect-secrets invocation remains non-zero on pre-existing
baseline findings in unrelated fixtures, vendored JavaScript, manifests, and
historical documentation; the Task 6 changed-file scan is clean.

## Honest limitations and deferrals

- There is intentionally no OpenAI-compatible conversation client or durable
  attempt/turn store in this task. Model generation, recovery, replay, context
  freezing, and tool-result round trips belong to Task 7.
- `live certified` in Task 6 means that the packaged deterministic contract is
  healthy and the configured model appears in the fixed endpoint's `/models`
  response. It is not AP-LIVE-01 end-to-end conversation evidence and must not
  be presented as a public release gate by itself.
- This task does not make LAN Basic Auth learner-decision authority. Browser
  learner authentication, CSRF/origin binding, decision challenges, and human
  provenance relative to the confined runtime belong to Task 8.
- The browser still lacks the Task 9 dump/conversation/proposal/decision UX.
  Markdown and deterministic Mermaid primitives exist from earlier tasks, but
  Task 6 does not claim the onboarding or web planning journey is complete.
- External coding harnesses remain study-session integrations only. No ACP/MCP
  or harness route was added as a planning fallback.

## Scope boundary

No Task 7+ conversation, browser, learner-auth, evidence-stewardship, release-
manifest, or external-harness implementation was added. The progress ledger
was not edited.
