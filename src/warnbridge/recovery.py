"""Reinterpret retained failures under the exclusive ingestion lock.

Keep observation IDs, source sessions, original clocks, TS and assembled bytes.
Record the previous interpretation before promoting a validated observation.
"""

from warnbridge.config import Config
from warnbridge.formats.xml import parse_body
from warnbridge.storage.store import Store, utc_now
from warnbridge.transport.decoder import Decoder


def recover_rejections(store: Store, config: Config) -> int:
    recovered = 0
    # Packet-loss/timeout rejections are never stitched together. Only complete
    # assemblies rejected by the old message-header interpretation are eligible.
    last_id = 0
    while True:
        row = store.db.execute(
            "SELECT * FROM observations WHERE id>? AND state='rejected' AND reason IN "
            "('body_size_limit','body_length_exceeds_assembly','crc_mismatch',"
            "'non_ff_stuffing','inner_outer_id_mismatch') ORDER BY id LIMIT 1",
            (last_id,),
        ).fetchone()
        if row is None:
            break
        last_id = row["id"]
        decoder = Decoder(config.pid, config.limits)
        events = list(decoder.feed(row["raw_ts"])) + list(decoder.finish())
        if len(events) != 1 or events[0].kind != "message":
            continue
        event = events[0]
        if event.assembled != row["assembled"] or event.transport_id != row["transport_id"]:
            continue
        parsed = parse_body(event.body, max_bytes=config.limits.max_body)
        with store.db:
            mid = store._record_content(event, parsed, row["processed_at"])
            store.db.execute(
                "INSERT INTO observation_recoveries VALUES(?,?,?,?,?,?,?)",
                (
                    row["id"],
                    utc_now(),
                    row["reason"],
                    row["header"],
                    row["body"],
                    row["stored_crc"],
                    row["calculated_crc"],
                ),
            )
            store.db.execute(
                "UPDATE observations SET message_id=?,header=?,body=?,stored_crc=?,"
                "calculated_crc=?,state='message',reason=NULL WHERE id=?",
                (mid, event.header, event.body, event.stored_crc, event.calculated_crc, row["id"]),
            )
        recovered += 1
    return recovered
