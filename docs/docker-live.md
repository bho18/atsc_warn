# Live Docker deployment on homeserver

Target: the Ubuntu AMD64 Lenovo ThinkCentre named `homeserver`, with existing
Docker, Caddy and Jellyfin. This deployment adds only WarnBridge. No Caddy instance,
router forwarding, firewall/VLAN change, privileged container or Docker socket mount
is needed. The image includes Debian's `hdhomerun-config` package.

Two containers share one persistent archive: `receiver` runs live HDHomeRun reception;
`web` serves the read-only UI/API. Both use Linux host networking. The receiver can
use the host's actual routable return address without Docker UDP/NAT translation.
The web process binds one private LAN IPv4 address, rather than 0.0.0.0, and checks
actual client IPs against configured trusted subnets. No Docker ports are published.

## Install on the ThinkCentre

Docker Engine and the Compose plugin are already part of the stated deployment
environment. Use that existing installation. If the checkout does not exist:

```sh
git clone --branch codex/warnbridge-initial https://github.com/bho18/atsc_warn.git ~/warnbridge
cd ~/warnbridge
```

For an existing checkout, `cd ~/warnbridge` and update it with:

```sh
git pull --ff-only https://github.com/bho18/atsc_warn.git codex/warnbridge-initial
```

Then configure locally:

```sh
python3 scripts/configure_docker.py
docker compose -f compose.live.yaml build
```

The script reads `ip -j -4 address show` and a kernel route lookup to the configured
receiver. These commands send no packet/query to the tuner. It detects the host's
LAN address and connected client subnet, writes ignored `config/local.docker.toml`
and prints the web URL. It refuses public/wildcard, loopback and Docker bridge
addresses and will not overwrite an existing configuration. No Python venv is
needed on the host; app dependencies are installed inside the image.

The historical receiver/RF defaults are `192.168.4.159` and RF 7, matching the user's
working setup. They can be changed without application edits. Explicit examples:

```sh
python3 scripts/configure_docker.py --receiver 192.168.4.159 --channel 7
# Optional: choose an actual host LAN address or another unused web/UDP port.
python3 scripts/configure_docker.py --lan-ip 192.168.1.50 --port 8082 --udp-port 5001
# Optional: add a trusted client VLAN to the detected host subnet.
python3 scripts/configure_docker.py --allow-network 192.168.4.0/24
```

These are alternative first-run commands, not successive overwrites. Edit the
existing local TOML for later changes. `192.168.1.50` is an example, not an asserted
ThinkCentre IP; default detection uses the address actually configured on that host.
The generated settings keep raw recording/full-multiplex off, select an idle tuner
automatically, and put the DB plus any future opt-in journals under `/data`.

## Preflight, start and inspect

Stop any old WarnBridge listener that uses this same tuner/UDP port before moving
capture; keep Jellyfin running. Check availability without tuning or scanning:

```sh
docker compose -f compose.live.yaml run --rm --no-deps receiver \
  discover --config /app/config/live.toml
```

An idle tuner must be available. Owned locks and idle-state checks remain enforced;
this app never force-clears a Jellyfin tuner. Once the inventory is acceptable:

```sh
docker compose -f compose.live.yaml up -d
docker compose -f compose.live.yaml ps
docker compose -f compose.live.yaml logs --tail=50 -f receiver
```

Open the exact LAN URL printed by the setup script, normally port 8080. The web
container starts with an empty live archive; it does not seed replay tests. The
receiver persists decoded WARN evidence and prints live JSONL. Heartbeat/Link Test
traffic is visible in the usual indicators/Diagnostics, with alert content in Alerts.
No full transport stream is recorded by default.

Web health probes the configured local bind address. Receiver health checks recent
live heartbeat evidence in the database, without new device operations. A 90-second
startup window accommodates RF settling/check cadence; unhealthy status reports a
reception problem and does not automatically retune or clear a lock. Docker restarts
exited processes, including after reboot; busy-tuner startup can keep retrying with
Docker's backoff. An unhealthy running container is not automatically restarted.
Graceful stop allows 60 seconds for the receiver's owned cleanup.

```sh
docker compose -f compose.live.yaml stop
# Or remove the containers/network while preserving the archive:
docker compose -f compose.live.yaml down
```

Do not add `-v` to a production `down`: it deletes the named archive volume. The
volume is scoped to project `warnbridge-live`, independently of the default replay
demo. Both processes use UID/GID 10001, read-only root filesystems, no capabilities,
no-new-privileges and bounded logs (10 MiB × 3 per container).

## Internal-network access

The generated `bind` is the ThinkCentre's private LAN address. Only that socket is
opened; the stack has no wildcard port publication. `web_allowed_networks` contains
the host address, loopback for local checks, and its detected connected LAN subnet.
Add only the private client CIDRs that should be able to read the archive. Other
peers receive HTTP 403 on UI, API, raw messages and assets alike. Requests cannot
bypass this by setting X-Forwarded-For/X-Real-IP/Forwarded; `warnbridge serve`
disables proxy-header trust and uses the real socket peer.

Keep this stack off public reverse-proxy routes and router port forwarding. A
reverse proxy hides the original socket peer, so its own access policy would also
need to enforce any deliberate proxied exposure. The app has no login system;
the subnet allowlist is the boundary for this internal deployment. Existing Caddy,
Jellyfin, Windows and firewall settings are not changed. Existing host network
policy must already allow client HTTP and native HDHomeRun control/return UDP;
this installer never opens host firewall ports.

If the host is multihomed, select its intended management LAN with `--lan-ip` or
edit `bind`/`return_ip` appropriately. `return_ip` must be reachable from the tuner
VLAN; `udp_bind` must be an address actually present on the host. A DHCP address
change requires updating the local config and recreating services; a DHCP
reservation is an optional operator choice, not an automatic network modification.

## Existing data and updates

Keep the old WSL/native archive until you have a verified SQLite backup. Never copy
a live DB without its WAL or overwrite a running/new production database. To import
a consistent backup into an empty Docker archive, first stop both containers and
place that backup privately at `backups/warnbridge.db`, readable by UID 10001:

```sh
docker compose -f compose.live.yaml stop
docker compose -f compose.live.yaml run --rm --no-deps \
  --entrypoint /bin/sh -v "$PWD/backups:/backup:ro" web \
  -c 'test ! -e /data/warnbridge.db && cp /backup/warnbridge.db /data/warnbridge.db'
```

The command refuses an existing target. Keep backups/private captures out of Git.
For a fresh setup no import is required. Upgrades retain the named volume:

```sh
docker compose -f compose.live.yaml stop
git pull --ff-only https://github.com/bho18/atsc_warn.git codex/warnbridge-initial
docker compose -f compose.live.yaml build
docker compose -f compose.live.yaml up -d
```

This deployment needs no new database migration beyond schema 2. The old
`compose.yaml` remains a separate loopback-only replay demonstration.
