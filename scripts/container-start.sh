#!/bin/sh
set -eu
if [ ! -e /data/warnbridge.db ]; then
    warnbridge replay /app/tests/fixtures/reconstructed.ts --config /app/config/container.toml
fi
exec warnbridge serve --config /app/config/container.toml
