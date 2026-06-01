set shell := ["bash", "-cu"]

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
        packages/agent-session-tools/tests/test_semantic_search.py

lint:
    uv run --group dev ruff check .
    uv run --group dev ruff format --check .

typecheck:
    uv run --group dev pyright

docs:
    uv run --extra docs mkdocs build --strict

audit:
    uv --quiet export --all-packages --group dev --no-emit-workspace --format requirements-txt -o /tmp/studyloop-requirements.txt
    uv tool run pip-audit -r /tmp/studyloop-requirements.txt --strict --no-deps --disable-pip

audit-full:
    uv --quiet export --all-packages --group dev --all-extras --no-emit-workspace --format requirements-txt -o /tmp/studyloop-requirements-full.txt
    # Torch has no fixed release for PYSEC-2026-139 yet; keep the ignore explicit.
    uv tool run pip-audit -r /tmp/studyloop-requirements-full.txt --strict --no-deps --disable-pip --ignore-vuln PYSEC-2026-139

smoke-installed:
    ./scripts/build-release.sh
    tmp="$(mktemp -d)" && uv venv "$tmp/venv" && uv pip install --python "$tmp/venv/bin/python" dist/studyloop-*.whl && PATH="$tmp/venv/bin:$PATH" ./scripts/smoke-installed-cli.sh

build-release:
    ./scripts/build-release.sh

release-consistency:
    uv run python scripts/check-release-consistency.py --skip-wheel

release-check: test lint typecheck docs audit audit-full release-consistency smoke-installed
