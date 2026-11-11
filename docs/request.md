# Project: WarnBridge — PBS WARN OTA Receiver and Alert Gateway

## 1. Mission and execution instructions

Build a new, self-hosted, offline-first application called WarnBridge.

Its primary function is to receive PBS WARN data from an ordinary ATSC 1.0
television broadcast, recover the messages carried on MPEG-TS PID 0x0911,
validate the observed broadcast encapsulation, parse CMAC and CAP XML,
preserve the original data, and expose useful monitoring and alert information
through a local API and web interface.

This is an implementation task, not merely a request for an architecture
document. Produce a brief implementation plan, then implement and test a
working project in the selected repository.

Start from the experimentally validated transport described below. Do not
restart with ATSC 3.0, propose buying different hardware, or make Internet
access a requirement for receiving OTA messages.

The repository is expected to be a new private repository named `warnbridge`.
Use the selected repository even if its actual name differs. Inspect the
existing workspace before changing anything. Do not overwrite unrelated work.

Do not assume permission or credentials to create another remote repository.
If repository provisioning is incomplete, scaffold what is possible in the
authorized workspace and report the exact missing setup step. Do not invent
a successful push or repository URL.

Make reasonable implementation decisions and document them. Do not stall
on routine preferences. Ask only when a genuinely blocking authorization,
destructive action, or unavailable required input prevents safe progress.

Distinguish:
- Observed facts from the user's real capture.
- Independently reproducible test vectors.
- Experimental interpretations of protocol fields.
- Requirements verified against authoritative documents.
- Features that remain unimplemented or unverified.

This is initially an experimental monitoring application, not a certified
alerting product. It must not automatically issue public warnings, originate
IPAWS messages, operate sirens, or claim authoritative alert authentication.

## 2. Deployment environment and operational constraints

The user's eventual deployment environment is:

- Ubuntu Linux on an AMD64 Lenovo ThinkCentre named `homeserver`.
- Existing Docker services and an existing Caddy reverse proxy.
- Jellyfin already uses the HDHomeRun.
- Receiver: SiliconDust HDHomeRun CONNECT DUO, model HDHR5-2US.
- Two ATSC 1.0 tuners.
- Device firmware reported by the user: 20261107.
- Device IP at the time of the experiment: 192.168.4.159.
- The receiver is on another VLAN.
- Broadcast discovery initially failed across VLANs.
- Direct-IP control and actual transport-stream capture succeeded.
- `hdhomerun_config` is installed on the deployment host.
- TSDuck is not a required dependency.
- Local display timezone: America/Chicago.
- Store timestamps as timezone-aware UTC.

The tested station configuration was:
- WNPT / Nashville PBS.
- Physical RF channel 7.
- `hdhomerun_config ... set /tunerN/channel auto:7`.
- ATSC 1.0 / 8-VSB reception.
- WARN PID: 0x0911, decimal 2321.

These addresses and channels are deployment examples, not universal defaults.
Do not hardcode them into application logic.

Do not assume either tuner is currently free. The previous idle status is
historical. Do not interrupt Jellyfin or take a tuner from another client.

The cloud development environment does not have access to the user's LAN.
Do not attempt to contact 192.168.4.159 from the cloud. Build mocks, replay
fixtures, and integration tests. Supply explicit local verification commands.

Do not:
- Open home-network ports to the Internet.
- Require a VPN or tunnel for initial development.
- Upgrade receiver firmware.
- Change VLAN or firewall configuration.
- Deploy another Caddy instance.
- Change existing Jellyfin settings.
- Commit device authentication values, API credentials, or private captures.

## 3. Current experimental baseline

The user successfully captured roughly four minutes of a full ATSC 1.0
transport stream, extracted PID 0x0911, and ran an experimental Python
validator against the actual recording.

The latest user-reported result was:

```json
{
  "warn_packets": 56,
  "complete_messages": 24,
  "crc_pass": 24,
  "crc_fail": 0,
  "heartbeats": 8,
  "cmac_messages": 16,
  "cap_messages": 0,
  "link_tests": 16,
  "duplicate_xml": 9,
  "unique_xml": 7,
  "continuity_gaps": 0,
  "duplicate_ts_packets": 0,
  "rejected_packets": 0,
  "rejected_messages": 0,
  "incomplete_messages": 0
}
```

The capture contained:
- Eight single-fragment ASCII heartbeat messages.
- Sixteen three-fragment CMAC 2.0 Link Test transmissions.
- Seven distinct XML byte strings.
- Nine repeated XML payloads.
- No native CAP documents.
- No observed actionable public warning in this sample.

The arithmetic is:
8 heartbeat packets + (16 link-test transmissions × 3 packets) = 56 TS packets.

The PID-only file should contain 56 × 188 = 10,528 bytes if it is the exact
unmodified file used for this result.

Known local files on the user's machine:
- `/home/bryan/wnpt-full.ts`
- `/home/bryan/warn-0911.ts`
- `/home/bryan/pbswarn-tools/warn_check.py`
- `/home/bryan/warn-validated-osst72e1/summary.json`
- Other extracted files inside that validation directory.

These paths are NOT automatically available in the cloud workspace.

Do not claim to have run the real capture unless it is actually provided.
Do not invent its hash, upload it, or reconstruct all 56 packets and label
the result as the original recording.

The baseline proves our current transport interpretation works on these
heartbeats and link tests. It does not prove universal protocol compliance,
production-alert coverage, schema validation, or digital-signature validity.

## 4. Experimentally validated transport format

### 4.1 MPEG transport stream

Input is a stream of 188-byte MPEG-TS packets.

Parse TS headers correctly:
- Sync byte 0x47.
- PID.
- Transport error indicator.
- Payload-unit-start indicator.
- Transport scrambling control.
- Adaptation-field control and length.
- Continuity counter.
- Discontinuity indicator where present.

Process PID 0x0911.

Do not assume every packet always has a four-byte header followed immediately
by payload. Handle adaptation fields correctly.

For continuity checking:
- Account for counter wrap from 15 to 0.
- Apply the correct rules to payload-bearing versus adaptation-only packets.
- Recognize exact repeated transport packets without confusing them with
  repeated messages.
- Handle discontinuities explicitly.
- Never silently join fragments across known loss or corruption.

Support arbitrary input read/chunk boundaries, not just reads of exactly
188 bytes. For files, offer strict parsing. Any optional resynchronization
must be explicit and report skipped data.

### 4.2 Per-packet WARN fragmentation header

At the beginning of the TS payload, the observed format is:

| Offset | Size | Interpretation |
|---|---:|---|
| 0 | 4 | Transport identifier, big-endian |
| 4 | 2 | Zero-based fragment index, big-endian |
| 6 | 2 | Last fragment index, inclusive, big-endian |
| 8 | remaining | Fragment content |

Equivalent unpacking:
`struct.unpack(">IHH", payload[:8])`.

A last-fragment value of 2 means three fragments: 0, 1, and 2.

In the observed packets:
- PUSI is set on fragment 0.
- PUSI is clear on continuation fragments.
- The transport identifier is repeated across fragments.

Do not treat the first payload byte as a PSI pointer field for this framing.

Reassemble only the bytes after each eight-byte WARN fragment header.

In packets with no adaptation field:
- TS payload capacity is 184 bytes.
- WARN fragment-content capacity is 176 bytes.

Support bounded assembly state. Enforce configurable size, fragment-count,
pending-message, and timeout limits. Identify these as application safety
limits, not as limits mandated by a standard we have not obtained.

Do not assume the transport identifier is globally unique. Avoid merging
different transmissions because they share an ID. If ordering or interleaving
is ambiguous, preserve the evidence and reject or quarantine the ambiguous
assembly rather than guessing.

### 4.3 Assembled message header and body

After removing all fragmentation headers and concatenating the fragment
content, the observed message starts with a 13-byte header:

| Offset | Size | Observation |
|---|---:|---|
| 0 | 1 | 0x2F in the validated samples |
| 1 | 1 | 0x00 for sampled CMAC link tests; 0x03 for heartbeats |
| 2–3 | 2 | 0x00FF in the sampled messages |
| 4–7 | 4 | Repeated transport identifier |
| 8 | 1 | 0x00 in the sampled messages |
| 9–12 | 4 | Body length, big-endian |
| 13 onward | body length | Exact message body |
| immediately afterward | 4 | CRC, big-endian |
| remaining fragment capacity | variable | 0xFF stuffing |

Preserve these header bytes and expose unknown fields as raw values.

Do not invent normative names or content-type enumerations for the unknown
header fields. In particular, do not assume 0x2F is fully understood or that
the high nibble conclusively identifies a specified protocol version.

The sampled CMAC body includes exactly one terminal NUL after the XML.
That NUL is included in the body length and CRC calculation.

Preserve the body byte-for-byte. Create a separate XML parsing view that
removes the observed terminal NUL where appropriate. Never strip arbitrary
NULs, padding, whitespace, or invalid characters from inside the body.

The heartbeat body is exactly:
`Heartbeat Message`

It is 17 ASCII bytes and, in this observed format, is not followed by a
terminal NUL within the declared body.

### 4.4 CRC model

The experimentally matching CRC is CRC-32/MPEG-2:

- Width: 32 bits.
- Polynomial: 0x04C11DB7.
- Initial value: 0xFFFFFFFF.
- Reflect input: false.
- Reflect output: false.
- Final XOR: 0x00000000.
- Stored CRC byte order: big-endian.

Calculate over:
13-byte assembled message header + exact declared body.

Exclude:
- MPEG-TS headers.
- Per-packet eight-byte WARN fragmentation headers.
- The stored CRC itself.
- Trailing 0xFF stuffing.

Appending the correctly stored CRC produces a zero residue for the supplied
test vector.

Do not substitute ordinary `zlib.crc32()`.

A CRC match is transport integrity evidence, not proof of authenticity.

### 4.5 Transport IDs and timestamps

Several non-heartbeat IDs are consistent with Unix seconds:
`0x6af3c24c` corresponds to 2026-11-11T01:18:04Z.

This interpretation remains empirical. Preserve the original integer and hex
representation regardless of whether it can be interpreted as a timestamp.

Heartbeat ID 0x00000411 is not to be displayed as a meaningful current
transport timestamp.

Repeated XML sometimes has the same transport ID, sometimes different IDs.
Do not use this field as the sole deduplication key.

Keep distinct:
- Local reception time.
- Capture processing/import time.
- Inferred transport timestamp.
- XML-declared sent time.
- Optional external API observation time.

A raw TS file without timing metadata does not provide actual packet
arrival times. Use null/unknown, not the current clock or file mtime.

Some captured link-test XML has a sent timestamp from November 30, 2020.
Do not rewrite it, discard it silently, or mistake its reception for a fresh
public warning.

## 5. Reproducible golden vectors

Implement these as independently specified regression fixtures. Do not
generate the expected CRC using the same function being tested.

### 5.1 CMAC link-test vector

The following Python literal gives the exact reconstructed XML bytes.
Adjacent byte-string literals concatenate without adding whitespace.

```python
XML = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b'<CMAC_Alert_Attributes xmlns="cmac:2.0">'
    b'<CMAC_protocol_version>2.0</CMAC_protocol_version>'
    b'<CMAC_sending_gateway_id>http://integration.aws.fema.gov'
    b'</CMAC_sending_gateway_id>'
    b'<CMAC_message_number>b440b6c8</CMAC_message_number>'
    b'<CMAC_sent_date_time>2026-11-11T01:18:00Z'
    b'</CMAC_sent_date_time>'
    b'<CMAC_status>System</CMAC_status>'
    b'<CMAC_message_type>Link Test</CMAC_message_type>'
    b'</CMAC_Alert_Attributes>'
)

HEADER = bytes.fromhex(
    "2f 00 00 ff 6a f3 c2 4c 00 00 00 01 bf"
)
BODY = XML + b"\x00"
STORED_CRC = bytes.fromhex("d0 ca e4 ef")

assert len(XML) == 446
assert len(HEADER) == 13
assert len(BODY) == 447
assert len(HEADER + BODY + STORED_CRC) == 464
```

Required CRC results:
- CRC(HEADER + BODY) = 0xD0CAE4EF.
- CRC(HEADER + BODY + STORED_CRC) = 0x00000000.
- CRC(b"123456789") = 0x0376E6E7.

For a synthetic TS fixture:
- Append 64 bytes of 0xFF to the 464-byte message.
- Split into three 176-byte fragment-content regions.
- Prepend the eight-byte fragment header to each.
- Use transport ID 0x6AF3C24C.
- Fragment indices 0, 1, 2; last index 2.
- Use PID 0x0911.
- Set PUSI only on fragment 0.
- Use payload-only TS packets.
- Use continuity counters 14, 15, 0 to exercise wraparound.

Label this a reconstructed/synthetic fixture, not the original OTA capture.

### 5.2 Heartbeat vector

```python
HEADER = bytes.fromhex(
    "2f 03 00 ff 00 00 04 11 00 00 00 00 11"
)
BODY = b"Heartbeat Message"
STORED_CRC = bytes.fromhex("7d 34 fe 4a")

assert len(BODY) == 17
```

CRC(HEADER + BODY) must equal 0x7D34FE4A.

Transport ID: 0x00000411.
Fragment index: 0.
Last fragment index: 0.
Pad unused fragment capacity with 0xFF.

## 6. Source material and research policy

Maintain `docs/sources.md` with URLs, document versions/dates, access dates,
repository refs/commit IDs, relevant sections, licensing observations,
findings, and unresolved questions.

Re-fetch and inspect the sources rather than assuming earlier summaries are
authoritative. Do not let documentation retrieval block implementation of
the validated transport.

### Manufacturer and protocol references

SiliconDust command-line documentation:
https://info.hdhomerun.com/info/hdhomerun_config

SiliconDust library/source:
https://github.com/Silicondust/libhdhomerun

D2WARN manufacturer information:
https://d2dtechnologies.com/d2warn/

D2WARN August 2023 manual:
https://d2dtechnologies.com/wp-content/uploads/2023/08/PBS-WARN-Manual-Aug-2023-rev-11.pdf

OASIS CAP 1.2:
https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html

IPAWS CAP Profile:
https://docs.oasis-open.org/emergency/cap/v1.2/ipaws-profile/v1.0/cs01/cap-v1.2-ipaws-profile-cs01.html

FEMA IPAWS-OPEN IDG v4.02 final:
https://content.govdelivery.com/attachments/USDHSFEMA/2024/01/31/file_attachments/2767795/IPAWS-OPEN-v4-02-InterfaceDesignGuide_Final.pdf

FEMA IPAWS-OPEN IDG v4.02.06 draft:
https://content.govdelivery.com/attachments/USDHSFEMA/2024/09/11/file_attachments/2994434/IPAWS-OPEN-v4-02-06_InterfaceDesignGuide_Draft.pdf

ATIS-0700037.v003 catalog:
https://webstore.ansi.org/standards/atis/atis0700037v003

Older ATIS preview:
https://store.accuristech.com/products/preview/2002334

PBS WARN public information:
https://www.pbs.org/about/about-pbs/contact-information/warn/

Do not call a draft the latest final standard. Verify newer guidance when
possible and record the limits of what is publicly accessible.

Research priorities:
- Authoritative CMAC schema and message-type semantics.
- PBS C–1 transport documentation and header/control-field definitions.
- CAP-to-CMAC mappings.
- Update/cancel/reference semantics.
- Signature and trust requirements applicable to received messages.
- Whether full CAP and other content types are currently carried OTA.

Do not bypass access controls or paywalls. Do not purchase standards or
contact PBS/FEMA/ATIS on my behalf without additional authorization.

### Historical repositories

https://github.com/amsilvr/pbswarn
https://github.com/artbotterell/pbswarn

Prior research identified:
- `amsilvr/pbswarn`: historical R/Shiny analysis, branch `master`;
  examined tip ac87823fb0b05d6045e764d923302bc4c418e4f6.
- `artbotterell/pbswarn`: branch `dev`;
  examined tip 5560f7d3c1a3ccf98ca50d41fb316575f2dfa290.
- Relevant fork paths:
  - hdhr/tuner/tuner.go
  - hdhr/hdhr/hdhr.go
  - client/capture.go
  - warnmonitor/warnmonitor.go
  - nextGen/warn_map/index.js

These are research references, not a codebase to run unchanged.

Prior inspection found heuristic byte deletion, repaired closing tags,
incomplete CMAC treatment, and hardcoded outbound posting destinations.
Some files contain PBS copyright notices marked "All Rights Reserved."

Confirm licensing before reuse. Write the receiver independently from the
observed protocol and authoritative specifications. Do not copy old code
merely because it is publicly viewable.

Never run historical scripts that POST received data to third-party systems.
Do not use any credentials or database connection information found there.

### Candidate web comparison endpoint

https://nmknkohb83.execute-api.us-east-1.amazonaws.com/prod/warn_out

Consumer example:
https://github.com/ser401-capstone-chatgpt-WEA/SER401-Capstone-Team-3/blob/US-126/scrape_pbs_warn_api.py

The consumer requests `/warn_out/` with `status`, `page`, and `per_page`,
and expects JSON containing alerts and pagination-related metadata.

Treat those as consumer assumptions to verify, not a supported API contract.

The operator, public integration policy, rate limits, retention, completeness,
and relationship to the OTA feed remain unverified. Earlier research access
received a 403 for one URL variant. Do not conclude either permanent failure
or unrestricted public authorization from that observation.

Do not assume this endpoint supplies all IPAWS alerts or all WARN transport
events. An active-alert snapshot is not a complete event log.

The FEMA draft's documented PublicWEA CAP feed is another research lead.
Do not invent a usable hostname or assume authorization.

## 7. Preferred implementation approach

Use:
- Python 3.12+ for the receiver and protocol core.
- A typed, modular Python package with a CLI.
- FastAPI or a comparably lightweight API framework.
- SQLite for initial persistence, with explicit migrations.
- A small, locally served web UI.
- pytest and appropriate lint/type-check tools.
- Docker Compose for deployment.
- Reproducible dependency locking.

Keep the protocol decoder usable without the web server.

Prefer a modular single application over unnecessary microservices.
Do not add Redis, Kafka, Kubernetes, cloud infrastructure, or an LLM to the
receive/decode path.

A suggested layout:

```text
AGENTS.md
README.md
pyproject.toml
dependency lockfile
src/warnbridge/
  cli.py
  config.py
  inputs/
  transport/
  formats/
  domain/
  storage/
  api/
  web/
tests/
  unit/
  integration/
  fixtures/
docs/
  architecture.md
  protocol.md
  evidence.md
  sources.md
  deployment.md
  development.md
  validation.md
  roadmap.md
scripts/
config/
Dockerfile
compose.yaml
.github/workflows/
```

Adjust the structure when justified, but keep clear boundaries between
transport, message parsing, persistence, receiver control, and presentation.

## 8. Required receiver and data-processing capabilities

### 8.1 Inputs

Implement:
- Offline MPEG-TS file decoding.
- Streaming stdin input.
- UDP MPEG-TS ingestion.
- A controlled HDHomeRun input adapter.
- Deterministic replay for development and demonstration.

Use the actual received UDP byte count. Do not parse unused receive-buffer
capacity. Do not assume every datagram contains seven packets.

Raw MPEG-TS over UDP and RTP-wrapped transport are different inputs.
Implement explicit RTP handling if supported; otherwise clearly reject it.
Do not strip a guessed fixed-length UDP/RTP prefix.

For live capture, record local UTC and monotonic arrival timestamps,
source/receiver identity, datagram or chunk offsets, and transport diagnostics.

Provide rotating raw captures or equivalent replayable records with bounded
retention. Preserve enough timing metadata to reproduce arrival order.

A replay must be labeled as replay. Replaying an old alert must not make it
a newly received live warning or trigger default operational notifications.

### 8.2 HDHomeRun control

Use documented SiliconDust interfaces. Verify lock and stream-control
semantics from official documentation/source rather than guessing.

Require explicit host and tuner selection for capture.
Support direct-IP addressing without requiring broadcast discovery.

Before tuning:
- Inspect current tuner status, target, and lock state.
- Acquire an appropriate owned lock/lease where supported.
- Refuse a busy or foreign-owned tuner.
- Account for races between checking availability and taking control.

Never force-clear another application's lock.

On exit, signal, failure, or reconnect:
- Stop streams owned by this application.
- Release only the lock this application owns.
- Do not restore stale settings over another client's newer ownership.
- Explain and test recovery behavior.

Use safe subprocess argument arrays, timeouts, and checked return codes if
calling `hdhomerun_config`. Do not interpolate shell commands.

Use a WARN-only PID filter for routine capture once configured. Retain an
explicit full-multiplex diagnostic mode.

Provide configurable bind/return IP and UDP port for cross-VLAN operation.
Do not use hardcoded `eth0` parsing or require mDNS.

Mock this adapter in cloud tests. Hardware tests must be explicitly opt-in
and must never run in CI automatically.

### 8.3 Preservation and validation

Retain:
- Original TS packet data or references into capture files.
- Original reassembled message bytes.
- Exact header bytes.
- Exact declared body.
- Stored and calculated CRC.
- Original XML bytes, separately from parsed fields.
- Validation results and failure reasons.

Rejected data must not become an accepted alert. Preserve bounded diagnostic
evidence and counters rather than silently dropping every failure.

Track distinct states for:
- Transport validity.
- XML well-formedness.
- Schema validation.
- Signature verification.
- Application classification.
- Geographic relevance.

Unknown, unavailable, not checked, invalid, and valid are different states.

A missing XSD or trust store must result in "not configured"/"not checked",
not a green "validated" result.

### 8.4 XML parsing

Dispatch by namespace and root:
- CMAC: `{cmac:2.0}CMAC_Alert_Attributes`
- CAP: `{urn:oasis:names:tc:emergency:cap:1.2}alert`
- Other roots/namespaces: preserve as unsupported/unknown.

Support namespace prefixes, not only a default namespace.

Use hardened parsing:
- Disable external entities and external resource retrieval.
- Reject or safely disable DTD processing.
- Bound document size, depth, and element counts.
- Never fetch arbitrary URLs found in XML.
- Escape untrusted text in the UI.

Do not repair XML tags or silently remove invalid characters.

Preserve repeated structures:
- Multiple CAP info blocks and languages.
- Multiple areas, polygons, circles, geocodes, parameters, and references.
- Unknown extension fields and their namespaces.
- Relevant element order and attributes.

Do not flatten the document into a single dictionary keyed by local tag name.

Keep original signed XML unchanged. If signature verification is later added,
use a maintained implementation and a configured trust policy. Do not assume
the presence of a Signature element proves authenticity.

### 8.5 Message classification and lifecycle

Identify heartbeat, CMAC Link Test, CAP, other CMAC, and unknown messages.

The sample CMAC messages are:
- CMAC_status = System
- CMAC_message_type = Link Test

Do not classify every CMAC document as a heartbeat.
Do not treat Test, System, Exercise, or Draft messages as actual public alerts.

Keep protocol-specific enum mappings. Do not assume CAP and CMAC use exactly
the same names or reference formats.

For native CAP, preserve at least:
- identifier, sender, sent
- status, msgType, scope
- references
- all info blocks
- event, eventCode, category, responseType
- urgency, severity, certainty
- effective, onset, expires
- senderName, headline, description, instruction
- all parameter values, including WEA-related parameters
- area descriptions and geometry

Preserve CMAC field names and values before attempting normalization.

Build separate concepts for:
1. A delivery/reception observation.
2. A protocol message and its content.
3. An alert lifecycle and relationships.

Repeated reception should not create repeated actionable alerts, but it must
remain visible in delivery history.

Use raw-byte SHA-256 for exact-content deduplication alongside protocol
identifiers. Do not deduplicate solely by text, transport ID, or sent time.

For CAP, preserve the sender/identifier/sent identity and reference tuples.
If identical logical identifiers carry different content, flag the conflict
rather than overwriting the earlier message.

Implement update/cancel/expiration behavior only where the semantics are
established. Preserve unresolved references and out-of-order arrivals.

Do not infer cancellation merely because an alert disappears from an API
snapshot.

### 8.6 Geographic processing

Retain original geometry and geocodes.

Where geometry conversion is implemented:
- Account explicitly for CAP latitude/longitude ordering versus GeoJSON.
- Handle circles and their stated units.
- Preserve leading zeros in SAME/FIPS-style values.
- Preserve separate areas rather than flattening their associations.
- Do not substitute bounding boxes or county polygons without labeling
  those as derived representations.

Do not assume all received alerts concern the station's geographic market.
Geographic filtering belongs after message reception and parsing.

Defer unsupported targeting semantics honestly rather than guessing.

## 9. Persistence, API, and user interface

Use SQLite initially with migrations, appropriate indexing, bounded writes,
and a clear ingestion concurrency model.

Avoid accidentally starting multiple receiver workers because an HTTP server
uses multiple processes or hot reload.

Persist messages, observations, validation outcomes, relationships, receiver
sessions, and health events. Avoid destructive replacement of raw evidence.

Suggested read-only API:
- `/api/v1/health`
- `/api/v1/receivers`
- `/api/v1/messages`
- `/api/v1/messages/{id}`
- `/api/v1/messages/{id}/raw`
- `/api/v1/alerts`
- `/api/v1/metrics`
- An event stream if useful.

Use stable IDs, pagination, filters, and explicit source/provenance fields.
Do not expose arbitrary filesystem paths through raw-file routes.

The initial UI should show:
- Receiver/capture status.
- Last observed heartbeat.
- Last received link test.
- Message counts and validation failures.
- Latest messages with classification and duplicate counts.
- Raw XML/text and decoded fields.
- Separate indicators for integrity, schema, and signature state.
- Capture/replay/live source labeling.

Make health distinctions explicit:
- RF/tuner availability.
- TS reception.
- PBS heartbeat reception.
- CMAC link-test reception.
- Recent new message content.
- Optional web-comparison availability.

A heartbeat alone must not produce a claim that current end-to-end public
warning delivery is fully operational.

All essential UI assets must work offline. Do not require CDNs, online fonts,
remote JavaScript, analytics, or map tiles for core operation.

Default the API to loopback access. Document deliberate LAN exposure through
the user's existing reverse proxy. Do not expose tuner-control actions
through an unauthenticated browser interface.

## 10. Optional web comparison integration

Design this as a separate adapter, disabled by default.

It may initially support importing saved JSON responses, with live polling
added only after response shape and allowed use are established.

Requirements:
- Configurable, explicitly enabled endpoint.
- Read-only requests.
- Request timeouts and response-size limits.
- Conservative configurable polling.
- Backoff and Retry-After handling.
- Bounded pagination.
- Detection of repeated pages and duplicate results.
- Validation of allowed hosts and redirects.
- No requests to hidden/admin/write endpoints.
- No upload of local captures or decoded messages.

Do not blindly reuse the student scraper's pagination logic.
Document which behavior is observed and which is contractual.

Record web observations separately from OTA observations.
Do not silently fill missing OTA records with web results and report the
radio receiver as successful.

Compare identifiers, timestamps, text variants, and areas where a defensible
mapping exists. Surface "not comparable" when mappings are missing.

An online service failure must never stop OTA reception.

CI must not poll the live WARN endpoint or require Internet connectivity
after development dependencies have been installed.

## 11. CLI and deployment expectations

Provide a discoverable CLI with useful help and nonzero error exits.

Suggested commands:
- `warnbridge decode INPUT --out OUTPUT`
- `warnbridge replay INPUT ...`
- `warnbridge capture --config CONFIG`
- `warnbridge serve --config CONFIG`
- `warnbridge doctor --config CONFIG`

`doctor` should be non-mutating unless a separate explicit test flag permits
a carefully documented capture test.

Preserve compatibility with the baseline summary field names where sensible,
or document a clear mapping.

Supply:
- Example configuration without secrets.
- Idempotent development setup.
- Test/lint/type-check commands.
- Dockerfile and Compose configuration.
- Persistent-data volume documentation.
- Graceful shutdown and restart behavior.
- Log and raw-capture retention controls.
- Backup/restore instructions.
- A real-hardware validation runbook.

The default cloud/demo configuration must use local replay fixtures, not
attempt to tune hardware or poll external services.

Do not run privileged containers without a demonstrated requirement.

Explain Docker networking for UDP return traffic across VLANs. If host
networking is offered as a Linux deployment option, make it explicit and
separate from the default replay configuration.

If Docker cannot actually run in the cloud workspace, validate what is
possible and clearly mark image/runtime verification as not executed.

## 12. Test requirements

Tests must be executable offline and must verify behavior, not only imports
or mocked success responses.

Include:

Transport:
- The supplied independent CRC vectors.
- Fragment assembly and message-length extraction.
- 0xFF stuffing.
- Continuity wrap.
- Adaptation fields and adaptation-only packets.
- Explicit discontinuities.
- Truncated packets and arbitrary input chunk boundaries.
- Missing, repeated, conflicting, and malformed fragments.
- Exact repeated TS packets versus repeated complete messages.
- CRC corruption.
- TEI and scrambling rejection.
- Inconsistent inner/outer IDs.
- Oversized lengths and resource-limit enforcement.
- Unknown header values without silent reinterpretation.

XML/application:
- The exact CMAC Link Test vector.
- Distinguishing System/Link Test from actual alerts.
- CAP fixtures with multiple languages and multiple areas.
- Namespace-prefixed equivalents.
- Repeated parameters and extensions.
- Malformed XML, DTD/entity attempts, and excessive nesting.
- Preservation of original XML bytes.
- Duplicate deliveries with same or different transport IDs.
- Stale sent timestamps.
- Updates/cancellations and unresolved references where implemented.
- No inferred receive time for timestamp-free files.

Infrastructure:
- Storage migrations and restart behavior.
- Replay-to-database-to-API integration.
- Bounded malformed-input handling.
- Graceful shutdown.
- Simulated tuner busy/lock conflicts.
- No foreign-lock release.
- UDP read-length handling.
- API/UI escaping and raw-file access restrictions.
- Optional web adapter with local mocked responses only.
- No default Internet dependency or public notification side effects.

Clearly label every fixture as:
- Reconstructed from supplied byte/text evidence.
- Synthetic.
- Authoritative published example, with source/license.
- Actual user capture, only when genuinely supplied.

Do not hardcode the real-capture expected counts into the decoder.

Once the actual 56-packet file is provided, run it as a separate acceptance
test against the baseline above and record its hash. Until then, report:
"Real-capture validation pending; user previously reported successful
validation with the experimental decoder."

## 13. Initial delivery scope and priorities

Implement in this order:

1. Repository setup, durable evidence documentation, golden fixtures, and
   tested transport decoder.
2. File/stdin/replay inputs, exact-byte preservation, structured output,
   and persistence.
3. UDP ingestion and safely controlled HDHomeRun adapter with mocked tests.
4. Read-only API, receiver health, and a usable offline message-inspection UI.
5. Docker deployment, CI, operational documentation, and local acceptance
   commands.
6. Optional comparison adapter and deeper standards conformance.

The first delivery should contain a runnable end-to-end offline/replay system,
not just scaffolding or a roadmap. It should also include the live-input
implementation and honest hardware-testing limitations.

Do not delay that delivery indefinitely while searching for a paid standard,
waiting for an actual emergency alert, or building an elaborate frontend.

Document advanced schema/signature work and any unresolved CMAC lifecycle
semantics as explicit follow-on work. Do not disguise missing validation as
implemented functionality.

Future extensions may include MQTT, Home Assistant, additional tuner types,
multi-station comparison, and separate ATSC 3.0 inputs. Keep extension points
reasonable, but do not implement those at the expense of the validated
ATSC 1.0 receiver.

## 14. Reproducible cloud development and durable project knowledge

Create a concise root `AGENTS.md` containing:
- Project purpose.
- Build/test commands.
- Critical safety and evidence-preservation rules.
- Links to detailed project documents.
- Required validation before completion.

Do not place the entire research history into AGENTS.md. Put detailed
material in the docs directory.

Record the supplied empirical baseline and golden vectors in versioned
documentation so later Codex tasks do not need this chat.

Maintain:
- `docs/evidence.md`: observed facts, provenance, and confidence.
- `docs/protocol.md`: supported byte layouts and open questions.
- `docs/sources.md`: authoritative references and historical code leads.
- `docs/validation.md`: commands actually executed and outcomes.
- `docs/roadmap.md`: implementation status and remaining work.
- `docs/development.md`: fresh-environment setup and troubleshooting.

Provide an idempotent setup script and a fresh-checkout validation script.
Do not depend on uncommitted files or saved VM state.

Ignore runtime databases, captures, credentials, local environment files,
and bulky logs by default. Commit only intentional fixtures and useful
validation summaries.

Keep the repository private. Do not publish packages, container images,
releases, external telemetry, or actual user captures without permission.
Record licensing provenance; do not assume historical PBS code is licensed
for unrestricted reuse.

Use a review branch and normal authorized Git/Codex delivery mechanisms.
Do not force-push, rewrite unrelated history, or claim a push succeeded if
it did not. Do not request that I paste credentials into source files.

## 15. Completion report

At the end of the task, report:

1. What was implemented and the important repository paths.
2. The actual dependency/runtime choices.
3. Commands executed, test counts, and real results.
4. What was verified using golden vectors or synthetic fixtures.
5. What still needs the user's original capture or physical receiver.
6. Exact commands to clone/install/run the project on `homeserver`.
7. A safe next local validation sequence that does not commandeer a busy
   Jellyfin tuner.
8. Known limitations and the next bounded development task.
9. Commit/branch/PR details only when those actions actually succeeded.

Never equate:
- Parseable XML with schema-valid XML.
- CRC validity with cryptographic authenticity.
- A recent heartbeat with a newly issued public warning.
- A web API observation with OTA reception.
- Synthetic fixture success with a hardware test.
- An unavailable schema with a successful validation.

Begin by inspecting the repository, recording this evidence, and implementing
the golden-vector tests and transport decoder. Then continue through the
working receive/replay, storage, API, and deployment path.