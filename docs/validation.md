# Validation record

Executed in the managed Linux AMD64 cloud workspace on November 10, 2026
America/Chicago (November 11 UTC). No real receiver or original private capture
was available. All tests used reconstructed/synthetic data, mocked device control,
loopback sockets, local browsers and locally built containers.

## Python checks

Native Python 3.12.14, SQLite 3.53.1, uv 0.13.5. Locked runtime dependencies include
FastAPI 0.162.4, Starlette 1.10.0, Uvicorn 0.54.0, DefusedXML 0.7.1 and Pydantic
2.14.3. See uv.lock for exact versions/hashes of all packages. Build backend
hatchling 1.27.0. Strict mypy, Ruff lint/format, pytest 9.2.0.

Commands executed successfully:

```sh
./scripts/setup.sh
./scripts/validate.sh
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/mypy src
.venv/bin/pytest -q
```

**71 tests passed**, including independent CRC vectors, chunk boundaries, continuity
wrap/adaptation-only/discontinuity rules, loss/collision/CRC/header rejection,
resource bounds, XML attacks/encoding/multiple structures, protocol identities,
reference resolution/conflicts/expiration, exact bytes, file reception unknown,
SQLite persistence/migration/restart/exclusion, read-only/concurrent API behavior,
UDP datagram length/RTP rejection, graceful SIGTERM, journal rotation/replay,
owned tuner races/cleanup/timeout handling and saved-web-response separation.
One upstream Starlette HTTPX test-client deprecation warning remains; no test failure.

Final reconstructed replay result:

```json
{"warn_packets":4,"complete_messages":2,"crc_pass":2,"crc_fail":0,
 "heartbeats":1,"cmac_messages":1,"cap_messages":0,"link_tests":1,
 "duplicate_xml":0,"unique_xml":1,"continuity_gaps":0,
 "duplicate_ts_packets":0,"rejected_packets":0,"rejected_messages":0,
 "incomplete_messages":0}
```

Fixture `tests/fixtures/reconstructed.ts`: 752 bytes, SHA-256
`9221f24749f827854cc6d953063751049c7f4a8c2ead61c1d17082e88029c3ac`.
This hash identifies only the intentionally reconstructed four-packet fixture.

## Browser and container

Chromium via locked Playwright, desktop 1400×1100 and mobile 390×844. The browser
smoke script checks message inspection, validation states, layout width, local
requests, and JS errors. Optional --check-cap displays the synthetic escaped
script headline as text and asserts no inserted script/dialog. CSP remains strict;
the test uses locator assertions instead of string evaluation blocked by CSP.
Screenshots are transient validation artifacts under /tmp, not runtime inputs.

Container built locally with:

```sh
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt -t warnbridge:local .
docker compose -p warnbridge-validation config --quiet
docker compose -p warnbridge-validation up -d --no-build --wait --wait-timeout 40
docker run --rm --network none --read-only --tmpfs /data:uid=10001,gid=10001 \
  warnbridge:local decode /app/tests/fixtures/reconstructed.ts --out /data/offline
```

The managed local daemon was explicitly selected via /var/run/docker.sock with
inherited Docker endpoint/context/TLS selectors cleared. BuildKit received the
proxy CA as an ephemeral secret; no CA/credential was baked into the image.
Base image pinned at manifest digest
`sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`
(Python 3.12.16). Image is local only; no publication.

Verified healthy non-root UID/GID 10001:10001, read-only root filesystem, persistent
volume, and successful golden decode with Docker network disabled. Concurrent
container API probe: 32/32 requests successful, two messages each. Runtime logs
checked for exceptions after the final fixes. Two issues found by actual runtime
checks were fixed: request-thread handoffs for read-only SQLite connections, and
explicit container file/directory permissions under the workspace's restrictive
umask. Concurrent API regression coverage is included.

## Not verified / not claimed

- **Real-capture validation pending; user previously reported successful validation
  with the experimental decoder.** The 56-packet counts are provenance, not this
  delivery's executed acceptance result.
- HDHR5-2US hardware, firmware 20261107, RF 7, real tuner/lock cleanup and VLAN UDP.
- Production alert/native CAP OTA coverage, normative transport/schema conformance,
  CMAC lifecycle rules, signatures/trust, geographic relevance or web completeness.
- Blocked manufacturer/OASIS/FEMA/ATIS pages, live web contract/operator policy.
- GitHub CI execution or remote PR: repository is public, so nothing was pushed.

See deployment.md for exact private-capture acceptance and safe local receiver
preflight, and sources.md for retrieval outcomes and repository privacy blocker.

## Fresh-checkout and final runtime acceptance

The source implementation was committed locally as `8c729c06c9174e52221e2bc6b5a54dc48c5289f6`
on `codex/warnbridge-initial`. A complete-history Git bundle was created and
verified, cloned into `/tmp/warnbridge-fresh`, then tested with:

```sh
git bundle verify /workspace/warnbridge-initial.bundle
git clone /workspace/warnbridge-initial.bundle /tmp/warnbridge-fresh
cd /tmp/warnbridge-fresh
./scripts/setup.sh
./scripts/validate.sh
```

Fresh checkout: **71 passed**, Ruff lint/format passed, mypy passed for 17 source
files, reconstructed replay summary matched the four-packet result above. Setup
used the shared package cache but a newly created checkout/venv; validation ran
with frozen offline dependencies. This verifies no uncommitted fixture or existing
application database is needed; it is not a claim of package installation on a
completely offline unprovisioned machine.

Final browser commands both passed:

```sh
.venv/bin/python scripts/browser_smoke.py --url http://127.0.0.1:8081 \
  --check-cap --screenshot /tmp/warnbridge-xss.png
.venv/bin/python scripts/browser_smoke.py
```

Port 8081 was a temporary native server containing only synthetic browser fixtures;
it was stopped after verification. Port 8080 served the Compose demo. Both browser
runs had zero external requests/JS errors. The hostile CAP headline rendered as
text, without a script node or dialog. After container restart, health was healthy
and metrics remained two messages/two observations: the demo was not re-imported.
Final container and native test-server logs contained no errors/tracebacks.

A subsequent documentation-only commit records these results. The final bundle
includes that commit and the unchanged validated implementation. No remote push,
PR, live endpoint polling, physical receiver test, or original-capture test occurred.
