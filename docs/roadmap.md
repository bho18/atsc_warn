# Delivery status and next bounded task

## Implemented and tested locally

- Strict incremental ATSC 1.0 WARN decoder; independent CRC vectors and corruption,
  loss, adaptation, duplicate and resource-bound tests.
- File/stdin imports, deterministic TS/journal replay, raw UDP ingestion; explicit
  rejection of RTP/unsupported datagram framing, arrival metadata and raw retention.
- Native HDHomeRun discovery, direct IP, tuner inventory and auto idle leases,
  live JSONL output, raw journaling off by default, owned locks and default PID
  filter and explicit full-multiplex diagnostic option, with mocked race tests.
- Immutable observation evidence, exact XML-content deduplication, identity conflict
  flags, CAP references/out-of-order resolution and conservative expiration display.
- SQLite migrations, ingestion exclusion, read-only API, offline desktop/mobile UI.
- Background RF polling/freshness states, individual delivery and grouped content
  views, source-scoped counts and paginated reception history.
- Locked Python dependencies, idempotent setup, offline validation, Docker and CI.
- Separate saved-web-response import with no network polling or guessed comparison.

## User-verified hardware milestone

User-supplied logs after b61a689 confirm direct-IP HDHR5-2US reception of live
heartbeats and CMAC Link Tests in mirrored WSL, with incoming UDP and valid decoded
transport. See evidence.md for exact excerpt counts and provenance. The original
56-packet TS file and broader hardware lifecycle/reliability checks remain separate.

## Explicitly deferred/unverified

- **Original 56-packet capture, broader firmware coverage, physical busy-tuner races,
  shutdown cleanup and unattended reliability.**
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
- Legacy detail embeds at most 100 observations; the new paginated delivery API/UI
  exposes full history. Archive retention/large-scale query tuning remains future work.

**Next bounded task:** privately supply the original PID-only file, record SHA-256,
run the baseline comparison without editing expected counts, inspect any divergence,
and complete a bounded live run with final summary and read-only confirmation that
its owned tuner was released. Keep authoritative-source retrieval/schema work as a
separate follow-on.
