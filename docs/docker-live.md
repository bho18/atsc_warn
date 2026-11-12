# Install WarnBridge on the ThinkCentre

Run these commands on `homeserver`, the Ubuntu AMD64 ThinkCentre. This is a fresh
installation using Docker Engine and its Compose plugin. You do not need a Git
checkout, Python virtual environment, local image build, Caddy configuration or an
existing WarnBridge installation. The host commands use `curl`, `python3` and
`iproute2`, alongside Docker Compose.

## Deployment directory

The ThinkCentre installation directory is **`/opt/warnbridge`**. Keep this layout:

```text
/opt/warnbridge/
  compose.yaml
  configure_docker.py
  config/local.docker.toml
  .env                       # optional image pin
```

The archive lives in Docker's named volume, mounted at `/data` inside the containers.
It is not written directly into `/opt`. The commands below use `sudo` for writes to
the app directory and Docker access. They do not require Docker-group membership
or transfer ownership of `/opt` or its contents to your account.

The helper derives its default config path from the Compose file's directory, so
`--compose-file /opt/warnbridge/compose.yaml` writes
`/opt/warnbridge/config/local.docker.toml` even when invoked from another directory.
Existing configuration is never overwritten. If files were already downloaded
elsewhere, inspect their paths before moving them; do not replace a working config.

## First installation

Download the deployment files into the application directory:

```sh
sudo mkdir -p /opt/warnbridge/config
cd /opt/warnbridge
sudo curl -fL https://raw.githubusercontent.com/bho18/atsc_warn/codex/warnbridge-initial/compose.deploy.yaml -o /opt/warnbridge/compose.yaml
sudo curl -fL https://raw.githubusercontent.com/bho18/atsc_warn/codex/warnbridge-initial/scripts/configure_docker.py -o /opt/warnbridge/configure_docker.py
if ! sudo test -f /opt/warnbridge/config/local.docker.toml; then
  sudo python3 /opt/warnbridge/configure_docker.py --compose-file /opt/warnbridge/compose.yaml
fi
```

The configuration helper reads the ThinkCentre's own network settings and prints
the LAN web URL. It uses the existing receiver address `192.168.4.159` and physical
RF channel 7, detects the host LAN address/subnet, and writes
`config/local.docker.toml`. Reading the routing table does not query or tune the
HDHomeRun. An existing local configuration is never overwritten. Run this helper
once for first installation; the conditional above skips it if the config already
exists. Normal image updates keep that file and do not rerun the helper.

Pull the image and start the two containers. Absolute Compose paths also work
when the shell is in another directory:

```sh
sudo docker compose -f /opt/warnbridge/compose.yaml pull
sudo docker compose -f /opt/warnbridge/compose.yaml up -d
sudo docker compose -f /opt/warnbridge/compose.yaml ps
```

Open the URL printed by the helper, normally `http://<ThinkCentre-LAN-IP>:8080`.
The image includes WarnBridge and `hdhomerun_config`; Docker downloads those together.
The `receiver` container safely selects an idle tuner and processes the WARN stream.
The `web` container serves the archive and receiver indicators. No full transport
stream recording is enabled.

See recent reception and web logs with:

```sh
cd /opt/warnbridge
sudo docker compose -f /opt/warnbridge/compose.yaml logs --tail=50 -f receiver
sudo docker compose -f /opt/warnbridge/compose.yaml logs --tail=50 web
```

The published image is `ghcr.io/bho18/warnbridge:edge`. Anonymous manifest access
and a complete Docker pull have been verified; no registry login or token is needed.
The `.github/workflows/container.yaml` workflow validates source pushes to
`codex/warnbridge-initial`, publishes Linux AMD64 commit-specific images, and
promotes the current passing revision to `edge`. A source push is not a completed
image release until that workflow succeeds. You control when the ThinkCentre
installs an update by running the pull/up commands below.

## Pull an update

As new images are published during development, run:

```sh
cd /opt/warnbridge
sudo docker compose -f /opt/warnbridge/compose.yaml pull
sudo docker compose -f /opt/warnbridge/compose.yaml up -d
sudo docker compose -f /opt/warnbridge/compose.yaml ps
```

This downloads the new `edge` image and recreates changed containers. It preserves
`/opt/warnbridge/config/local.docker.toml` and the named archive volume. There is
no `git pull` or image build on the ThinkCentre. If pulling fails, the running containers continue
using their existing image; do not remove them to retry a download.

Normal app updates use the same Compose file. When a release also changes the
deployment layout, refresh that file without replacing the local configuration:

```sh
cd /opt/warnbridge
sudo curl -fL https://raw.githubusercontent.com/bho18/atsc_warn/codex/warnbridge-initial/compose.deploy.yaml -o /opt/warnbridge/compose.yaml.new
sudo docker compose -f /opt/warnbridge/compose.yaml.new config --quiet
sudo cp /opt/warnbridge/compose.yaml /opt/warnbridge/compose.yaml.previous
sudo mv /opt/warnbridge/compose.yaml.new /opt/warnbridge/compose.yaml
sudo docker compose -f /opt/warnbridge/compose.yaml pull
sudo docker compose -f /opt/warnbridge/compose.yaml up -d
```

Images also have a commit-specific `sha-<full-commit-sha>` tag. To keep a particular
version or roll back an app image, edit the optional root-managed image pin:

```sh
sudoedit /opt/warnbridge/.env
```

Set its exact tag:

```dotenv
WARNBRIDGE_IMAGE=ghcr.io/bho18/warnbridge:sha-<full-commit-sha>
```

Then run the `sudo docker compose` pull/up commands above again. A registry digest
(`ghcr.io/bho18/warnbridge@sha256:<digest>`) pins the exact image bytes. Remove the
line to follow `edge` updates again. Keep a SQLite backup before an upgrade that changes
the database schema; changing an image tag does not reverse a database migration.

## Internal network and persistent data

The web server binds the detected private LAN address and checks the actual client
IP against its configured internal subnet allowlist. Clients outside that list
receive HTTP 403, including on API and static-asset routes. Forwarding headers cannot
bypass the check. Both containers use Linux host networking, with no published
Docker ports. The app does not add public proxy routes, router forwarding or
firewall rules, and does not modify Caddy or Jellyfin.

The archive is the named volume belonging to project `warnbridge-live`, shared by
both containers at `/data`. It starts empty on a fresh installation. Containers run
as UID/GID 10001, with read-only root filesystems, capabilities dropped and bounded
logs. The receiver keeps its owned-lock safeguards and does not take a busy tuner
from another application. Container stop allows 60 seconds for owned cleanup.

```sh
cd /opt/warnbridge
sudo docker compose -f /opt/warnbridge/compose.yaml stop
# Remove containers while retaining the archive:
sudo docker compose -f /opt/warnbridge/compose.yaml down
```

Do not use `sudo docker compose down -v` on this installation: `-v` deletes the archive.
Keep the local config and a consistent SQLite backup when moving to another host.
The app has no login system; keep it off public reverse-proxy routes and router
port forwarding. Existing host network policy must allow the selected internal
client subnet and tuner return traffic.

## Different LAN settings

For a first installation with an additional trusted client VLAN, a different
configured host address, or different ports, use the helper before starting:

```sh
sudo python3 /opt/warnbridge/configure_docker.py --compose-file /opt/warnbridge/compose.yaml --allow-network 192.168.4.0/24
# Alternative example; use an address actually assigned to the ThinkCentre:
sudo python3 /opt/warnbridge/configure_docker.py --compose-file /opt/warnbridge/compose.yaml --lan-ip 192.168.1.50 --port 8082 --udp-port 5001
```

These are alternative first-run commands. For an existing installation, edit its
local TOML with `sudoedit /opt/warnbridge/config/local.docker.toml`, then run
`sudo docker compose -f /opt/warnbridge/compose.yaml up -d --force-recreate`.
The helper refuses public/wildcard, loopback or Docker bridge addresses and will not overwrite the
local file. If DHCP changes the host's address, update the bind/return address and
allowed subnet settings before recreating the containers.
