# WarnBridge

An experimental, self-hosted PBS WARN ATSC 1.0 receiver and evidence archive.
Decodes the observed PID 0x0911 framing, preserves original bytes, and serves a
local read-only API and offline message-inspection UI. Reception never requires
an Internet service. **CRC integrity is not authenticity. This is not a certified
alerting product and sends no public warnings or operational notifications.**

The selected repository is `atsc_warn`; the application/package is `warnbridge`.
Public source delivery is authorized. Private captures, credentials and runtime
state remain excluded from Git.

## Live HDHomeRun reception

Install SiliconDust's `hdhomerun_config` in your Linux/WSL instance, then:

```sh
.venv/bin/warnbridge discover
.venv/bin/warnbridge discover --host 192.168.4.159
.venv/bin/warnbridge listen --host 192.168.4.159 --channel 7
```

The IP/RF channel are historical examples: use your device and station. Omit --host
for native auto-discovery of exactly one receiver. Omit --tuner to acquire the first
idle tuner safely; add --tuner 0 for explicit selection. Output is live JSONL;
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

Open http://127.0.0.1:8080. The reconstructed four-packet fixture produces one CMAC
System/Link Test and one heartbeat, both with valid independent CRC values. It is
**not** the original 56-packet OTA capture. No tuner or web endpoint is contacted.

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
capture; the image does not include the HDHomeRun CLI.

## Boundaries and project map

- `src/warnbridge/transport`: standard-library decoder and CRC; strict loss handling.
- `formats`: hardened XML parsing, separate validation/classification states.
- `inputs`: file, raw UDP, journal replay, owned HDHomeRun control, saved web JSON.
- `storage`: migration and immutable deliveries; SHA-256 content deduplication.
- `api`, `web`: read-only API, offline assets, provenance and raw-byte inspection.
- `tests`: independent golden vectors, synthetic faults/CAP, storage/API/UDP/tuner tests.

Schema validation/signature verification, automatic update/cancel application,
geographic filtering and live web comparison are not implemented. User-supplied
logs confirm live heartbeat/CMAC Link Test reception from an HDHR5-2US in mirrored
WSL after the native keepalive fix. Broader hardware lifecycle behavior remains
unverified, and the cloud has not accessed the receiver. Actual captures are ignored by Git.

Read [deployment](docs/deployment.md), [development](docs/development.md),
[protocol](docs/protocol.md), [evidence](docs/evidence.md), [sources](docs/sources.md),
[architecture](docs/architecture.md), [validation](docs/validation.md) and
[roadmap](docs/roadmap.md). Exact original requirements: [request](docs/request.md).

**Real-capture validation pending; user previously reported successful validation
with the experimental decoder.**
