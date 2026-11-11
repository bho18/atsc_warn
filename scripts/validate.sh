#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/warnbridge-uv}"
uv sync --frozen --offline
uv run --frozen --offline ruff check src tests scripts
uv run --frozen --offline ruff format --check src tests scripts
uv run --frozen --offline mypy src
uv run --frozen --offline pytest -q
warnbridge_validation_dir="$(mktemp -d)"
trap 'rm -rf "$warnbridge_validation_dir"' EXIT
uv run --frozen --offline warnbridge replay tests/fixtures/reconstructed.ts --out "$warnbridge_validation_dir"
