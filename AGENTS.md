# WarnBridge
Experimental offline-first PBS WARN receiver for ATSC 1.0 PID 0x0911. Python 3.12+.

Run `./scripts/setup.sh`, then `./scripts/validate.sh`. Decoder must work without
starting the API. Never start hardware capture in CI or cloud tests.

Preserve original TS, message/body/XML bytes; distinguish reception, import, inferred
transport and XML times. CRC is integrity, never authentication. Missing schema/trust
configuration is not successful validation. Never turn replay/System/Test traffic
into operational public warnings. No public-warning, siren, IPAWS origination or
outbound upload behavior. Never force-clear a tuner lock or contact the user's LAN
from the cloud. Native discovery and automatic unlocked-tuner selection are allowed;
require explicit --host when multiple devices exist. A confirmed lockkey=none allows
acquisition even with a configured channel/target; atomically acquire ownership
before replacing them. Use owned-lock operations.
Process live TS in memory; raw journals are opt-in. Preserve alert evidence.
User-authorized retention expires heartbeat/Link Test and auxiliary diagnostics after
7 days, failed evidence after 30 days (configurable). The local UI may explicitly
purge retained failures after a count preview and confirmation; never purge alerts.

The user permits a public repository and normal source delivery. The user also
authorizes WarnBridge container image publication to GHCR for pull-based installation
and iterative image updates. Other package publication and private captures still
require separate authorization. Do not copy historical PBS source without verified
licensing. No credentials in source or logs.
UI: keep one small signature-verification note; do not repeat authentication/schema
disclaimers across cards, badges and message details. Preserve technical metadata.

Read docs/protocol.md, docs/evidence.md, docs/architecture.md and docs/deployment.md.
Before completion run offline tests, lint, type checks and an end-to-end replay/API
check; update docs/validation.md with actual outcomes and unverified limitations.

## Deployment and updates

- The target is the Ubuntu AMD64 Lenovo ThinkCentre named `homeserver`. Treat setup
  as a fresh WarnBridge installation until the user confirms it is deployed. Prior
  WSL/laptop reception does not establish a checkout, installation or running service
  on the ThinkCentre. Do not ask again for the already recorded OS/host/tuner details.
- The canonical host deployment directory is `/opt/warnbridge`, not bare `/opt`
  or a source checkout. Keep `/opt/warnbridge/compose.yaml`, the helper,
  `/opt/warnbridge/config/local.docker.toml` and optional `/opt/warnbridge/.env` there.
  The archive remains in Docker's named volume, mounted at container `/data`.
  Use a root-owned installation: include `sudo` for directory creation, downloads
  into `/opt/warnbridge`, config generation/edits and production Docker commands.
  Do not assume Docker-group membership or user ownership. Never recursively change
  ownership across `/opt`; no chown is required for this root-owned setup.
- The normal deployment is image-only. Follow `docs/docker-live.md`: create that host
  directory, download `compose.deploy.yaml` as `compose.yaml` and
  `scripts/configure_docker.py`, run the helper with
  `--compose-file /opt/warnbridge/compose.yaml`,
  then `sudo docker compose pull` and `sudo docker compose up -d`. A Git checkout, host venv,
  local image build and native host HDHomeRun CLI are not prerequisites.
- The public image is `ghcr.io/bho18/warnbridge:edge`; anonymous manifest access,
  full image pull and container startup have been verified. It includes the native
  HDHomeRun CLI. The helper detects LAN settings on the target host using iproute2;
  never substitute the laptop's historical IP for the ThinkCentre's address.
- Keep the UI internal: explicit private LAN bind and trusted subnet allowlist,
  actual socket-peer checks, no forwarded-header trust, no public proxy/port
  forwarding or automatic firewall changes. Preserve existing Caddy/Jellyfin.
- App updates run from `/opt/warnbridge`: `sudo docker compose pull` then
  `sudo docker compose up -d`. From another directory, use
  `-f /opt/warnbridge/compose.yaml` explicitly. Default generated config paths must
  resolve beside the Compose file, never under an unrelated working directory.
  Preserve `config/local.docker.toml`, optional image pin in `.env`, project name
  `warnbridge-live` and its archive volume. Do not instruct `down -v` or rerun the
  first-install config helper for routine updates. A Compose layout change must be
  called out separately; refresh the downloaded file without overwriting config.
- `.github/workflows/container.yaml` validates and publishes Linux AMD64 images on
  `codex/warnbridge-initial` pushes: rolling `edge`, `sha-<full commit>` and registry
  digests for pins/rollback. Keep publication gated on tests; verify the Actions
  result and image pull before claiming that a new published image is available.
- `compose.live.yaml` is the developer source-build alternative; `compose.yaml` in
  the source repository is the replay demo. Do not present either as the normal
  fresh-install/pull-update workflow. Native/WSL guides are alternatives/history.
- Read `docs/docker-live.md` before changing deployment instructions. Preserve
  `docs/request.md` and historical evidence/validation provenance; current user
  deployment instructions here and in the live Docker runbook supersede their
  initial private-repository/local-build assumptions.
