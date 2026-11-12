# Alert inbox and receiver monitoring

## Alerts and the live heartbeat indicator

The default **Alerts** inbox shows live CAP and non-Link-Test CMAC content. It
excludes heartbeat/Link Test traffic without dropping evidence. Choose **replay**,
file/stdin or All sources explicitly to inspect imported examples. Each card shows
protocol, declared status, source, receipt/sent/expiry, delivery count and a readable
headline when available. Test/System/Exercise/Draft/unknown content remains clearly
labeled and accessible. Actual means a field value, not an authenticated warning.

The inspector shows CAP languages/information blocks, severity/urgency/certainty,
instructions, description, parameters (including wireless alert text), separate
areas/geocodes and original coordinates. An interactive Leaflet map displays
supplied polygons and approximate circle boundaries over a bundled offline
reference basemap. Pan/zoom, select boundaries, or use Fit alert areas; an optional
OpenStreetMap street layer loads only when selected. See [maps.md](maps.md) for
sources, offline detail and tile behavior. No geocode boundary is inferred. Invalid geometry stays in the field/raw
views and is reported as unplottable. Unknown extensions and original XML/bytes
remain under the evidence disclosure, along with all deliveries.

CAP Update/Cancel references and expiration are projected conservatively within
the selected source group, without changing evidence. Live imports cannot be
cancelled by replay. Conflicts/mixed sources/ambiguous latest references need review.
Missing targets and cancellation messages without info remain visible. See
protocol.md for exact rules. CMAC receives an experimental original-field review
view; no current CMAC schema, enum mapping, geography or lifecycle is assumed.

The connection indicator pulses once on each newly observed, fresh **live**
heartbeat delivery. It does not pulse on every UI refresh or on imported/replay
heartbeats, even when a replay retains arrival timestamps. It shows overdue after
`heartbeat_stale_after` (default 45 seconds), stopped for a stopped receiver, waiting
before a timed live observation, and unknown when API refresh fails. Age advances
locally between polls, so an old green state cannot persist through a hung request.
Reduced-motion preferences disable the animation. RF lock, heartbeat freshness,
Link Tests and authentication remain separate indicators.

The manufacturer's revision-11 D2WARN manual, printed page 104, describes PBS
heartbeats every 30 seconds and FEMA Link Tests usually 60 seconds, sometimes 120.
The 45-second UI threshold is a configurable application choice, not that manual's
40-second receiver alarm setting or a certification of warning delivery. The manual
does not establish why the user's fixed 2020 Link Test keeps recurring. All those
Link Tests share the broad connectivity-check purpose; distinct XML/repeat counts
alone do not identify different test functions. See sources.md for the citation.

Read-only API additions: `/api/v1/alerts` defaults to `source=live`; use `source=all`
or a specific source, optional `status`, `limit` and `offset`. It includes non-Link-Test
CMAC even when status is unknown. Message detail accepts a source filter, with an
`alert` projection derived from existing preserved trees. `/api/v1/health.connection`
is live-only heartbeat freshness. Existing general messages/deliveries APIs retain
their all-source default and add the `source=live` alias. No new migration is needed.

## RF / tuner card

The live listener reads `/tunerN/status` in a dedicated background worker while it
owns that tuner. Default interval: 5 seconds after the preceding check completes.
The bounded one-sample queue passes results to the ingestion thread for SQLite
writes; the polling thread never shares that SQLite connection. Slow control calls
therefore do not block UDP reception or native keepalives. Read calls retain the
existing 8-second subprocess timeout, and the worker is stopped/joined before the
owned tuner is released. No tuning/control action is added to the web server.

The UI refreshes every 5 seconds and shows the channel/tuner, RF lock, strength,
signal quality and symbol quality, plus sample age. These are receiver readings,
not public-warning delivery/authenticity indicators. A sample older than 20 seconds
is stale; failed/invalid polls are unavailable; a finished/failed/abandoned receiver
session is stopped. A process crash leaves its last sample stale instead of keeping
a permanent green lock indicator. No sample means not checked. Initial no-lock
samples can become locked after tuning settles and a subsequent poll completes.

Configure `rf_poll_interval` (minimum 1 second) and `rf_stale_after` (greater than the
poll interval) in TOML if needed; defaults are 5.0 and 20.0. API health reads stored
samples only and performs no device queries. Running only `serve` cannot poll RF;
run the updated `listen` process against the same database.

## Deliveries and unique content

Under **Diagnostics**, **Deliveries** shows one accepted reception per row, including each
heartbeat and each repeated Link Test. It shows reception time separately from XML
sent time. Untimed file/replay imports keep reception unknown and show processing
time instead; they never acquire a fabricated arrival timestamp.

**Unique content** groups exact XML-view bytes (or non-XML body bytes) by SHA-256,
independently of transport IDs. Its delivery count is the number of observations of
that content. All sampled heartbeat bodies are the same `Heartbeat Message`, so a
single heartbeat content record is expected. CMAC transmissions can repeat identical
XML many times, while others contain different message numbers, timestamps, XML
formatting or other fields and form distinct content records. Different repeat
counts alone do not establish loss or an error. Old System/Link Test XML sent times
remain visible; receiving an old test again does not create a new public warning.

Diagnostics defaults to Link Tests and supports heartbeat history through the type
filter. Both diagnostic views support type and source filtering. Content counts, source labels and
first/last known receipt times respect the selected source, so a live-only count no
longer includes replay imports. The repeated-content marker reflects whether the
archive had that content before the delivery, even if the earlier observation was
from another source. All-source grouping is retained deliberately; data/identities
are not rewritten or duplicated by this UI change. Unique content sorts by most
recent delivery rather than only its first insertion.

Selecting a message opens a readable alert (when applicable), original bytes/fields
and a paginated delivery-history
table, including source, timestamps, transport ID and CRC. Each history row can be
selected to inspect/download that observation's body. The legacy message-detail
response still caps its embedded observation list at 100; the new paginated
`GET /api/v1/deliveries` endpoint accesses the entire accepted history with stable
observation IDs, source/type/message filters, limit (1–100) and offset. Existing raw
routes restrict an observation to its requested content ID and expose no file paths.

## Upgrading an existing installation

For the ThinkCentre Docker deployment, use the existing downloaded Compose directory:

```sh
cd /opt/warnbridge
sudo docker compose pull
sudo docker compose up -d
```

The config and named archive volume remain in place. Do not run Git/source setup
or regenerate local config for a normal image update. For a first install, use
[docker-live.md](docker-live.md), which starts from an empty directory. The native
commands below apply only to an intentional source/native installation.

### Native/source upgrade alternative

Stop **both** the listener and web server before updating. The alert inbox retains
schema 2. For installations still on schema 1, database migration 002
adds a per-session latest RF snapshot table and an observation index, taking schema
version 1 to 2. Existing messages, delivery counts, raw bytes and relationships are
preserved; no reimport or database deletion is needed. Old binaries must be stopped
because they do not understand schema 2.

```sh
git pull --ff-only https://github.com/bho18/atsc_warn.git codex/warnbridge-initial
./scripts/setup.sh
```

Restart the listener, then the web server in another terminal, with the same config
and database as before. For the historical station/device example:

```sh
.venv/bin/warnbridge listen --host 192.168.4.159 --channel 7
# Separate terminal:
.venv/bin/warnbridge serve
```

Refresh the browser. RF status should update within the polling/UI cycle after a
successful device query. The alert inbox reads existing preserved trees immediately;
no reimport/deletion is needed. Diagnostics retains individual and grouped check
traffic. Live heartbeat animation needs timed reception, not imported data.
