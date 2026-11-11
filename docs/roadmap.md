# Delivery status and next bounded task

## Implemented and tested locally

- Strict incremental ATSC 1.0 WARN decoder; independent CRC vectors and corruption,
  loss, adaptation, duplicate and resource-bound tests.
- File/stdin imports, deterministic TS/journal replay, raw UDP ingestion; explicit
  rejection of RTP/unsupported datagram framing, arrival metadata and raw retention.
- HDHomeRun direct-IP owned locks, idle recheck, keyed operations/cleanup, default PID
  filter and explicit full-multiplex diagnostic option, with mocked race tests.
- Immutable observation evidence, exact XML-content deduplication, identity conflict
  flags, CAP references/out-of-order resolution and conservative expiration display.
- SQLite migration, ingestion exclusion, read-only API, offline desktop/mobile UI.
- Locked Python dependencies, idempotent setup, offline validation, Docker and CI.
- Separate saved-web-response import with no network polling or guessed comparison.

## Explicitly deferred/unverified

- **Original 56-packet capture and all physical receiver/VLAN/firmware behavior.**
- Schema validation and cryptographic signature/trust verification: not configured
  or implemented. No authenticity claims. Authoritative document retrieval blocked.
- Normative header/control semantics, other OTA content types and production alerts.
- Automatic CAP update/cancel lifecycle projection; CMAC normalization/lifecycle.
  References/identities/unknown fields are already preserved for later validation.
- Geometry conversion, targeting, geographic relevance and maps.
- RTP, resynchronization, multicast, other tuners and ATSC 3.0.
- Live web comparison: operator policy, completeness, rate limits, pagination,
  redirect rules and defensible mappings must be established before adding polling.
- Automatic reconnect/crash-lock recovery: intentionally no force takeover. Retry
  is a new explicit capture attempt, with full idle/lock checks.
- Containerized HDHomeRun control (the image lacks hdhomerun_config). Use the native
  host capture process initially; container image supports API/replay/raw UDP.
- Alerts/observations need richer archive-scale browsing; detail caps at latest 100.

**Next bounded task:** privately supply the original PID-only file, record SHA-256,
run the baseline comparison without editing expected counts, inspect any divergence,
and then perform one 60-second hardware test on an independently confirmed idle
tuner. Keep authoritative-source retrieval/schema work as a separate follow-on.
