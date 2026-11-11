"""One ingestion writer; WAL readers; immutable evidence per observation."""

import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from warnbridge.formats.xml import Parsed, utc_time
from warnbridge.transport.decoder import Event


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def known_header(header: bytes) -> bool:
    return (
        len(header) == 13
        and header[0] == 0x2F
        and header[1] in (0, 3)
        and header[2:4] == b"\x00\xff"
        and header[8] == 0
    )


class Store:
    def __init__(
        self, path: str | Path, *, max_rejected: int = 1000, readonly: bool = False
    ) -> None:
        if not readonly:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(
            Path(path).resolve().as_uri() + "?mode=ro" if readonly else path,
            uri=readonly,
            timeout=10,
            check_same_thread=not readonly,
        )
        self.db.row_factory = sqlite3.Row
        self.max_rejected = max_rejected
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            if readonly:
                if self.db.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise ValueError("unsupported database schema; run current writer migration")
                return
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("BEGIN IMMEDIATE")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError("database is newer than this application")
            if version == 0:
                migration = Path(__file__).with_name("001_initial.sql").read_text()
                # This bundled migration has simple statements, no embedded semicolons.
                # Check the version *after* taking the write lock for concurrent startup.
                for statement in migration.split(";"):
                    if statement.strip():
                        self.db.execute(statement)
            self.db.commit()
        except BaseException:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def start_session(self, source: str, identity: str) -> str:
        sid = str(uuid4())
        with self.db:
            self.db.execute(
                "INSERT INTO sessions(id,source,identity,started_at,state) VALUES(?,?,?,?,?)",
                (sid, source, identity, utc_now(), "running"),
            )
        return sid

    def finish_session(self, sid: str, summary: dict[str, int], state: str = "finished") -> None:
        with self.db:
            self.db.execute(
                "UPDATE sessions SET ended_at=?,state=?,summary=? WHERE id=?",
                (None if state == "running" else utc_now(), state, json.dumps(summary), sid),
            )

    def health_event(self, sid: str, kind: str, detail: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO health_events(session_id,at,kind,detail) VALUES(?,?,?,?)",
                (sid, utc_now(), kind, detail[:2000]),
            )
            self.db.execute(
                "DELETE FROM health_events WHERE id NOT IN "
                "(SELECT id FROM health_events ORDER BY id DESC LIMIT 1000)"
            )

    def record(self, sid: str, event: Event, parsed: Parsed | None, chunk_index: int) -> str | None:
        mid = None
        now = utc_now()
        with self.db:
            if event.kind == "message" and parsed is not None:
                content = parsed.xml if parsed.xml is not None else event.body
                mid = sha256(content).hexdigest()
                validation = {
                    "transport": "valid",
                    "xml": parsed.xml_state,
                    "schema": parsed.schema_state,
                    "signature": parsed.signature_state,
                    "geography": parsed.geography_state,
                    "parse_reason": parsed.reason,
                }
                identity = json.dumps(parsed.identity) if parsed.identity else None
                self.db.execute(
                    "INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        mid,
                        parsed.protocol,
                        parsed.classification,
                        parsed.xml,
                        json.dumps(parsed.fields),
                        json.dumps(validation),
                        identity,
                        int(parsed.actual_public),
                        now,
                    ),
                )
                for ref in parsed.references:
                    self.db.execute(
                        "INSERT OR IGNORE INTO relationships VALUES(?,?,?)",
                        (mid, json.dumps(ref), parsed.fields.get("msgType", "unknown")),
                    )
            # Empirical interpretation only, suppressed for heartbeat and implausible years.
            inferred = None
            if event.transport_id and event.transport_id != 0x411:
                stamp = datetime.fromtimestamp(event.transport_id, UTC)
                if 2000 <= stamp.year <= 2100:
                    inferred = stamp.isoformat()
            self.db.execute(
                "INSERT INTO observations(session_id,message_id,processed_at,received_at,"
                "monotonic_ns,chunk_index,transport_id,inferred_transport_at,header,body,assembled,"
                "raw_ts,offsets,stored_crc,calculated_crc,state,reason) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    mid,
                    now,
                    event.received_at,
                    event.monotonic_ns,
                    chunk_index,
                    event.transport_id,
                    inferred,
                    event.header,
                    event.body,
                    event.assembled,
                    event.raw_ts,
                    json.dumps(event.offsets),
                    event.stored_crc,
                    event.calculated_crc,
                    event.kind,
                    event.reason,
                ),
            )
            if event.kind == "rejected":
                self.db.execute(
                    "DELETE FROM observations WHERE state='rejected' AND id NOT IN "
                    "(SELECT id FROM observations WHERE state='rejected' "
                    "ORDER BY id DESC LIMIT ?)",
                    (self.max_rejected,),
                )
        return mid

    def messages(
        self,
        limit: int = 50,
        offset: int = 0,
        classification: str | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        where = (
            "WHERE (? IS NULL OR m.classification=?) AND (? IS NULL OR EXISTS "
            "(SELECT 1 FROM observations o JOIN sessions s ON o.session_id=s.id "
            "WHERE o.message_id=m.id AND s.source=?))"
        )
        params = (classification, classification, source, source)
        total = self.db.execute(f"SELECT count(*) FROM messages m {where}", params).fetchone()[0]
        rows = self.db.execute(
            f"SELECT m.id FROM messages m {where} ORDER BY m.created_at DESC, "
            "m.id LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.message(row["id"], detail=False) for row in rows],
        }

    def message(self, mid: str, *, detail: bool = True) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result.pop("xml")
        result["fields"] = json.loads(result["fields"])
        result["validation"] = json.loads(result["validation"])
        result["identity"] = json.loads(result["identity"]) if result["identity"] else None
        result["conflict"] = bool(
            row["identity"]
            and self.db.execute(
                "SELECT count(*) FROM messages WHERE identity=?", (row["identity"],)
            ).fetchone()[0]
            > 1
        )
        observations = self.db.execute(
            "SELECT o.id,o.session_id,s.source,s.identity AS source_identity,o.processed_at,"
            "o.received_at,o.monotonic_ns,o.chunk_index,o.transport_id,o.inferred_transport_at,"
            "o.header,o.offsets,o.stored_crc,o.calculated_crc FROM observations o "
            "JOIN sessions s ON o.session_id=s.id WHERE message_id=? ORDER BY o.id DESC LIMIT 100",
            (mid,),
        ).fetchall()
        result["delivery_count"] = self.db.execute(
            "SELECT count(*) FROM observations WHERE message_id=?", (mid,)
        ).fetchone()[0]
        result["sources"] = [
            r[0]
            for r in self.db.execute(
                "SELECT DISTINCT s.source FROM observations o JOIN sessions s ON s.id=o.session_id "
                "WHERE o.message_id=? ORDER BY s.source",
                (mid,),
            )
        ]
        result["lifecycle"] = "unresolved" if result["protocol"] == "CAP" else "not_applicable"
        expires = result["fields"].get("expires", [])
        times = [utc_time(t) for t in expires]
        if times and all(t is not None and t <= datetime.now(UTC) for t in times):
            result["lifecycle"] = "expired"
        result["operational_notifications"] = "disabled"
        if detail:
            result["observations"] = []
            for o in reversed(observations):
                item = dict(o)
                item["header_hex"] = item.pop("header").hex()
                item["observed_header_profile"] = known_header(o["header"])
                item["transport_id_hex"] = (
                    f"0x{o['transport_id']:08X}" if o["transport_id"] is not None else None
                )
                item["offsets"] = json.loads(item["offsets"])
                result["observations"].append(item)
            result["observations_truncated"] = result["delivery_count"] > 100
            result["relationships"] = [
                {
                    "kind": r["kind"],
                    "target_identity": json.loads(r["target_identity"]),
                    "resolved_message_ids": [
                        m[0]
                        for m in self.db.execute(
                            "SELECT id FROM messages WHERE identity=?", (r["target_identity"],)
                        )
                    ],
                }
                for r in self.db.execute("SELECT * FROM relationships WHERE message_id=?", (mid,))
            ]
        else:
            result.pop("fields")
        return result

    def raw(self, mid: str, part: str, observation: int | None = None) -> bytes | None:
        if part == "xml":
            row = self.db.execute("SELECT xml FROM messages WHERE id=?", (mid,)).fetchone()
        elif part in {"body", "header", "assembled", "raw_ts"}:
            row = self.db.execute(
                f"SELECT {part} FROM observations WHERE message_id=? "
                "AND (? IS NULL OR id=?) ORDER BY id LIMIT 1",
                (mid, observation, observation),
            ).fetchone()
        else:
            raise ValueError("unknown raw part")
        return bytes(row[0]) if row and row[0] is not None else None

    def receivers(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT 100")
        return [{**dict(r), "summary": json.loads(r["summary"])} for r in rows]

    def health(self) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for label, classification in (("heartbeat", "heartbeat"), ("link_test", "cmac_link_test")):
            row = self.db.execute(
                "SELECT o.received_at,o.processed_at,s.source FROM observations o "
                "JOIN messages m ON o.message_id=m.id JOIN sessions s ON s.id=o.session_id "
                "WHERE m.classification=? ORDER BY o.id DESC LIMIT 1",
                (classification,),
            ).fetchone()
            last[label] = dict(row) if row else None
        return {
            "application": "ok",
            "rf_tuner": "not_checked",
            "ts_reception": {
                "state": "not_continuously_monitored",
                "last_live_received_at": self.db.execute(
                    "SELECT max(o.received_at) FROM observations o JOIN sessions s "
                    "ON s.id=o.session_id WHERE s.source IN ('live_udp','live_hdhomerun')"
                ).fetchone()[0],
            },
            "last_observed": last,
            "new_content_at": self.db.execute("SELECT max(created_at) FROM messages").fetchone()[0],
            "web_comparison": "disabled",
            "public_warning_delivery": "not_established",
            "schema": "not_configured",
            "signature": "not_checked",
        }

    def metrics(self) -> dict[str, Any]:
        return {
            "messages": self.db.execute("SELECT count(*) FROM messages").fetchone()[0],
            "observations": self.db.execute("SELECT count(*) FROM observations").fetchone()[0],
            "retained_rejections": self.db.execute(
                "SELECT count(*) FROM observations WHERE state='rejected'"
            ).fetchone()[0],
            "sessions": self.receivers(),
        }
