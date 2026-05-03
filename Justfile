set shell := ["bash", "-cu"]

default:
    @just --list

test:
    uv run --group dev pytest

lint:
    uv run --group dev ruff check .

typecheck:
    uv run --group dev pyright

docs:
    uv run --extra docs mkdocs build --strict

build-release:
    ./scripts/build-release.sh

release-check: test lint typecheck docs build-release
