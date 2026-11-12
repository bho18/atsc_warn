# Live HDHomeRun reception (including WSL)

Install Python 3.12+, the locked app dependencies (`./scripts/setup.sh`), and the
native SiliconDust CLI inside the Linux/WSL environment. On Ubuntu the CLI package
is `hdhomerun-config`; verify `hdhomerun_config discover` runs before using discovery.
No Internet discovery service or web comparison endpoint is used.

## Find a device and inspect its tuners

```sh
.venv/bin/warnbridge discover
# Direct IP bypasses broadcast discovery entirely:
.venv/bin/warnbridge discover --host 192.168.4.159
```

The IP is the user's historical example; substitute the current receiver address.
Native discovery delegates to `hdhomerun_config discover` (SiliconDust's native
broadcast protocol). Local `/discover.json` metadata supplies the device ID, model
and tuner count; unknown fields, DeviceAuth and device-supplied URLs are ignored.
Metadata reads have a five-second timeout, 64 KiB bound and no redirect following.
The CLI lists each tuner's current RF channel, signal status, stream target and
lock owner, with idle/busy/unknown availability. These commands only read state.

IPv4 is supported. Duplicate native results for a device ID are coalesced. When
multiple devices are discovered, `listen` requires --host instead of picking a
receiver arbitrarily. If the HTTP metadata endpoint is inaccessible but native
control works, specify both --host and --tuner to operate without guessing tuner
count. Direct-IP metadata/control do not depend on broadcast reaching the device.

## Listen, choose a channel, and output messages

```sh
# Discover exactly one device; choose and acquire its first idle tuner:
.venv/bin/warnbridge listen --channel 7

# Direct IP, automatic idle tuner selection:
.venv/bin/warnbridge listen --host 192.168.4.159 --channel 7

# Explicit tuner and return path:
.venv/bin/warnbridge listen --host 192.168.4.159 --tuner 1 \
  --channel auto:7 --return-ip 192.0.2.20 --udp-port 5000
```

Replace the TEST-NET return address with the receiving machine's address that the
HDHomeRun can reach. --channel 7 means **physical RF 7** and becomes auto:7. For
WNPT this is the historical known setting, not a universal station default. Current
channels are visible in `discover`; this workflow does not run a station scan or
retune an occupied tuner. Channel changes require stopping the owned listener and
starting it with the new --channel value. `capture` remains an alias for `listen`.

Automatic selection only skips busy/foreign-owned tuners or a lost acquisition
race. Each candidate is rechecked under its owned lock before any tuning; a filter,
control or network failure stops the operation instead of blindly switching tuners.
Explicit --tuner never silently switches to another tuner. All tuners busy produces
an error with no takeover. A non-none channel is conservatively treated as busy,
even when target/lock appear empty. Jellyfin ownership is never force-cleared.

Routine reception sets a device-side filter for PID 0x0911 and consumes raw UDP TS
in memory. **No transport/datagram recording files are created by default.** Only
complete WARN message evidence and bounded failure diagnostics go into SQLite;
non-WARN packets are discarded. There is no full-multiplex recording or need to
write a TS file before decoding. Existing unneeded arrival journals from earlier
versions are not deleted automatically.

Stdout is immediately flushed JSONL: a receiver selection record, a `message` record
per complete delivery (or `rejected` diagnostic), and a final `summary` on shutdown.
Message records contain classification, validation states, XML/fields, duplicate
flag, reception time and exact body bytes as base64. The XML text field is a UTF-8
display view; original body bytes remain unchanged in base64/SQLite. Duplicate
messages are labeled and remain visible in delivery history. No operational alert
notifications are generated. Stderr carries startup information and network warnings.

```sh
mkdir -p data
.venv/bin/warnbridge listen --host 192.168.4.159 --channel 7 | tee -a data/messages.jsonl
# In another terminal, using the same DB/config:
.venv/bin/warnbridge serve
```

The UI/API observes the database while the single ingestion worker runs. Reception
and import times remain separate; receiving a Link Test is not a public alert.
Use --duration 60 for a bounded test; Ctrl-C/SIGTERM also stops and releases the owned
tuner. Receiver selection and native control have bounded calls; stop waits for an
in-flight call before cleanup. Crash/network cleanup limitations in deployment.md
still apply; no automatic forced lock recovery exists.

For durable configuration copy `config/live.example.toml` to `config/local.toml`.
CLI options override TOML; --tuner auto overrides a configured explicit tuner.
Only deliberate diagnostics should use --full-multiplex or --record-raw. The latter
opts into the existing bounded rotating arrival journals. --no-record-raw overrides
a config that enables recording. Diagnostic recording retention settings retain
their prior names, but do nothing unless record_raw=true/--record-raw is selected.

## WSL and network troubleshooting

Direct-IP TCP control succeeding does not prove the receiver's UDP stream can
reach WSL. Default WSL2 NAT commonly prevents unsolicited inbound UDP/broadcast
from a LAN device. On supported Windows/WSL installations, an existing mirrored
networking configuration can make LAN discovery and UDP reception work. Otherwise
use an already configured routable UDP return path, or run the listener on the
native Ubuntu host. A TCP-only portproxy is not a UDP return path.

The listener binds 0.0.0.0:5000 by default, selects a return address using the local
route to the receiver (without sending a probe datagram), and prints that address
on startup. Override it with --return-ip if it is not routable from the receiver;
WSL's private 172.x NAT address may not be reachable from the HDHomeRun. Merely
substituting the Windows LAN IP does not create a UDP forwarding path to WSL.
--udp-bind controls the local socket; --return-ip controls the receiver target.

After 45 seconds without valid TS data (configurable no_data_warning), a warning
points to RF lock, PID, return address and WSL routing. It also persists a health
event. This is a diagnostic warning, not an automatic firmware/firewall/VLAN change
or proof of a receiver failure. If no data arrives, inspect the tuner RF status
read-only and verify the chosen address/UDP port using local network diagnostics.

No hardware, Windows settings, Jellyfin, Caddy, firewall or VLAN was changed or
contacted by cloud validation. Native discovery/control and WSL return paths still
need the user's opt-in local hardware validation.
