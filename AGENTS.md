# WarnBridge
Experimental offline-first PBS WARN receiver for ATSC 1.0 PID 0x0911. Python 3.12+.

Run `./scripts/setup.sh`, then `./scripts/validate.sh`. Decoder must work without
starting the API. Never start hardware capture in CI or cloud tests.

Preserve original TS, message/body/XML bytes; distinguish reception, import, inferred
transport and XML times. CRC is integrity, never authentication. Missing schema/trust
configuration is not successful validation. Never turn replay/System/Test traffic
into operational public warnings. No public-warning, siren, IPAWS origination or
outbound upload behavior. Never force-clear a tuner lock or contact the user's LAN
from the cloud. Native discovery and automatic idle-tuner selection are allowed;
require explicit --host when multiple devices exist. Use owned-lock operations.
Process live TS in memory; raw journals are opt-in. Preserve WARN message evidence.

The user permits a public repository and normal source delivery. The user also
authorizes WarnBridge container image publication to GHCR for pull-based installation
and iterative image updates. Other package publication and private captures still
require separate authorization. Do not copy
historical PBS source without verified licensing. No credentials in source or logs.

Read docs/protocol.md, docs/evidence.md, docs/architecture.md and docs/deployment.md.
Before completion run offline tests, lint, type checks and an end-to-end replay/API
check; update docs/validation.md with actual outcomes and unverified limitations.
