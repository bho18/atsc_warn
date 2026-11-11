# Development

Python 3.12+ on Linux; validated native interpreter 3.12.14. Use uv 0.13.5 and the
committed uv.lock. Initial installation needs package access; normal decoding,
replay, API, UI and tests do not need Internet after dependencies are installed.

```sh
python3.12 -m venv ~/.local/share/warnbridge-tools
~/.local/share/warnbridge-tools/bin/pip install uv==0.13.5
export PATH="$HOME/.local/share/warnbridge-tools/bin:$PATH"
./scripts/setup.sh
./scripts/validate.sh
```

Setup is idempotent; validation uses frozen offline dependencies and a disposable
output directory. If offline cache misses occur in a fresh environment, rerun setup
online once. To use an existing uv installation, omit the tool-venv steps. To make
a fresh machine fully offline, pre-provision the interpreter, uv, wheels/build
backend and lockfile packages, or use a prebuilt local image. No online fonts/maps.

```sh
.venv/bin/warnbridge --help
.venv/bin/warnbridge replay tests/fixtures/reconstructed.ts --config config/demo.toml
.venv/bin/warnbridge serve --config config/demo.toml
# In another terminal with the server running and Chromium installed:
.venv/bin/python scripts/browser_smoke.py --chromium /usr/bin/chromium
```

UI: http://127.0.0.1:8080. Browser smoke checks desktop/mobile inspection and blocks
all external requests. Screenshot output defaults to /tmp. Chromium is an optional
development dependency, not a runtime dependency. Playwright Python package is
locked in the dev group; no browser download runs in setup or core CI.

Linter/formatter: ruff. Strict source typing: mypy. Tests: pytest + FastAPI test
client + loopback sockets/subprocesses; no hardware or external endpoints. The
locked Starlette version emits an upstream HTTPX test-client deprecation warning;
it is not a failing application check and no warning suppression is applied.

Cloud specifics: default user cache was read-only, so setup uses
`UV_CACHE_DIR=/tmp/warnbridge-uv` unless overridden. Package network uses inherited
proxy/CA settings. Docker builds may need
`--secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt` for the managed proxy;
no session certificate is copied into the image. Documentation sites were blocked;
implementation never bypassed network restrictions.

`doctor` without `--receiver` does not create a DB or contact a device. Explicit
`--receiver` only reads status/target/lock, requiring configured host+tuner. Capture
additionally requires channel+return_ip. Syntax/IO/config failures exit 2; strict
import containing rejected data exits 1 after preserving diagnostics; success is 0.
Ctrl-C file processing exits 130. SIGINT/SIGTERM live capture requests orderly stop.
