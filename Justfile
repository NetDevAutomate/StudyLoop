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

release-check: test lint typecheck docs audit audit-full smoke-installed
