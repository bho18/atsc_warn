# Evidence and provenance

Evidence recorded November 10, 2026 (America/Chicago; execution date November 11 UTC).
The supplied request is preserved in [request.md](request.md). It is a user report,
not an independently verified standards document. No original private capture was
available in this workspace and none was uploaded or reconstructed as an original.

**Real-capture validation pending; user previously reported successful validation
with the experimental decoder.**

## Reported OTA experiment

WNPT Nashville PBS, physical RF 7, ATSC 1.0/8-VSB, PID 0x0911. HDHomeRun CONNECT
DUO HDHR5-2US, reported firmware 20261107. Direct-IP control/capture worked across
VLANs; broadcast discovery did not. Receiver IP/channel/idle status are historical
examples, never current availability evidence. Jellyfin shares the receiver.

The user reported 56 packets, 24 complete messages, 24 CRC passes, zero CRC failures,
8 heartbeats, 16 CMAC messages, 0 CAP messages, 16 Link Tests, 9 duplicate XML and
7 unique XML. Continuity gaps, duplicate TS packets, rejected packets/messages,
and incomplete messages were all zero. See [baseline.json](baseline.json).

Arithmetic: 8 + 16×3 = 56 packets; 56×188 = 10,528 bytes. The report concerned about
four minutes of a full multiplex capture, followed by PID extraction. The local
paths in request.md are unavailable in cloud. No hash is claimed for them.
Old XML sent times (including November 30, 2020) must remain unchanged.

## Independently specified vectors

`tests/fixtures/golden.py` transcribes exact user-supplied XML/header/CRC literals.
Expected CRC constants are not produced by the implementation under test:

| Input | Expected CRC-32/MPEG-2 |
|---|---|
| ASCII `123456789` | `0376E6E7` |
| 13-byte CMAC header + 447-byte body | `D0CAE4EF` |
| Same bytes + big-endian stored CRC | `00000000` |
| Heartbeat header + 17 ASCII bytes | `7D34FE4A` |

CMAC XML is 446 bytes; body adds exactly one terminal NUL. Header is
`2f0000ff6af3c24c00000001bf`; message including CRC is 464 bytes, followed by 64 FF
stuffing bytes. Three synthetic payload-only TS packets use CC 14,15,0. Heartbeat
header is `2f0300ff000004110000000011`; exact body is `Heartbeat Message`.

`reconstructed.ts` contains those three packets plus one heartbeat at CC 1: **four
packets (752 bytes), two messages**, not the original 56-packet recording. Packet
construction is synthetic; constituent XML/header/CRC bytes derive from supplied
evidence. `cap.xml`, synthetic wrappers, corruption cases and mocked device
responses are invented test data. CAP fixture is not a published/schema-valid
example, a signed alert, or a recorded OTA message.

## Confidence boundaries

- Observed framing interpretation matches independent supplied CRC vectors and
  user-reported sample results; broader broadcast coverage remains unverified.
- Transport ID as Unix seconds is empirical. `6af3c24c` maps to
  `2026-11-11T01:18:04Z`; `00000411` is not a useful heartbeat timestamp.
- Official SiliconDust source was re-fetched and inspected for lock/control rules.
- Initial direct document fetches were blocked. On November 12, the web research
  tool retrieved the manufacturer manual, OASIS CAP 1.2 and FEMA IDG 4.02; see
  sources.md. Current CMAC schema/transport/trust verification is still incomplete.
  No schema/signature success claim.
- A valid CRC is not authentication; parseable XML is not schema validation;
  a heartbeat is not evidence of successful public-warning delivery.

## User-reported live WSL test

The user reported HDHR5-2US ID 10652CEC at 192.168.4.159, both tuners initially idle,
and a successful owned tune of tuner 0 to auto:7. After settling, status was
`lock=8vsb ss=100 snq=100 seq=100 bps=4512 pps=2`. Return target was
`udp://192.168.1.21:5000`; Windows confirmed that address belonged to Wi-Fi, and
WSL reported mirrored mode. Linux showed WarnBridge bound at 0.0.0.0:5000 but
packet capture observed no incoming UDP at that port. WSL's effective Hyper-V
firewall defaulted inbound to Block with no listed UDP 5000 allow. The user then
authorized one source-scoped allow rule, but a later attempt still received no TS.
The user has not supplied the effective rule after creation or a Windows NIC trace.

These reports establish RF lock/control and absence of packets at the Linux capture
point in those attempts, not the exclusive network cause. A source inspection then
established a software omission: our adapter did not send native UDP video keepalives.
The adapter now does; whether that resolves the physical WSL/VLAN case remains
unverified. No original transport recording from these runs has been provided.

## User-verified live WSL reception after the keepalive correction

The user supplied terminal output from the update to `b61a689` and a separate
packet-header trace. These are real-device observations provided by the user,
not a cloud hardware run or a raw TS recording. The terminal explicitly reported
`source=live_hdhomerun` and `raw_recording=false`.

The complete JSON records in the pasted excerpt contain 20 accepted deliveries:
7 heartbeats and 13 CMAC System/Link Tests, with 6 distinct content IDs (5 CMAC XML
bodies and one heartbeat body). Fifteen deliveries are flagged duplicates against
the persistent archive; these flags include content seen before this excerpt.
Every complete message record reports transport=valid; the 13 XML messages report
well_formed. The decoded base64 bodies independently match the shown XML views and
SHA-256 content IDs. This does not independently recalculate transport CRCs: raw
assembled headers/stored CRCs are absent from the pasted JSON.

Complete deliveries span 2026-11-12T01:18:29.355597Z to 01:21:32.178749Z
(November 11, 2026, 7:18–7:21 PM America/Chicago). The paste ends partway through
another JSON line and contains no final summary, so these are excerpt counts,
not final run totals or a complete continuity/loss assessment. No complete rejected
record is present. Some Link Tests retain a 2020 XML sent time; their current
reception does not make them current public warnings. No native CAP/public alert
is shown; schema remains not_configured and signature not_checked.

The separate trace contains 76 outgoing four-byte UDP keepalives and 17 incoming
1316-byte UDP datagrams. The two logs cover different intervals; these counts must
not be treated as one aligned capture. Incoming packets use receiver UDP 5004 to
the listener's UDP 5000, confirming a working return path into mirrored WSL in this
run. A 1316-byte payload is seven 188-byte packet slots, not evidence of full-multiplex
recording. Raw packet contents/PIDs cannot be recovered from these header-only lines.

The overall direct-IP live receive/decode path now has user-supplied hardware
acceptance evidence. Success followed the keepalive patch with the earlier firewall
exception in place; the logs do not isolate the independent contribution of each.
Physical busy-tuner races, shutdown cleanup and unattended reliability remain
separate acceptance checks. Original 56-packet recording validation remains pending.
Neither supplied raw log is committed or published; only this aggregate evidence
summary is versioned.

## Alert-focused follow-up (November 12, 2026 UTC)

The user reports steady heartbeat/Link Test traffic and requests an alert-focused
view. No actual alert XML/TS has been supplied or received in the cloud. Synthetic
CAP and CMAC examples exercise transport ingestion and presentation, not OTA alert
coverage, current CMAC schema validity or authenticity. The new alert-demo.ts is
separate from both the independent vectors and the missing original recording.

The D2WARN manual revision 11, printed page 104, describes PBS NOC heartbeat checks
at 30-second intervals and FEMA Link Tests usually every 60 seconds, sometimes 120.
This distinguishes their broad purposes; it does not explain the user's repeated
2020-dated Link Test template. Different message numbers/sent times/content produce
different exact-content records; counts alone cannot establish loss, origin-side
retransmission policy or distinct test functions. Those remain unverified.
