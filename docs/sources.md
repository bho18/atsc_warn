# Sources, access and licensing ledger

Access attempts: November 10, 2026 America/Chicago / November 11 UTC. Machine-readable
HTTP results and successful-source hashes: [source-access.json](source-access.json).
All retrieval was read-only. No historical programs were executed; no standards
purchased; no contacts made; no credentials or private captures used.

## Official manufacturer source inspected

[SiliconDust libhdhomerun](https://github.com/Silicondust/libhdhomerun), resolved HEAD
`dc48af56d3c338288765b263e57129f711dedb9b` via git ls-remote. Pinned raw source fetched
successfully. LICENSE says GNU LGPL v2.1; no implementation copied or bundled.

- `hdhomerun_config.c`: main_cmd (lines 611–622) accepts `key <uint32>` before get/set;
  cmd_get/cmd_set_internal and main establish error/exit behavior.
- `hdhomerun_device.c`: get_tuner_lockkey_owner (984–993) reads owner information;
  it is **not** a get-the-secret-key interface. Lock request (1264–1289) writes a
  fresh random key through set_with_lockkey; release (1292–1311) sets `none` using
  the owned key. Force (1314 onward) is a distinct operation that WarnBridge never
  calls. Channel/filter/target setters (1069–1222) and generic set_var (1253–1262)
  use keyed writes. Target accepts explicit protocol/IP/port. Stream code supports
  UDP and RTP as separate modes; WarnBridge selects `udp://` and rejects RTP input.
- Local installed CLI/receiver firmware compatibility is still a hardware check.
  WarnBridge rechecks idle state after atomic acquisition, keys every mutation and
  performs no restoration based on stale pre-acquisition settings.

[Command-line documentation](https://info.hdhomerun.com/info/hdhomerun_config): fetch
blocked by proxy CONNECT 403. Interface findings above come from inspected official
source, not an assumed successful documentation fetch.

## Initial direct-fetch failures (historical)

During initial delivery each following URL failed at proxy CONNECT with 403. This is a cloud
network-policy restriction, not evidence that the origin denies the user. Document
version names below come from the supplied references; content and currentness
were not independently verified. No claim that a draft is the latest final.

| Reference | Version/date and relevant investigation | Status / licensing |
|---|---|---|
| [D2WARN](https://d2dtechnologies.com/d2warn/) | manufacturer capabilities | blocked; no text reused |
| [D2WARN manual](https://d2dtechnologies.com/wp-content/uploads/2023/08/PBS-WARN-Manual-Aug-2023-rev-11.pdf) | Aug 2023 rev 11; transport/receiver behavior | blocked; terms unverified |
| [OASIS CAP](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html) | CAP 1.2 OS; alert/info/area, references, Update/Cancel, signatures | blocked; no schemas bundled |
| [IPAWS profile](https://docs.oasis-open.org/emergency/cap/v1.2/ipaws-profile/v1.0/cs01/cap-v1.2-ipaws-profile-cs01.html) | v1.0 cs01; required fields/constraints | blocked; terms unverified |
| [FEMA IDG final](https://content.govdelivery.com/attachments/USDHSFEMA/2024/01/31/file_attachments/2767795/IPAWS-OPEN-v4-02-InterfaceDesignGuide_Final.pdf) | v4.02, Jan 2024 link; CMAC schema/mapping, trust | blocked; not inspected |
| [FEMA IDG draft](https://content.govdelivery.com/attachments/USDHSFEMA/2024/09/11/file_attachments/2994434/IPAWS-OPEN-v4-02-06_InterfaceDesignGuide_Draft.pdf) | v4.02.06, Sep 2024 link; PublicWEA lead | blocked; DRAFT, no usable hostname inferred |
| [ATIS catalog](https://webstore.ansi.org/standards/atis/atis0700037v003) | ATIS-0700037.v003; C–1 framing/header/control | blocked; no purchase or access-control bypass |
| [Older preview](https://store.accuristech.com/products/preview/2002334) | older ATIS preview, version unverified | blocked; no normative definitions inferred |
| [PBS WARN](https://www.pbs.org/about/about-pbs/contact-information/warn/) | public program information | blocked; not treated as a schema/transport specification |

These are initial direct-fetch results, superseded for three documents by the web
tool retrieval below. Still unresolved: authoritative current CMAC XSD/enums, PBS
C–1 unknown fields, current CAP-to-CMAC mapping, applicable signature/trust policy,
actual OTA alert coverage and newer final guidance. User-observed framing remains
the implementation baseline; CAP presentation now also uses the retrieved standard.

## Successful web-tool inspection (November 12, 2026 UTC)

The connected web research tool could retrieve documents unavailable to the initial
shell proxy. Its text extraction was inspected read-only; no full standards text,
third-party implementation, XSD or trust store is copied/bundled. This records an
inspection, not a currentness or complete protocol-conformance claim. The historical
source-access.json continues to describe the initial direct-fetch attempts only.

- [D2WARN manual, August 2023 revision 11](https://d2dtechnologies.com/wp-content/uploads/2023/08/PBS-WARN-Manual-Aug-2023-rev-11.pdf),
  105 PDF pages. Printed page 104 (PDF page 104): PBS NOC sends a short heartbeat
  every 30 seconds; its receiver alarms if absent for 40 seconds. FEMA Link Tests
  are usually every 60 seconds, sometimes 120; intervals are not guaranteed. This
  is manufacturer guidance, not an assertion about the observed byte profile or
  current FEMA schedule. Its rough multi-kilobyte example does not replace the
  user's independently specified 446-byte XML vector. No explanation of a fixed
  2020-dated recurring test was found; caching/templates/redundancy are unverified.
- [OASIS Common Alerting Protocol Version 1.2, OASIS Standard, 1 July 2010](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html),
  sections 3.2.1–3.2.4: alert/info/resource/area fields, status and msgType,
  references, multilingual info, parameters, polygon coordinates and circles.
  Update supersedes referenced earlier messages; Cancel cancels referenced earlier
  messages. Coordinates use latitude,longitude and circle radius uses kilometres.
  The application adds conservative source/sender/time/conflict guards and labels
  the result as declared/unauthenticated. No schema or signature verification is
  inferred from presentation. XSD retrieval/bundling and IPAWS-profile conformance
  remain separate tasks; the standard's existence is not an XSD validation result.
- [FEMA IPAWS-OPEN Interface Design Guidance 4.02 Final](https://content.govdelivery.com/attachments/USDHSFEMA/2024/01/31/file_attachments/2767795/IPAWS-OPEN-v4-02-InterfaceDesignGuide_Final.pdf),
  cover February 2024, 142 PDF pages. Public-feed guidance distinguishes CAP feed
  messages from CMAC C-interface messages. Appendix CAP-to-CMAS transformation
  mapping discusses identifier/sender/sent/status/msgType and references, including
  cancellations without info. This does not establish the exact current CMAC 2.0
  root/leaf fields or enum mapping observed OTA, nor a usable public-feed contract,
  credentials or hostname. No network polling was added.

The older ATIS preview remained inaccessible (HTTP 403), and no paywall was
bypassed. Search snippets/older FCC CMAC examples were not treated as normative
CMAC 2.0 definitions. Non-Link-Test CMAC alerts therefore remain original-field
review, pending a current schema and actual alert sample.

## Historical research only

- [amsilvr/pbswarn](https://github.com/amsilvr/pbswarn), master:
  `ac87823fb0b05d6045e764d923302bc4c418e4f6`, independently confirmed current branch
  tip by ls-remote. Root LICENSE fetch returned 404; that alone cannot prove no
  license elsewhere. Historical R/Shiny characterization remains user-reported.
- [artbotterell/pbswarn](https://github.com/artbotterell/pbswarn), dev:
  `5560f7d3c1a3ccf98ca50d41fb316575f2dfa290`, independently confirmed by ls-remote.
  Pinned `hdhr/tuner/tuner.go` fetched; header explicitly says Copyright 2019 PBS,
  All Rights Reserved. Root LICENSE returned 404. No reuse permission established.
- Additional user-supplied leads: `hdhr/hdhr/hdhr.go`, `client/capture.go`,
  `warnmonitor/warnmonitor.go`, `nextGen/warn_map/index.js`. Prior findings about
  heuristic byte deletion, XML repair and hardcoded posting remain user-reported
  unless explicitly reverified here. They are not implementation dependencies.

WarnBridge was written independently from byte evidence and interface semantics.
No historical source, credentials, connection strings or outbound posting logic
was copied, run or committed.

## Candidate web endpoint and consumer

[warn_out endpoint](https://nmknkohb83.execute-api.us-east-1.amazonaws.com/prod/warn_out)
read-only access attempt was blocked by the cloud proxy. This does not establish
origin status, operator permission, completeness, retention or a supported contract.
No pagination/polling was attempted. A current snapshot cannot represent all events.

[Consumer example](https://github.com/ser401-capstone-chatgpt-WEA/SER401-Capstone-Team-3/blob/US-126/scrape_pbs_warn_api.py)
was fetched as page and raw text. Branch US-126 resolved to
`51b05f3079bb0b4e6895c96447b59a5a37299f10`. Inspected lines 38–110: consumer sends
status/page/per_page, expects alerts and pages metadata, reads next_url but increments
page in requests. These are consumer assumptions, not a validated endpoint contract.
Licensing not established; no code reused or run. Live comparison remains disabled.

## Repository provisioning

GitHub connector metadata reported `bho18/atsc_warn` visibility **public**, size 0,
default branch main (no commits). This conflicts with the requested privacy.
Work is local only; no push/PR/public release. Repository owner must change Settings
→ General → Danger Zone → Change repository visibility → Private before remote
delivery. GitHub CLI metadata was blocked; connector metadata supplied the check.

## Live connectivity follow-up (November 11, 2026 America/Chicago)

The user explicitly approved a public repository, superseding the initial privacy
blocker above. Credentials, private captures and runtime state are still excluded.

Inspected pinned SiliconDust `hdhomerun_config.c` lines 72–165: native `discover`
prints `hdhomerun device <8 hex ID> found at <address>` and uses native discovery
across interfaces. WarnBridge delegates this command instead of using a cloud
directory. IPv4 duplicates are coalesced by device ID.

The local HDHomeRun HTTP `/discover.json` interface supplies DeviceID, ModelNumber
and TunerCount. Reference: https://info.hdhomerun.com/info/http_api . The live adapter
accepts only these safe metadata fields, bounds reads and does not follow device URLs
or redirects. That manufacturer web documentation remains inaccessible under this
cloud network policy; physical device/firmware response shape is unverified here.
HTTP metadata behavior is tested with local mocks; explicit tuner/IP control remains
available when metadata is unavailable. No device authentication field is stored.

## Native UDP video keepalive verification

Pinned SiliconDust source at `dc48af56d3c338288765b263e57129f711dedb9b` was fetched
and inspected during the WSL no-data investigation:

- `hdhomerun_device.c` lines 1370–1398: stream_start sets its target, then registers
  the receiver IP, UDP port 5004 and the owned lock key with its video socket.
- [hdhomerun_video.c](https://github.com/Silicondust/libhdhomerun/blob/dc48af56d3c338288765b263e57129f711dedb9b/hdhomerun_video.c)
  lines 311–339: send a uint32 key from the receiving socket; send immediately and
  repeat every 1000 milliseconds. SHA-256 of retrieved source:
  `7f399d1ce3e68b6fcca60c9e96b67cb9aec4af4f3e9e7bd7ecfb521886345bdb`.
- [hdhomerun_pkt.c](https://github.com/Silicondust/libhdhomerun/blob/dc48af56d3c338288765b263e57129f711dedb9b/hdhomerun_pkt.c)
  lines 153–162: write_u32 serializes in big-endian order. SHA-256:
  `a68d6b4e0248f2d630842d69949f1486d538cf14625655810d5a6063895d124f`.

These independently inspected interface semantics justify a native keepalive in the
Python adapter. Source license remains LGPL-2.1; no C implementation was copied or
bundled. This is a four-byte video-control datagram, not a WARN heartbeat or alert.
Its benefits for this user's WSL/VLAN return path remain a hardware-test hypothesis.

## Open source map engine and reference data (November 12, 2026 UTC)

Leaflet 1.9.4 was retrieved from its official npm distribution and verified against
npm's SHA-512 integrity metadata before copying browser assets. BSD-2-Clause terms
were inspected and retained in web/vendor/leaflet/LICENSE. Natural Earth GeoJSON
and its public-domain license were fetched from the pinned author repository commit
`ca96624a56bd078437bca8184e78163e5039ad19`. The bundled derivative retains only map
reference fields and rounds reference coordinates; alert evidence is untouched.
See maps.md and the bundled provenance manifests for exact URLs/hashes and rebuild
instructions. These are independent public basemap data, not user captures.

The current OSMF raster tile usage policy was inspected using the web tool:
https://operations.osmfoundation.org/policies/tiles/ . Optional street tiles use
its standard HTTPS URL, visible attribution and browser caching/referrer behavior,
without prefetch or offline downloads. Cloud browser tests substitute local mock
images and failures, never fetching real public tiles. Default map rendering makes
no external requests; its reference geography is the separately licensed local data.

## Native CLI in the live Docker image

The Debian trixie hdhomerun-config package built here is `20230719-1+b4`, from
libhdhomerun `20230719-1`. Its installed copyright/license files remain in the image.
Package metadata: https://packages.debian.org/trixie/hdhomerun-config . Debian's
source view was inspected at
https://sources.debian.org/src/libhdhomerun/20230719-1/hdhomerun_config.c/ : main_cmd
accepts the `key <uint32>` prefix before get/set, despite its omission from the
short usage text. This supports the existing owned-key adapter syntax. The image
was checked without networking; real firmware behavior still needs local acceptance.
