# RF monitoring and message views

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

The default **Deliveries** view shows one accepted reception per row, including each
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

Both views support type and source filtering. Content counts, source labels and
first/last known receipt times respect the selected source, so a live-only count no
longer includes replay imports. The repeated-content marker reflects whether the
archive had that content before the delivery, even if the earlier observation was
from another source. All-source grouping is retained deliberately; data/identities
are not rewritten or duplicated by this UI change. Unique content sorts by most
recent delivery rather than only its first insertion.

Selecting a message opens its original bytes/fields and a paginated delivery-history
table, including source, timestamps, transport ID and CRC. Each history row can be
selected to inspect/download that observation's body. The legacy message-detail
response still caps its embedded observation list at 100; the new paginated
`GET /api/v1/deliveries` endpoint accesses the entire accepted history with stable
observation IDs, source/type/message filters, limit (1–100) and offset. Existing raw
routes restrict an observation to its requested content ID and expose no file paths.

## Upgrading an existing installation

Stop **both** the listener and web server before updating. Database migration 002
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
successful device query. The new Deliveries view presents existing observations
individually immediately; starting the new listener enables RF sampling going forward.
