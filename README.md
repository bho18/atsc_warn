# WarnBridge

An experimental, self-hosted PBS WARN ATSC 1.0 receiver and evidence archive.
Decodes the observed PID 0x0911 framing, preserves original bytes, and serves a
local API and offline alert inbox. Reception never requires
an Internet service. **CRC integrity is not authenticity. This is not a certified
alerting product and sends no public warnings or operational notifications.**

The selected repository is `atsc_warn`; the application/package is `warnbridge`.
Public source delivery is authorized. Private captures, credentials and runtime
state remain excluded from Git.

## ThinkCentre Docker deployment (internal network)

For a fresh installation on `homeserver`, download two small deployment files;
Docker pulls the app image. The commands use `sudo` for writes under `/opt` and
Docker access, without requiring Docker-group membership or changing directory
ownership. No Git checkout or local build is required:

```sh
sudo mkdir -p /opt/warnbridge/config
cd /opt/warnbridge
sudo curl -fL https://raw.githubusercontent.com/bho18/atsc_warn/codex/warnbridge-initial/compose.deploy.yaml -o /opt/warnbridge/compose.yaml
sudo curl -fL https://raw.githubusercontent.com/bho18/atsc_warn/codex/warnbridge-initial/scripts/configure_docker.py -o /opt/warnbridge/configure_docker.py
if ! sudo test -f /opt/warnbridge/config/local.docker.toml; then
  sudo python3 /opt/warnbridge/configure_docker.py --compose-file /opt/warnbridge/compose.yaml
fi
sudo docker compose -f /opt/warnbridge/compose.yaml pull
sudo docker compose -f /opt/warnbridge/compose.yaml up -d
```

Compose and configuration files live under `/opt/warnbridge`; archived messages
stay in Docker's named volume. An existing local configuration is kept. The helper
detects the ThinkCentre's LAN address/subnet and prints the web URL. The UI binds
that private address and enforces the internal client allowlist.
Receiver and web containers share a persistent archive; raw stream recording is off.
The public deployment image is `ghcr.io/bho18/warnbridge:edge`; no registry login is needed.

For each published update:

```sh
cd /opt/warnbridge
sudo docker compose -f /opt/warnbridge/compose.yaml pull
sudo docker compose -f /opt/warnbridge/compose.yaml up -d
```

[The Docker runbook](docs/docker-live.md) covers status/logs, registry access,
version pinning/rollback, other trusted VLANs and persistent data.

## Native HDHomeRun reception (alternative)

For a deliberate source/native installation, install SiliconDust's `hdhomerun_config` in your Linux/WSL instance, then:

```sh
.venv/bin/warnbridge discover
.venv/bin/warnbridge discover --host 192.168.4.159
.venv/bin/warnbridge listen --host 192.168.4.159 --channel 7
```

The IP/RF channel are historical examples: use your device and station. Omit --host
for native auto-discovery of exactly one receiver. Omit --tuner to acquire the first
unlocked tuner; add --tuner 0 for explicit selection. Existing channel/target settings
are replaced only after acquiring ownership. Output is live JSONL;
SQLite stores decoded WARN evidence. **Raw transport recording is off by default.**
Routine capture filters PID 0x0911 on the receiver and discards unrelated packets.
Use --record-raw only for deliberate diagnostics.

See [the live receiver guide](docs/live-receiver.md) for channel/return-IP settings,
logging, optional raw diagnostics, and WSL UDP routing. Discovery can fail across
VLANs/WSL NAT; --host bypasses broadcast. WSL must also have a working UDP return
path; the listener prints the chosen return IP and warns when no TS arrives.

## Quick offline demonstration

With Python 3.12+ and uv 0.13.5 installed:

```sh
./scripts/setup.sh
./scripts/validate.sh
.venv/bin/warnbridge replay tests/fixtures/reconstructed.ts --config config/demo.toml
.venv/bin/warnbridge serve --config config/demo.toml
```

Open http://127.0.0.1:8080. Choose **Diagnostics → replay** to inspect the checks.
The reconstructed four-packet fixture produces one CMAC
System/Link Test and one heartbeat, both with valid independent CRC values. It is
**not** the original 56-packet OTA capture. No tuner or web endpoint is contacted.

To explore alert text, languages, instructions, areas, updates and cancellations:

```sh
.venv/bin/warnbridge replay tests/fixtures/alert-demo.ts --config config/demo.toml
```

Choose **Alerts → replay** in the UI. These seven messages are explicitly synthetic,
with fixed example dates and DEMO ONLY text; they are not actual warnings or
schema-validated samples. The inbox defaults to live reception and excludes replay.
The heartbeat indicator only pulses for newly observed, recently received live
heartbeats. Link Tests and heartbeat history remain available in Diagnostics.

```sh
.venv/bin/warnbridge decode /path/to/capture.ts --out output/import
cat /path/to/capture.ts | .venv/bin/warnbridge decode - --out output/stdin
.venv/bin/warnbridge replay data/captures --journal --config config/demo.toml
.venv/bin/warnbridge doctor --config config/demo.toml
```

Docker demonstration: `docker compose up --build -d`. It imports the reconstructed
fixture only when the data volume has no database and binds host loopback. The
image runs as UID 10001, without privileges, with persistent data and bounded logs.
No additional Caddy instance is installed. Read the deployment runbook before live
capture. The image includes the HDHomeRun CLI. Normal ThinkCentre deployment uses
`compose.deploy.yaml`; `compose.live.yaml` is the developer source-build alternative.

## Boundaries and project map

- `src/warnbridge/transport`: standard-library decoder and CRC; strict loss handling.
- `formats`: hardened XML parsing, separate validation/classification states.
- `domain`: readable CAP fields, declared lifecycle and offline coordinate geometry.
- `inputs`: file, raw UDP, journal replay, owned HDHomeRun control, saved web JSON.
- `storage`: migration and immutable deliveries; SHA-256 content deduplication.
- `api`, `web`: local queries, confirmed failure cleanup, offline assets and byte inspection.
- `tests`: independent golden vectors, synthetic faults/CAP, storage/API/UDP/tuner tests.

CAP presentation includes multilingual information blocks, instructions, wireless
alert parameters, separate areas, interactive Leaflet maps, expiration and conservative
same-source Update/Cancel reference projection. CMAC alerts have an experimental
original-field review view; current CMAC schema/mappings remain unverified.
Maps bundle an offline Natural Earth reference basemap and offer an optional
OpenStreetMap street layer. See [alert maps](docs/maps.md).
Schema validation, signature verification, geographic targeting and live web
comparison are not implemented. User-supplied
logs confirm live heartbeat/CMAC Link Test reception from an HDHR5-2US in mirrored
WSL after the native keepalive fix. Broader hardware lifecycle behavior remains
unverified, and the cloud has not accessed the receiver. Actual captures are ignored by Git.

Read [deployment](docs/deployment.md), [development](docs/development.md),
[protocol](docs/protocol.md), [evidence](docs/evidence.md), [sources](docs/sources.md),
[architecture](docs/architecture.md), [validation](docs/validation.md) and
[roadmap](docs/roadmap.md). Exact original requirements: [request](docs/request.md).

**Real-capture validation pending; user previously reported successful validation
with the experimental decoder.**

The UI defaults to **Alerts**, with check traffic in **Diagnostics**. RF status is
polled by the live listener and shows stale/error/stopped states. Heartbeat freshness
is separate from RF lock and alert authenticity. Existing evidence is retained;
the current archive uses schema 4 for retention and stable observation IDs. Restart listener and
server after a native/source upgrade. Docker users update with pull/up as above.
See [UI monitoring](docs/ui-monitoring.md).

## Retention and active alerts

Choose **Alert state → Active only** to hide expired, cancelled, superseded,
scheduled and unknown-status alerts. This uses the same lifecycle as the cards,
including CAP/CMAC grouping and source-scoped cancellations, before pagination.

Heartbeat/Link Test deliveries and auxiliary diagnostic logs expire after **7 days**;
failed-message evidence expires after **30 days**, with the existing newest-1000 cap.
Alert history (including Test/System CAP, cancellations and unknown content) is kept.
Cleanup runs at startup and every minute while the receiver or web service is running.
**Retained failures → Preview purge** lets you remove older failures or all retained
failures after reviewing the count. **Storage & retention** shows policy and space use.
See the [Docker runbook](docs/docker-live.md#retention-and-active-filter-update-schema-4)
for first-update backup and configuration details.
