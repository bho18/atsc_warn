#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo 'Install uv 0.13.5, then rerun this script.' >&2; exit 1; }
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/warnbridge-uv}"
uv sync --frozen
