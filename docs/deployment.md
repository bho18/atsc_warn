# homeserver deployment and local acceptance

Target: Ubuntu AMD64, existing HDHomeRun CLI/Jellyfin/Caddy. Do not change those
services, firmware, VLANs, firewall rules or public ports as part of this delivery.
No cloud process contacted the historical receiver IP.

## Get the local delivery onto homeserver

The selected remote `https://github.com/bho18/atsc_warn.git` is currently **public**.
The implementation was not pushed. First obtain the supplied `warnbridge-initial.bundle`
file from this chat's workspace and put it in `~/Downloads` on homeserver (private
file transfer). These commands work without a provisioned remote review branch:

```sh
git clone ~/Downloads/warnbridge-initial.bundle ~/warnbridge
cd ~/warnbridge
python3.12 -m venv ~/.local/share/warnbridge-tools
~/.local/share/warnbridge-tools/bin/pip install uv==0.13.5
export PATH="$HOME/.local/share/warnbridge-tools/bin:$PATH"
./scripts/setup.sh
./scripts/validate.sh
.venv/bin/warnbridge replay tests/fixtures/reconstructed.ts --config config/demo.toml
.venv/bin/warnbridge serve --config config/demo.toml
```

Ubuntu must already provide Python 3.12 and venv support; package setup is a host
administration step if missing. uv installation/dependency setup needs Internet
once; receive/replay/serve thereafter is local. The bundled source has no actual
captures, DBs, credentials or historical third-party implementation code.

Future remote workflow, **only after** the owner changes the repository to Private
and the local review branch is actually pushed:

```sh
git clone --branch codex/warnbridge-initial https://github.com/bho18/atsc_warn.git ~/warnbridge
```

That branch is not currently available remotely. The empty remote also needs a
chosen initial/default-branch setup before a meaningful first PR can be created.
No new remote repository is necessary or authorized by this implementation.

## Original-capture acceptance, before touching tuners

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

## Read-only hardware preflight on homeserver

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
races; the preflight is not a reservation. Every subsequent write and release is
keyed. It refuses configured channels even if the stream target is none. It uses
a WARN-only PID filter unless full_multiplex=true was explicitly configured.
Do not silently choose another tuner after refusal.

After capture, inspect the selected tuner's status/target/lock again. Expect the
owned target/channel stopped and lock released. Confirm Jellyfin still works.
Review session counters, timing journal, heartbeat/link-test observations and raw
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

No automatic reconnect or takeover. After control-network failure, cleanup may be
impossible; it is reported as an error. SIGKILL/power loss cannot guarantee cleanup.
The next capture must repeat inspection and refuse a remaining/foreign lock. Have
an operator investigate ownership; this application never force-clears it. The
next exclusive DB writer marks previously running sessions abandoned.

## Persistent data and Docker

Default `docker compose up --build -d` uses a named volume, non-root UID 10001,
read-only root filesystem, no capabilities, loopback-only port 8080 and rotated
10 MiB × 3 container logs. A missing DB gets only the local synthetic replay demo.
Restart keeps existing data and does not repeat the demo. Images are built locally,
not published. Stop with `docker compose down` (no `-v`, which would remove data).

The container image intentionally does not contain hdhomerun_config. Initial live
hardware deployment should use **native capture plus native serve** with the same
config/database. Native read-only API can run alongside one ingestion writer.
Container replay/UDP/API are tested separately; do not assume a named demo volume
is the same database as the native `data/` directory. To share it deliberately,
mount the native data directory at /data and choose a container UID/GID that can
write it; preserve permissions and backups first.

Raw UDP in a container is an explicit alternative using `warnbridge udp --config`.
Publish the chosen UDP port as UDP, set udp_bind=0.0.0.0 inside the container, and
set return IP on the controlling receiver to the **host's routable address**, not
the container's bridge IP. Raw UDP and RTP are not interchangeable. Existing VLAN
routing/ACLs must already permit control and return traffic. Diagnose locally;
this project does not open ports or reconfigure networking. Linux host networking
is an optional deployment choice for raw UDP, separate from the default bridge
replay setup; it is not needed for native host capture. Keep the API bound to
127.0.0.1 if using host networking.

The existing native Caddy may deliberately proxy to 127.0.0.1:8080. A containerized
Caddy cannot reach the host by its own loopback; use your existing deliberately
configured shared network/host routing. No second Caddy or public port opening.
Apply your existing LAN access policy/authentication before exposing the archive;
the app itself has no authentication and no browser tuner-control endpoint.

## Retention and backups

Default journals: eight segments × 8 MiB, JSONL with actual bytes base64 encoded,
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
