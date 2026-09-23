set shell := ["bash", "-cu"]

# PyMuPDF 1.27.2's SWIG extension emits one final Python 3.13 warning after
# pytest has torn down its own warning filters. Exact message only; all other
# deprecations remain visible. Remove when upstream swig/swig#2881 lands here.
export PYTHONWARNINGS := "ignore:builtin type swigvarlink has no __module__ attribute:DeprecationWarning"

default:
    @just --list

sync-dev:
    uv sync --all-packages --group dev

sync-full:
    uv sync --all-packages --group dev --all-extras

sync-web:
    uv sync --all-packages --group dev --extra web

sync-content:
    uv sync --all-packages --group dev --extra content

sync-semantic:
    uv sync --all-packages --group dev --extra semantic

test:
    uv run --group dev pytest

test-web:
    uv run --group dev pytest \
        packages/studyloop/tests/test_web_app.py \
        packages/studyloop/tests/test_web_content_gen_rest.py \
        packages/studyloop/tests/test_web_content_gen_ws.py \
        packages/studyloop/tests/test_web_content_providers.py \
        packages/studyloop/tests/test_web_secrets_route.py \
        packages/studyloop/tests/test_web_session_start_acp.py \
        packages/studyloop/tests/test_web_session_start_pty.py \
        packages/studyloop/tests/test_web_session_ws.py \
        packages/studyloop/tests/test_web_runtime_feedback.py

test-browser-smoke:
    uv run --group dev pytest packages/studyloop/tests/test_web_smoke_browser.py -m e2e -q

# The FULL browser suite (~500 tests, ~8 min). Until this target existed the
# only -m e2e invocation in this file was the single smoke file above, so the
# other 39 e2e files ran in no gate at all -- the same blind spot ci.yml already
# names for the browser-side unit tests.
#
# STUDYLOOP_E2E_TIMEOUT_SCALE is cleared rather than passed through, so this
# target is the release configuration BY CONSTRUCTION and cannot accidentally
# report a widened run as a gate result. To diagnose a flake on a loaded
# machine, call pytest directly with the variable set; the run then labels
# itself in both its header and its summary.

# Full browser e2e suite, unscaled (~8 min). Args narrow it: just e2e <file>
#
# One run per machine at a time. The suite binds fixed per-module ports and
# (until R-49 lands) writes the real session-state file, so two concurrent runs
# — two lane worktrees, or a lane and its verifier — refuse each other's ports
# ("port 18614 is already being served before the child started") and can
# clobber each other's session state. 51 such errors were seen on 2026-09-02.
# The lock is a directory (mkdir is atomic and portable; macOS has no flock(1));
# a lock whose recorded pid is no longer alive is treated as stale and removed.
e2e *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    lock=/tmp/studyloop-e2e.lock
    while ! mkdir "$lock" 2>/dev/null; do
        holder=$(cat "$lock/pid" 2>/dev/null || echo "")
        if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
            echo "e2e: removing stale lock left by dead pid $holder"; rm -rf "$lock"; continue
        fi
        echo "e2e: another e2e run holds $lock (pid ${holder:-unknown}); waiting 20s"; sleep 20
    done
    echo $$ > "$lock/pid"
    trap 'rm -rf "$lock"' EXIT
    STUDYLOOP_E2E_TIMEOUT_SCALE= uv run --group dev pytest -m e2e {{ARGS}}

# Browser-side unit tests. Pass the GLOB, not the directory — `node --test <dir>`
# discovers nothing here. The repo-local package.json declares the ESM type so
# Node does not walk up out of the repository looking for one.
test-js:
    node --test packages/studyloop/tests/js/*.test.js

test-content:
    uv run --group dev pytest \
        packages/studyloop/tests/test_content_cli.py \
        packages/studyloop/tests/test_content_generators.py \
        packages/studyloop/tests/test_content_generators_runner.py \
        packages/studyloop/tests/test_content_generators_stub.py \
        packages/studyloop/tests/test_content_job_runner.py \
        packages/studyloop/tests/test_content_scope.py \
        packages/studyloop/tests/test_content_storage.py \
        packages/studyloop/tests/test_content_storage_merge.py \
        packages/studyloop/tests/test_content_workflow.py

check-semantic-profile:
    uv run python scripts/check-semantic-profile.py

test-semantic:
    just check-semantic-profile
    uv run --group dev pytest \
        packages/agent-session-tools/tests/test_embeddings.py \
        packages/agent-session-tools/tests/test_embedding_schema.py \
        packages/agent-session-tools/tests/test_embedding_store.py \
        packages/agent-session-tools/tests/test_embedding_semantic_profile.py

# The `testacc` gate (AWS Terraform Provider `make testacc` analogy, owner's
# explicit reference): every acceptance test SKIPS with a clear reason unless
# STUDYLOOP_ACC=1, which this recipe sets. Args are POSITIONAL, not
# make-style KEY=value -- `just` has no such syntax; `just testacc HARNESS=x`
# would bind the literal string "HARNESS=x" as HARNESS's value, not set
# HARNESS to x (see test_acceptance_gate.py::TestJustRecipeArgumentSyntax and
# docs/acceptance-testing.md). Invoke positionally:
#   just testacc                                   # all harnesses, scripted actor
#   just testacc kiro                               # just kiro, scripted actor
#   just testacc kiro gateway                       # kiro, LiteLLM-backed learner
#   just testacc kiro scripted tests/acceptance/test_kiro_web_acp_lane.py
# HARNESS is a comma list (STUDYLOOP_ACC_HARNESS); empty means "all six" --
# the default the gate itself applies when the var is unset (O-7/D-23).
testacc HARNESS="" ACTOR="scripted" TESTS="packages/studyloop/tests/acceptance/":
    STUDYLOOP_ACC=1 STUDYLOOP_ACC_HARNESS="{{HARNESS}}" STUDYLOOP_ACC_ACTOR="{{ACTOR}}" \
        uv run --group dev pytest -m acceptance \
        --ignore=packages/studyloop/tests/acceptance/uat {{TESTS}}

# The UAT (sign-off) tier's OWN, additional opt-in on top of acceptance
# (council D-13): STUDYLOOP_UAT=1, set here, in ADDITION to STUDYLOOP_ACC=1 --
# `tests/acceptance/uat/conftest.py`'s gate requires both. Same positional-arg
# footgun as `testacc` applies (see docs/acceptance-testing.md); the mechanism
# tests this tier's modules ship (manifest schema, redaction, rubric loader,
# strict-runner semantics) are UNGATED and run under plain `just test` --
# this recipe only reaches the live-ish journey smoke test(s) under
# tests/acceptance/uat/ itself.
testuat HARNESS="" ACTOR="scripted" TESTS="packages/studyloop/tests/acceptance/uat/":
    STUDYLOOP_ACC=1 STUDYLOOP_UAT=1 STUDYLOOP_ACC_HARNESS="{{HARNESS}}" STUDYLOOP_ACC_ACTOR="{{ACTOR}}" \
        uv run --group dev pytest -m 'acceptance and uat' {{TESTS}}

lint:
    uv run --group dev ruff check .
    uv run --group dev ruff format --check .

shellcheck:
    shellcheck \
        scripts/install.sh \
        scripts/smoke-installed-cli.sh \
        scripts/build-release.sh \
        scripts/smoke-uv-tool-install.sh

typecheck:
    uv run --group dev pyright

docs:
    NO_MKDOCS_2_WARNING=1 uv run --extra docs mkdocs build --strict

# Structural validation of openspec/specs + openspec/changes.
# Skips (does not fail) when the openspec CLI is not installed.
spec-check:
    if command -v openspec >/dev/null 2>&1; then \
        openspec validate --specs --all; \
    else \
        echo "openspec CLI not found — skipping spec validation (see the OpenSpec section of docs/contributing.md)"; \
    fi

audit:
    uv --quiet export --all-packages --group dev --no-emit-workspace --format requirements-txt -o /tmp/studyloop-requirements.txt
    uv tool run pip-audit -r /tmp/studyloop-requirements.txt --strict --no-deps --disable-pip

audit-full:
    uv --quiet export --all-packages --group dev --all-extras --no-emit-workspace --format requirements-txt -o /tmp/studyloop-requirements-full.txt
    # Torch has no fixed release for PYSEC-2026-139 yet; keep the ignore explicit.
    uv tool run pip-audit -r /tmp/studyloop-requirements-full.txt --strict --no-deps --disable-pip --ignore-vuln PYSEC-2026-139

smoke-installed:
    ./scripts/build-release.sh
    tmp="$(mktemp -d)" && uv venv "$tmp/venv" && uv pip install --python "$tmp/venv/bin/python" dist/studyloop-*.whl packages/agent-session-tools && STUDYLOOP_EXPECT_BIN_DIR="$tmp/venv/bin" PATH="$tmp/venv/bin:$PATH" ./scripts/smoke-installed-cli.sh

# W28: the real global `uv tool install` path -- what a fresh checkout's
# ./scripts/install.sh actually runs -- was shellcheck-only (see `shellcheck`
# above); a live UV_PYTHON interpreter-mismatch bug report implicated exactly
# this path having zero execution coverage. Runs both `uv tool install`
# invocations for real into a scratch UV_TOOL_BIN_DIR and smokes the result.
smoke-uv-tool-install:
    ./scripts/smoke-uv-tool-install.sh

# R-29: every extra studyloop's wheel advertises (content, bedrock, notebooklm,
# tui, web, mcp, all) must install and import from a BARE wheel -- no
# workspace, no --with-editable, no sibling package on disk. Also asserts
# `sessions` is not advertised at all, since agent-session-tools cannot
# resolve outside this repo's uv workspace. See test_wheel_extras_smoke.py.
smoke-extras:
    uv run --group dev pytest packages/studyloop/tests/test_wheel_extras_smoke.py -m integration -q

# The installed-wheel WEB smoke (second-brain launcher release evidence): build
# the wheel, install studyloop[web] into an isolated venv outside the checkout,
# start the installed app, request /api/second-brain/launch-target, and load
# every launcher asset main.js's import graph reaches. Release-only, not
# preflight: it pays for a wheel build plus a server start every run, and
# package regressions are otherwise invisible to source-checkout tests.
smoke-web:
    uv run --group dev pytest packages/studyloop/tests/test_wheel_web_smoke.py -m integration -q

build-release:
    ./scripts/build-release.sh

# WD-5/WD-6: the live wind-down gate checks, captured through Claude Code
# headless against the LiteLLM gateway (no vendor credential; the key is read
# from the proxy's own config at runtime). Opt-in — burns gateway spend
# (estimate: reviews/2026-09-04-gate-checks/ESTIMATE.md). Writes transcripts
# and the pass/fail summary under reviews/…/evidence/gate-checks/.
gate-checks:
    STUDYLOOP_EVIDENCE_DIR={{justfile_directory()}}/reviews/2026-09-04-gate-checks/evidence/gate-checks \
        uv run --group dev pytest packages/studyloop/tests/live/test_wind_down_transcripts.py -m live_provider -q

release-consistency:
    uv run python scripts/check-release-consistency.py --skip-wheel

# The release-mode superset: everything above PLUS the openspec guards — a
# change with commits since the last tag must be archived or carry a
# `deferred: <reason>`, and archive entries ADDED since the last tag must pass
# `openspec validate` (soft-skipped when the CLI is absent, same convention as
# spec-check; not `--archived --all`, so that a historical archive nobody is
# working on can never re-fail a future release and teach people to ignore
# the gate — the July archive that motivated this was reconciled against the
# tree on 2026-09-23 and `--archived --all` is green today).
# Deliberately NOT part of preflight: open changes are legal during a cycle;
# only shipping one is not. Both guards would have fired on the 0.2.0 cut
# (2026-09-04 review, Q5).
# Pre-tag form: everything --release checks EXCEPT the git-tag/CHANGELOG-date
# assertion, which cannot hold before the tag this gate precedes exists. It
# prints the tag still to be cut.
release-consistency-shipped:
    uv run python scripts/check-release-consistency.py --skip-wheel --release --pre-tag

# Strict form, run AFTER `git tag vX.Y.Z`: the tag must exist and the CHANGELOG
# heading for the version must not predate the tag's commit.
release-verify:
    uv run python scripts/check-release-consistency.py --skip-wheel --release

prepare-release version:
    uv run python scripts/prepare-release.py {{version}}

# The user-representative journeys: the real CLI driven through a learner's week in
# a hermetic world. Default-on (they run in `just test`), so this recipe is only for
# running them alone while iterating.
journeys:
    uv run --group dev pytest packages/studyloop/tests/journeys/ -v

# Publishable pictures of the notes StudyLoop writes. Rendered for reading and
# labelled in their own pixels as NOT being Obsidian -- see the script's docstring
# for why a screenshot of the app itself is a separate, opt-in thing.
vault-screenshots out:
    uv run python scripts/capture-vault-screenshots.py --out {{out}}

# The two opt-in second-brain checks against real products. Neither runs in
# `preflight`, `release-check` or CI: one writes into a real Obsidian vault, the
# other signs in to a real xTiles account. Both refuse to run without an explicit
# opt-in, and both are deselected by default in BOTH pyproject files.
live-obsidian:
    STUDYLOOP_LIVE_OBSIDIAN=1 \
    STUDYLOOP_LIVE_OBSIDIAN_VAULT=StudyLoop-Live-Test \
    STUDYLOOP_LIVE_OBSIDIAN_VAULT_PATH=~/Obsidian/StudyLoop-Live-Test \
    uv run --group dev pytest -m live_obsidian -v

# Needs a session captured once (`just xtiles-auth`) and the URL your assistant
# returned. PROBE is the distinctive title prefix the assistant was told to use --
# every assertion is scoped to it, and a short one is refused.
live-xtiles url probe:
    STUDYLOOP_LIVE_XTILES=1 \
    STUDYLOOP_LIVE_XTILES_URL="{{url}}" \
    STUDYLOOP_LIVE_XTILES_PROBE="{{probe}}" \
    uv run --group dev pytest -m live_xtiles -v

# One-time, needs a real window: xtiles.app sign-in is behind reCAPTCHA, so a
# headless password login cannot pass it (evidence: reviews/2026-09-03-second-brain
# /evidence/m8/xtiles-live/00-why-a-captured-session.md).
xtiles-auth:
    uv run python scripts/xtiles-live-auth.py

preflight: lint typecheck test test-js docs release-consistency spec-check

release-check: test test-js lint typecheck shellcheck docs audit audit-full release-consistency-shipped smoke-installed smoke-uv-tool-install smoke-extras smoke-web

# "Would GitHub Actions pass?" locally, before pushing. `check` runs the
# host-answerable gates (lint, typecheck, test, sast, audit, docs, ...); `lint`
# via run-job then proves the container path itself works, since ci-standards
# needs `ci-standards-runner:latest` built once (see
# ~/code/personal/tools/github_ci_pipeline/README.md) for anything
# platform-sensitive. This pair is the fast, cheap confidence check -- run
# `ci-standards run-job e2e --target . --image ci-standards-runner:latest`
# separately for the platform-sensitive browser suite (15+ minutes).
ci-local:
    ci-standards check --target .
    ci-standards run-job lint --target . --image ci-standards-runner:latest
