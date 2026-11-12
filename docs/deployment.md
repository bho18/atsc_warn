# homeserver deployment and local acceptance

Target: the Ubuntu AMD64 ThinkCentre named `homeserver`. The image supplies the
HDHomeRun CLI; no host CLI installation is required. Preserve existing Jellyfin,
Caddy, firmware, VLANs, firewall settings and public-port policy.
No cloud process contacted the historical receiver IP.

## Default: fresh Docker installation and image updates

Use [the ThinkCentre Docker runbook](docker-live.md) for the user deployment.
It starts with a new host directory and downloads a Compose file plus the local
configuration helper. It requires no WarnBridge checkout, host venv or local build.
The public image is `ghcr.io/bho18/warnbridge:edge`; it includes the native tuner CLI.
The helper detects the ThinkCentre's private address and prints the internal web URL.

The installed Compose file is named `compose.yaml`, downloaded from
`compose.deploy.yaml`. Normal updates run in that host directory:

```sh
cd ~/warnbridge
docker compose pull
docker compose up -d
```

The source publishing workflow validates each source revision before updating
`edge`. Local configuration and the named archive volume survive container updates.
A previous WSL test does not establish an installation on homeserver. Follow the
fresh-install sequence unless the user confirms a completed deployment. Keep the
web bind and client allowlist internal; do not add public proxy/forwarding rules.

## Optional native/source installation and acceptance

The remaining native commands are an alternative for source development and private
capture acceptance. They are not prerequisites for the Docker installation above.

### Get a source checkout

The user has authorized this repository to be public. Clone the delivered review
branch (or use a supplied source bundle when remote access is unavailable):

```sh
git clone --branch codex/warnbridge-initial https://github.com/bho18/atsc_warn.git ~/warnbridge
cd ~/warnbridge
python3.12 -m venv ~/.local/share/warnbridge-tools
~/.local/share/warnbridge-tools/bin/pip install uv==0.13.5
export PATH="$HOME/.local/share/warnbridge-tools/bin:$PATH"
./scripts/setup.sh
./scripts/validate.sh
```

For native live reception follow [live-receiver.md](live-receiver.md), with
WSL-specific network notes when applicable. It uses native discovery or direct IP, reads tuner availability/current
channels, leases an idle tuner, applies the WARN PID filter and outputs JSONL while
processing UDP in memory. Raw journaling is off by default. The native Linux CLI
package on Ubuntu is `hdhomerun-config`. No receiver is contacted by setup/validation.

### Original-capture acceptance in a source checkout

Use a fresh output directory for the private original. Do not commit/upload it.

```sh
cd ~/warnbridge
sha256sum /home/bryan/warn-0911.ts
wc -c /home/bryan/warn-0911.ts
.venv/bin/warnbridge decode /home/bryan/warn-0911.ts --out output/original-acceptance
.venv/bin/python - <<'PY'
import json
from pathlib import Path
expected = json.loads(Path('docs/baseline.json').read_text())
actual = json.loads(Path('output/original-acceptance/summary.json').read_text())
differences = {k: {'expected': v, 'actual': actual.get(k)}
               for k, v in expected.items() if actual.get(k) != v}
print(differences or 'All supplied baseline counters match')
raise SystemExit(bool(differences))
PY
```

Exact reported PID-only file size is 10,528 bytes. A different file need not have
those counts. Record its real hash, command output and provenance privately; never
change the decoder to hardcode that baseline. Optionally decode the full multiplex
with a separate output directory; it may not be the identical recording segment.
Untimed file reception remains unknown, irrespective of file mtime/import clock.

### Native read-only hardware preflight

The following address is the historical example; confirm the current host/IP
locally. Inspect **both** tuners without tuning, setting a target or scanning:

```sh
hdhomerun_config 192.168.4.159 get /tuner0/status
hdhomerun_config 192.168.4.159 get /tuner0/target
hdhomerun_config 192.168.4.159 get /tuner0/lockkey
hdhomerun_config 192.168.4.159 get /tuner1/status
hdhomerun_config 192.168.4.159 get /tuner1/target
hdhomerun_config 192.168.4.159 get /tuner1/lockkey
```

Continue only when one chosen tuner reports channel none, target none, lock none,
and Jellyfin is not using/reserving it. If busy or uncertain, stop and retry later;
never force-clear the lock. Prior idle status is irrelevant.

```sh
cp config/homeserver.example.toml config/local.toml
# Edit config/local.toml: current host, explicitly selected idle tuner, channel,
# and return_ip = homeserver's IPv4 routable from the receiver VLAN.
.venv/bin/warnbridge doctor --config config/local.toml --receiver
# Only after reviewing the idle snapshot:
.venv/bin/warnbridge capture --config config/local.toml --duration 60
```

The adapter rechecks before and after atomic lock acquisition to protect against
races; the preflight is not a reservation. Auto-selection may skip a busy or raced
candidate and try the next idle tuner; an explicit --tuner choice is never changed. Every subsequent write and release is
keyed. It refuses configured channels even if the stream target is none. It uses
a WARN-only PID filter unless full_multiplex=true was explicitly configured.
A non-busy startup/network error stops reception instead of trying another tuner.

After capture, inspect the selected tuner's status/target/lock again. Expect the
owned target/channel stopped and lock released. Confirm Jellyfin still works.
Review live JSONL, session counters, heartbeat/link-test observations and WARN
bytes. Lack of native CAP/public alerts is not a capture failure by itself; a
heartbeat alone is not public-warning end-to-end validation.

For full-multiplex diagnostics, explicitly set full_multiplex=true for a bounded
capture. Journals rotate rapidly at full broadcast bitrate; increase retention
only intentionally. Restore the configuration to false afterward.

## Shutdown, failure and recovery

SIGINT/SIGTERM sets a stop flag. UDP timeout permits prompt exit, pending assemblies
become incomplete diagnostics, then the owned target/channel and lock are cleared.
Subprocess calls have an 8-second timeout. Startup failures after lock acquisition
run keyed cleanup. An uncertain lock-acquisition timeout attempts only keyed release
of the candidate key. If ownership changed, device-side keyed writes must refuse;
no force/unkeyed cleanup or stale restoration follows. Tests mock these outcomes;
firmware behavior still requires the opt-in local check.

The receiver process performs no in-place automatic reconnect or takeover. Docker
may restart an exited process, repeating its normal idle/owned-lock checks; an
unhealthy running container is not automatically retuned. After control-network
failure, cleanup may be impossible; it is reported as an error. SIGKILL/power loss cannot guarantee cleanup.
The next capture must repeat inspection and refuse a remaining/foreign lock. Have
an operator investigate ownership; this application never force-clears it. The
next exclusive DB writer marks previously running sessions abandoned.

## Source-build and replay Docker alternatives

For the ThinkCentre's live receiver and LAN-only UI use [docker-live.md](docker-live.md).
It downloads a published image without a Git checkout/local build, detects LAN
settings locally, separates receiver/web processes and persists their shared archive.
The instructions below describe the separate source/replay alternatives.

From a source checkout, the replay demo `docker compose up --build -d` uses a
named volume, non-root UID 10001,
read-only root filesystem, no capabilities, loopback-only port 8080 and rotated
10 MiB × 3 container logs. A missing DB gets only the local synthetic replay demo.
Restart keeps existing data and does not repeat the demo. This replay example
builds locally; `compose.deploy.yaml` instead pulls the published GHCR image.
Stop with `docker compose down` (no `-v`, which would remove data).

The image includes Debian's hdhomerun-config. Production `compose.deploy.yaml`
pulls that image. Developer `compose.live.yaml` builds it from a source checkout
while retaining the same host networking and restricted web server. Native
processes remain a separate alternative. Do not assume a
named demo/live Docker volume is the same database as the native `data/` directory. To share it deliberately,
mount the native data directory at /data and choose a container UID/GID that can
write it; preserve permissions and backups first.

Raw UDP in a container is an explicit alternative using `warnbridge udp --config`.
Publish the chosen UDP port as UDP, set udp_bind=0.0.0.0 inside the container, and
set return IP on the controlling receiver to the **host's routable address**, not
the container's bridge IP. Raw UDP and RTP are not interchangeable. Existing VLAN
routing/ACLs must already permit control and return traffic. Diagnose locally;
this project does not open ports or reconfigure networking. Linux host networking
is an optional deployment choice for raw UDP, separate from the default bridge
replay setup; it is not needed for native host capture. In an ad hoc raw-UDP
experiment, keep the API on loopback unless you deliberately configure the private
LAN bind and client allowlist used by the production deployment.

The existing native Caddy may deliberately proxy to 127.0.0.1:8080. A containerized
Caddy cannot reach the host by its own loopback; use your existing deliberately
configured shared network/host routing. No second Caddy or public port opening.
Apply your existing LAN access policy/authentication before exposing the archive;
the app itself has no authentication and no browser tuner-control endpoint.

## Retention and backups

Raw journals are disabled by default. Opt-in --record-raw journals: eight segments × 8 MiB, JSONL with actual bytes base64 encoded,
UTC/monotonic timestamps, sequence and UDP peer. Old segments are deleted; copy
interesting private evidence before rotation. Replay is deterministic in order,
without artificial wall-clock delays, and always labeled replay. Missing/rotated
prefixes may start mid-message and correctly produce orphan diagnostics.

Accepted message evidence persists until explicitly archived. Default DB+WAL
threshold 512 MiB stops ingestion rather than silently deleting accepted data;
final bounded pending evidence can exceed the threshold slightly. Rejected evidence
and health events retain the newest 1000 each; session counters keep total failures.
No privileged container or external log service is needed.

To back up native data consistently while a reader/writer is running:

```sh
mkdir -p backups
.venv/bin/python - <<'PY'
import sqlite3
from datetime import datetime, timezone
name = 'backups/warnbridge-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.db'
source = sqlite3.connect('data/warnbridge.db')
destination = sqlite3.connect(name)
source.backup(destination)
destination.close()
source.close()
print(name)
PY
```

Copy config/local.toml and retained journal files through private backup channels.
For restore/archival: stop receiver and API, preserve the existing DB/WAL/SHM as a
consistent set in a separate backup, then place a SQLite backup at the configured
DB path with correct permissions. Do not overwrite a running DB or mix stale
WAL/SHM with a replacement. Restart API and verify data, then run read-only tuner
preflight before starting capture. Keep backups and runtime files out of Git.
