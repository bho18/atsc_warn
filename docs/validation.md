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

## Live receiver workflow follow-up — November 11, 2026 (America/Chicago)

The user approved public source delivery and requested native discovery/direct IP,
automatic idle tuner selection, physical channel selection, and live decoding without
continuous transport recording. The initial public-repository blocker recorded
above is superseded by that authorization.

Implemented `discover` and `listen` CLI workflows; `capture` remains an alias.
Native CLI discovery, bounded local HTTP device metadata, tuner inventory, busy/raced
tuner fallback, explicit selection, return-IP routing/override, immediate JSONL
message output and a no-UDP warning are covered by mock/loopback tests. Raw arrival
journals are now opt-in; non-WARN packets are discarded and do not enter the DB.

Executed `./scripts/validate.sh`: **87 tests passed**, Ruff lint/format passed, mypy
passed for 18 source files, and the original reconstructed replay still produced
4 packets / 2 complete messages / 2 CRC passes. One upstream Starlette HTTPX
test-client deprecation warning remains. No new runtime dependencies were added.

The live integration test emulates native tuner control, pushes mixed non-WARN and
WARN packets over a real loopback UDP socket, verifies immediate decoded output,
checks the selected channel/PID filter and release, and proves only the 188-byte
WARN packet was retained with no raw journal directory. Another subprocess test
verifies actual SIGTERM shutdown. Separate tests cover opt-in journals, direct IP
without broadcast, native discovery duplicates/ambiguity, metadata limits/redirect
refusal, busy/lock acquisition races, current channel inspection, config overrides,
and a persisted actionable WSL no-data warning.

Physical HDHomeRun discovery/control/firmware behavior and actual WSL networking
remain unverified: the cloud has not contacted the user's LAN. No schema, signature
or real-capture acceptance claim has changed. See live-receiver.md for the exact
local commands. Manufacturer HTTP API documentation re-fetch was blocked by proxy
CONNECT 403; the adapter's metadata contract is tested with mocks only.

## Native video keepalive correction

User-reported mirrored WSL reception still had no incoming UDP after the proposed
source-scoped firewall allowance. Code was compared with pinned official SiliconDust
source; its native video client sends a four-byte big-endian owned key to device UDP
5004, from its bound video socket, immediately and every 1000 ms. This step was
missing from WarnBridge and is now implemented for owned HDHomeRun live inputs.
No additional firewall, VLAN, firmware, receiver or Windows change was executed.

Executed `./scripts/validate.sh`: **91 tests passed**; Ruff lint/format and strict
mypy passed for 18 source files; reconstructed replay remained 4 packets, 2 messages,
2 CRC passes and no rejected/incomplete messages. The existing upstream Starlette
HTTPX test-client deprecation warning remains. No dependencies or migrations changed.

New regression coverage checks the independently specified synthetic key 0x12345678
becomes exactly bytes 12 34 56 78, the correct destination and receiving socket,
periodic transmission during idle time, and refusal before/after ownership. A real
loopback UDP peer withholds its heartbeat until two valid keepalives arrive from
the bound receive port. The CLI then decodes the heartbeat, keeps the private token
out of output/raw journals, and releases its tuner. Another test forces send failure
and verifies target/channel/lock cleanup plus a failed persistent receiver session.

These are source-conformance and mock/loopback tests, not proof that this resolves
the user's actual WSL/VLAN routing. A hardware retry should inspect outbound UDP
5000→5004 and inbound TS; sending a UDP datagram cannot prove the receiver got it.

## User-supplied live acceptance logs

The user provided output from `b61a689` showing successful direct-IP, RF 7, HDHR5-2US
reception in mirrored WSL. Analysis of complete records found 20 transport-valid
message deliveries (7 heartbeats, 13 System/Link Tests), 6 distinct content IDs and
15 archive-duplicate flags. Base64 body, XML view and SHA-256 identity consistency
checks all passed for those records. This is a check of decoded output, not an
independent CRC calculation on raw TS evidence.

The separately supplied packet-header trace shows 76 outgoing four-byte keepalives
and 17 incoming 1316-byte UDP datagrams. Run/excerpt time windows differ. One terminal
JSON line is truncated and no final decoder summary is provided; full-run packet,
continuity, CRC-failure and shutdown counters are unknown. No supplied raw logs or
message payloads were added to Git. See evidence.md for provenance and limitations.

This establishes user-verified live reception with the keepalive patch and the
previously authorized firewall exception. It does not establish that either change
alone was sufficient, certify public-warning delivery, validate signatures/schemas,
or replace the pending original 56-packet-file acceptance test.

## RF status and delivery-history UI correction

The RF card previously stayed not_checked because health returned a constant and
frontend refresh never populated it. A dedicated read-only status worker now polls
while the tuner is owned. Its bounded queue is drained by the ingestion thread;
SQLite remains confined to that thread, and slow control reads cannot block UDP
keepalives. Persisted RF samples have lock/no-lock, stale, unavailable and stopped
states. Schema 002 adds latest per-session samples and an observation index; schema-1
messages/observations/raw evidence are preserved in place.

The UI defaults to individual Deliveries and separately offers Unique content. It
shows XML sent time, reception/processing time, source-filtered counts, latest receipt
ordering and paginated history. Identical heartbeat content remains a single content
record underneath, with each delivery individually accessible. Archive-wide repeat
markers and source-scoped counts have distinct semantics documented in ui-monitoring.md.
New GET /api/v1/deliveries pagination exposes histories beyond the legacy detail
response's 100-observation cap. The RF display becomes unavailable on API disconnection;
requests have bounded timeouts and automatic refresh avoids overlapping requests.

Executed `./scripts/validate.sh`: **98 tests passed**, Ruff lint/format passed,
strict mypy passed for 19 source files, and replay still produced 4 packets / 2
complete messages / 2 CRC passes. The upstream Starlette HTTPX test-client warning
remains. New tests cover RF refresh/error/stop behavior, stale samples after process
loss, slow RF polling while keepalives continue, actual listener-to-DB status wiring,
source-filtered 35-live/1-replay heartbeat counts, 125 deliveries under one content
ID, paginated access past 100 observations, and raw-part ownership restrictions.
Migration testing reopens a version-1 schema and compares retained original bytes.

`uv build --offline --wheel --out-dir /tmp/warnbridge-ui-v2-wheel` succeeded; wheel
inspection confirmed both SQL migrations, the RF worker and updated web assets.
Native browser server used a disposable synthetic database at loopback port 8087.
Executed both standard browser smoke and:

```sh
.venv/bin/python scripts/browser_smoke.py --url http://127.0.0.1:8087 \
  --check-rf --check-cap --screenshot /tmp/warnbridge-ui-v2.png
```

Desktop 1400x1100 and mobile 390x844 passed with no external requests or unexpected
JS/API errors. Mocked health replies exercised locked -> stale -> unavailable ->
stopped, API connection loss and recovery. The synthetic archive exercised grouped
content, per-delivery rows, source filtering and delivery-history paging. Hostile
CAP text remained inert. Final native server logs contained no errors/tracebacks.
No new physical RF polling or Windows configuration change was executed in cloud.
Users must restart both processes for schema 2 and ongoing RF sampling.
