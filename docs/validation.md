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

## Alert inbox and live heartbeat follow-up — November 12, 2026 UTC

The UI now opens on live alert content and keeps heartbeat/Link Test traffic in
Diagnostics. CAP has readable multilingual text, instructions, parameters and
separate areas with offline coordinate plots. Non-Link-Test CMAC has an explicitly
experimental original-field review. Existing preserved trees are projected at read
time; schema remains version 2 and original evidence is unchanged. CAP lifecycle
labels describe declared timing/references, with same-source/sender/time and
conflict guards. Replay cannot cancel live data or refresh the connection pulse.

Manufacturer manual, OASIS CAP and FEMA IDG text were successfully inspected with
the connected web research tool; initial direct proxy failures remain historical.
See sources.md for versions/sections and the current CMAC-schema limitation.

Executed `./scripts/setup.sh` and `./scripts/validate.sh`: **129 tests passed**,
Ruff lint/format passed, strict mypy passed for 21 source files. The existing
upstream Starlette HTTPX test-client deprecation warning remains. Reconstructed
replay still yields 4 packets / 2 messages / 2 CRC passes, no losses/rejections.

New checks exercise transport-to-API alert ingestion, default live-only inbox,
status/source filters and pagination, exact bytes, multilingual/repeated fields,
leading-zero geocodes, CAP-to-GeoJSON coordinate order, circle kilometres,
invalid/unclosed/nonfinite geometry, missing/invalid dates, scheduled/expired/
non-Actual/Cancel/Ack/Error presentation, out-of-order references, foreign/test/
replay cancellation exclusion, conflicting identities and ambiguous latest
references. Live heartbeat checks cover stale, stopped, fresh and restarted
sessions, excluding untimed imports and replay with retained timestamps.

The deterministic alert-demo.ts fixture replays **65 TS packets / 7 messages /
7 CRC passes**, six CAP and one synthetic CMAC field-review example, with zero
continuity gaps, incomplete messages or rejections. It is 12,220 bytes and contains
fixed-date DEMO ONLY examples; its CRCs are computed test data, not independent
protocol evidence. Default live inbox remains empty when only this demo is imported.

Both browser commands passed against a disposable synthetic database on loopback
port 8087, desktop 1400×1100 and mobile 390×844:

```sh
.venv/bin/python scripts/browser_alerts_smoke.py --url http://127.0.0.1:8087 \
  --screenshot /tmp/warnbridge-alerts.png
.venv/bin/python scripts/browser_smoke.py --url http://127.0.0.1:8087 \
  --check-rf --check-cap --screenshot /tmp/warnbridge-alert-diagnostics.png
```

Verified empty live inbox vs replay cards, explicit Test/Replay labels, language
switching, parameters/geocodes, polygon/circle plots, CMAC unknown fields, dynamic
inspector lifecycle refresh without resetting language, and retained delivery
paging/filtering. Heartbeat pulses on a new live observation ID, not a repeated
health poll; stale age advances between polls, stopped/API failure removes green
state, and reduced-motion preference suppresses animation. Hostile CAP text is
inert in cards, readable detail and raw evidence. No external requests, inserted
scripts, unexpected dialogs, layout overflow or JavaScript errors occurred. An
initial browser assertion using unsafe-eval was replaced with DOM assertions;
application CSP was not relaxed.

`UV_CACHE_DIR=/tmp/warnbridge-uv uv build --offline --wheel --out-dir
/tmp/warnbridge-alert-wheel` succeeded. The wheel contains the alert domain,
offline assets and both SQL migrations. The initial build attempt used the
read-only default uv cache and failed; explicitly choosing the existing writable
cache resolved it. No runtime dependencies were added. Container rebuild/remote
CI were not rerun for this change; previously recorded container checks are history.

No cloud process accessed the home LAN, tuned hardware, captured a real alert or
published a warning. Actual OTA alert/schema/trust acceptance and current CMAC
normalization remain pending; synthetic presentation checks do not establish them.

## Leaflet alert maps — November 12, 2026 UTC

Replaced the coordinate plot with Leaflet 1.9.4, locally vendored under BSD-2-Clause.
Bundled Natural Earth reference geography is public domain, with pinned inputs,
original license and source/output hash manifests. The default map needs no external
requests. Optional OSM street tiles load only on selection; tile failure restores
reference geography. Alert geometry/evidence and schema version 2 are unchanged.

Executed `./scripts/setup.sh` and `./scripts/validate.sh`: **129 tests passed**, Ruff
lint/format passed (43 Python files), strict mypy passed for 21 source files, and
reconstructed replay remained 4 packets / 2 messages / 2 CRC passes. The existing
upstream Starlette HTTPX test-client deprecation warning remains. No Python/Node
runtime dependency was added; the verified browser distribution is bundled.

Executed all three browser scripts against the disposable synthetic database at
loopback 8087:

```sh
.venv/bin/python scripts/browser_maps_smoke.py --url http://127.0.0.1:8087 \
  --screenshot /tmp/warnbridge-map.png
.venv/bin/python scripts/browser_alerts_smoke.py --url http://127.0.0.1:8087 \
  --screenshot /tmp/warnbridge-alerts-map.png
.venv/bin/python scripts/browser_smoke.py --url http://127.0.0.1:8087 \
  --check-rf --check-cap --screenshot /tmp/warnbridge-map-diagnostics.png
```

Desktop/mobile map checks passed for offline geography/labels, two supplied alert
shapes, scale/zoom/pan, fit, safe circle details and attribution, language replacement
and repeated cleanup, resize, antimeridian and polar geometry, and missing-reference
asset recovery. Street-tile success and failure were simulated by local route
responses; no real public tile requests were sent. Tile failure returns to offline
reference; no external requests occur before explicit selection. Malicious area
text stays literal in Leaflet popups, with no injected image or script/dialog.
No unexpected JavaScript or CSP console errors occurred. Expected browser errors
from intentionally aborted tile requests are filtered only in the failure case.

The map test initially compared multiline rendered scale text to DOM text and was
corrected to assert the metric scale line. A second initial failure used already
decoded tile images, so the failure check now changes zoom before blocking new
requests; the failed tile path and fallback are actually exercised. No application
CSP was weakened to run tests. Scripts/connect remain same-origin; image CSP permits
only self/data and the fixed optional OSM tile host.

Built `UV_CACHE_DIR=/tmp/warnbridge-uv uv build --offline --wheel --out-dir
/tmp/warnbridge-map-wheel`. Wheel inspection verified engine/CSS/images, map data,
licenses and all vendored file/output hashes. An extracted-wheel replay/API test
used the packaged code (not the editable checkout), processed seven synthetic alerts
with seven CRC passes, kept the default live inbox empty, served map assets/licenses
and checked strict CSP. A local screenshot contains only labeled synthetic alert
content. The temporary native server was stopped after testing.

Map rendering/packaging is verified with synthetic coordinates and local basemap
data. Real OTA alert/CMAC geography acceptance, current CMAC mapping/schema,
authenticity and production tile-provider availability remain unverified. No new
hardware/network configuration, container publication or external notification was
performed. See maps.md for dependency/data licensing and provider behavior.

## ThinkCentre live Docker and internal access — November 11, 2026 (America/Chicago)

Added `compose.live.yaml`, separate from the existing replay demo. Receiver and web
run as unprivileged, read-only containers on Linux host networking, with a shared
persistent archive and read-only local TOML. Generated settings bind the web/UDP
sockets to the host LAN IPv4, constrain HTTP clients to selected internal subnets,
and leave raw/full-multiplex recording off. The setup helper reads local iproute2
JSON only; no receiver query or probe is sent. Existing config is never overwritten.

The Docker image now includes Debian trixie's hdhomerun-config `20230719-1+b4`.
Its short usage output omits keyed commands, so Debian's source was inspected to
confirm main_cmd accepts the existing key-before-get/set adapter syntax. No native
hardware command/discovery/tuning was run in cloud. Binary presence/UID/package
were inspected with Docker networking disabled; usage exits 1 as expected.

Executed `./scripts/setup.sh` and `./scripts/validate.sh`: **151 tests passed**, Ruff
lint/format passed for 48 Python files, strict mypy passed for 21 source files.
Reconstructed replay remains 4 packets / 2 messages / 2 CRC passes, no rejections
or continuity failures. The existing upstream Starlette HTTPX warning remains.
New tests cover route-only LAN detection, explicit/configured host IP checks,
refusal of public/wildcard/bridge binds and public/ambiguous CIDRs, no config
replacement, TOML live settings, all-route allow/deny checks, IPv4-mapped peers,
invalid networks, and ignoring spoofed forwarding headers. `warnbridge serve`
disables Uvicorn's proxy-header interpretation so decisions use socket peers.

The managed local Docker daemon was selected explicitly with inherited endpoint,
context and TLS selectors removed (credentials/config preserved). Built locally:

```sh
docker --host=unix:///var/run/docker.sock build \
  --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -t warnbridge:live-local .
```

Both Compose files pass `config --quiet`; CI now checks both. The optional
`.venv/bin/python -m scripts.container_live_smoke` passed with a uniquely named test
project and synthetic volume. It replaces live tuner control with raw loopback
UDP; no real device IP is contacted. Actual containers verified:

- UID/GID 10001:10001, capabilities dropped, no-new-privileges, read-only root and
  config mount, host network, no published Docker ports or Docker socket mount.
- A mixed non-WARN/WARN loopback datagram produces exactly one heartbeat delivery
  and recent connection state; no raw capture directory is created.
- Actual TCP source 127.0.0.2 is denied even with a trusted-looking X-Forwarded-For;
  permitted 127.0.0.1 remains allowed with an untrusted-looking forwarded address.
  Static maps and APIs follow the same policy.
- Both custom container health checks become healthy from local API/database state.
- The web process restarts without reimporting/deleting data. Receiver SIGTERM
  finishes the session and health becomes stopped. No tracebacks appear in logs.

The test cleans up only its own newly created containers/volume; the pre-existing
loopback replay demo is untouched. No image was published. The live stack has not
been deployed on the user's ThinkCentre from cloud; physical HDHomeRun firmware,
routing/firewall and owned-tuner release still require the supplied local preflight
and acceptance. Host address detection is mock-tested; the real address is read
when the user runs setup on homeserver, never inferred from the laptop's old IP.
The application has no login system; keep public reverse proxies/port forwarding
away from this internal stack. See docker-live.md for limits, migration and updates.

## Pull-based installation and image publishing

Added compose.deploy.yaml with a GHCR image reference and no build context, plus a
configuration-helper option for a downloaded compose.yaml. The fresh-install path
uses an empty directory, two downloaded files and Docker image pulls; no source
checkout, venv or local build is required. Updates preserve config/data and use
pull/up. Source-build compose.live.yaml remains available for development.

Executed the full frozen offline validation: **152 tests passed**, Ruff lint/format
passed (48 Python files), mypy passed (21 source files), and reconstructed replay
still yielded 4 packets / 2 messages / 2 CRC passes. The added regression verifies
the fresh-install helper prints image pull/start commands and the detected LAN URL,
without a build step. All three Compose configurations validate.

The publishing workflow gates Linux AMD64 image publication on those checks, uses
repository-scoped package-write permissions, pins actions, tags source revisions,
reuses existing SHA-tagged digests on reruns and promotes the current source head
to edge. Registry publication, first-package visibility and pull verification are
recorded after executing the workflow; a configured workflow alone is not a claim
that an image exists or is anonymously accessible.


Actual registry publication and installation acceptance:

- Publishing run https://github.com/bho18/atsc_warn/actions/runs/43227742882
  completed validation, image build/push and edge promotion successfully for
  source `996228a4481a2961e1890ef63d106fa718c435ab`.
- Both `ghcr.io/bho18/warnbridge:edge` and
  `ghcr.io/bho18/warnbridge:sha-996228a4481a2961e1890ef63d106fa718c435ab`
  returned HTTP 200 through anonymous GHCR tokens. Manifest bytes independently
  hash to `sha256:72e39a5b57089a83d97363e980398d10db667968c0e490d7875e4a1cbdb3f298`,
  matching the registry digest header and the publishing job output.
- An actual Docker pull of edge downloaded all layers and verified that digest.
  Image inspection confirms Linux AMD64, UID 10001:10001 and the expected source
  revision label. The public package page also returns HTTP 200; no manual package
  visibility switch or registry login is required for installation.
- The exact two raw deployment/helper download URLs return HTTP 200 and match the
  checked source files. No Git clone/local image build is part of the host path.
- `python -m scripts.container_live_smoke --deployment --image
  ghcr.io/bho18/warnbridge:edge` starts the pulled image with Compose copied into an
  empty temporary directory. It verifies there is no build context, then repeats
  loopback reception, private-peer restrictions, map assets, health, persistence,
  non-root/read-only isolation and graceful stop checks. All passed. The test uses
  synthetic raw UDP and never contacts the physical receiver.

The user explicitly requested pullable images and image updates, authorizing this
GHCR publication. No private captures, runtime configuration or credentials were
published. The host still needs to run the supplied installation commands; cloud
acceptance does not claim an installation on the ThinkCentre or physical reception.

## Deployment documentation contract

Documented the user-confirmed image-only ThinkCentre installation/update workflow
as standing instructions in AGENTS.md. README now leads with Docker deployment;
the general deployment, UI upgrade, development and native receiver guides clearly
separate normal image pulls from optional source/native/replay workflows. The
contract records the fresh-host assumption, public GHCR image, target-host LAN
detection, internal bind/allowlist, publication checks, persistent config/volume,
Compose-file refresh and pull/up updates. Original request and historical evidence
were preserved. No runtime code or container configuration changed in this pass.

Executed setup and the full validation script: 152 tests passed, Ruff lint/format
and mypy passed, reconstructed replay remained 4 packets / 2 messages / 2 CRC passes.
Existing integration tests include replay-to-API checks. All 22 local Markdown
links in the changed guides resolved, and git diff --check passed. The existing
upstream Starlette HTTPX test-client warning remains.
