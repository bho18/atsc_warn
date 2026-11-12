"""One ingestion writer; WAL readers; immutable evidence per observation."""

import json
import sqlite3
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from warnbridge.domain.alerts import project_alert
from warnbridge.formats.xml import Parsed, utc_time
from warnbridge.inputs.hdhomerun import Tuner
from warnbridge.transport.decoder import Event


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def known_header(header: bytes) -> bool:
    return (
        len(header) >= 13
        and len(header) == 13 + 3 * header[9]
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
                if self.db.execute("PRAGMA user_version").fetchone()[0] != 3:
                    raise ValueError("unsupported database schema; run current writer migration")
                return
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("BEGIN IMMEDIATE")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise ValueError("database is newer than this application")
            for target, filename in (
                (1, "001_initial.sql"),
                (2, "002_receiver_status.sql"),
                (3, "003_recoveries.sql"),
            ):
                if version >= target:
                    continue
                migration = Path(__file__).with_name(filename).read_text()
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

    def _record_content(self, event: Event, parsed: Parsed, now: str) -> str:
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
        return mid

    def record(self, sid: str, event: Event, parsed: Parsed | None, chunk_index: int) -> str | None:
        mid = None
        now = utc_now()
        with self.db:
            if event.kind == "message" and parsed is not None:
                mid = self._record_content(event, parsed, now)
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
        source_sql, source_params = self.source_filter(source)
        where = (
            "WHERE (? IS NULL OR m.classification=?) AND EXISTS "
            "(SELECT 1 FROM observations o JOIN sessions s ON o.session_id=s.id "
            f"WHERE o.message_id=m.id AND {source_sql})"
        )
        params = (classification, classification, *source_params)
        total = self.db.execute(f"SELECT count(*) FROM messages m {where}", params).fetchone()[0]
        rows = self.db.execute(
            f"SELECT m.id FROM messages m {where} ORDER BY "
            "(SELECT max(o.id) FROM observations o JOIN sessions s ON s.id=o.session_id "
            f"WHERE o.message_id=m.id AND {source_sql}) DESC,m.id LIMIT ? OFFSET ?",
            (*params, *source_params, limit, offset),
        ).fetchall()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [self.message(row["id"], detail=False, source=source) for row in rows],
        }

    @staticmethod
    def source_filter(source: str | None) -> tuple[str, tuple[str, ...]]:
        if source == "live":
            return "s.source IN (?,?)", ("live_hdhomerun", "live_udp")
        return ("s.source=?", (source,)) if source else ("1=1", ())

    def message(
        self, mid: str, *, detail: bool = True, source: str | None = None
    ) -> dict[str, Any] | None:
        source_sql, source_params = self.source_filter(source)
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
                "SELECT count(*) FROM messages m WHERE identity=? AND EXISTS "
                "(SELECT 1 FROM observations o JOIN sessions s ON s.id=o.session_id "
                f"WHERE o.message_id=m.id AND {source_sql})",
                (row["identity"], *source_params),
            ).fetchone()[0]
            > 1
        )
        observations = self.db.execute(
            "SELECT o.id,o.session_id,s.source,s.identity AS source_identity,o.processed_at,"
            "o.received_at,o.monotonic_ns,o.chunk_index,o.transport_id,o.inferred_transport_at,"
            "o.header,o.offsets,o.stored_crc,o.calculated_crc FROM observations o "
            "JOIN sessions s ON o.session_id=s.id WHERE message_id=? "
            f"AND {source_sql} ORDER BY o.id DESC LIMIT 100",
            (mid, *source_params),
        ).fetchall()
        result["delivery_count"] = self.db.execute(
            "SELECT count(*) FROM observations o JOIN sessions s ON s.id=o.session_id "
            f"WHERE message_id=? AND {source_sql}",
            (mid, *source_params),
        ).fetchone()[0]
        if source is not None and result["delivery_count"] == 0:
            return None
        result["sources"] = [
            r[0]
            for r in self.db.execute(
                "SELECT DISTINCT s.source FROM observations o JOIN sessions s ON s.id=o.session_id "
                f"WHERE o.message_id=? AND {source_sql} ORDER BY s.source",
                (mid, *source_params),
            )
        ]
        times_row = self.db.execute(
            "SELECT min(received_at),max(received_at),min(processed_at),max(processed_at) "
            "FROM observations o JOIN sessions s ON s.id=o.session_id "
            f"WHERE message_id=? AND {source_sql}",
            (mid, *source_params),
        ).fetchone()
        result.update(
            zip(
                (
                    "first_received_at",
                    "last_received_at",
                    "first_processed_at",
                    "last_processed_at",
                ),
                times_row,
                strict=True,
            )
        )
        result["declared_sent"] = result["fields"].get("sent") or None
        number = result["fields"].get("CMAC_message_number", [])
        result["protocol_identifier"] = (
            (number[0] if len(number) == 1 else None)
            if result["protocol"] == "CMAC"
            else result["fields"].get("identifier")
        )
        result["lifecycle"] = "unresolved" if result["protocol"] == "CAP" else "not_applicable"
        expires = result["fields"].get("expires", [])
        times = [utc_time(t) for t in expires]
        if times and all(t is not None and t <= datetime.now(UTC) for t in times):
            result["lifecycle"] = "expired"
        result["operational_notifications"] = "disabled"
        if result["classification"] not in ("heartbeat", "cmac_link_test"):
            result["alert"] = project_alert(result["protocol"], result["fields"])
            if result["validation"]["parse_reason"]:
                result["alert"]["issues"].append(result["validation"]["parse_reason"])
            self.cap_lifecycle(result, source)
            self.cmac_lifecycle(result, source)
        else:
            result["alert"] = None
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
                recovered = self.db.execute(
                    "SELECT recovered_at,original_reason FROM observation_recoveries "
                    "WHERE observation_id=?",
                    (o["id"],),
                ).fetchone()
                item["recovery"] = dict(recovered) if recovered else None
                result["observations"].append(item)
            result["observations_truncated"] = result["delivery_count"] > 100
            result["relationships"] = [
                {
                    "kind": r["kind"],
                    "target_identity": json.loads(r["target_identity"]),
                    "resolved_message_ids": [
                        m[0]
                        for m in self.db.execute(
                            "SELECT m.id FROM messages m WHERE identity=? AND EXISTS "
                            "(SELECT 1 FROM observations o JOIN sessions s ON s.id=o.session_id "
                            f"WHERE o.message_id=m.id AND {source_sql})",
                            (r["target_identity"], *source_params),
                        )
                    ],
                }
                for r in self.db.execute("SELECT * FROM relationships WHERE message_id=?", (mid,))
            ]
        else:
            result.pop("fields")
        return result

    def deliveries(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        message_id: str | None = None,
        source: str | None = None,
        classification: str | None = None,
    ) -> dict[str, Any]:
        source_sql, source_params = self.source_filter(source)
        where = (
            "WHERE o.state='message' AND (? IS NULL OR o.message_id=?) "
            f"AND {source_sql} AND (? IS NULL OR m.classification=?)"
        )
        params = (message_id, message_id, *source_params, classification, classification)
        joins = (
            "FROM observations o JOIN messages m ON m.id=o.message_id "
            "JOIN sessions s ON s.id=o.session_id "
        )
        total = self.db.execute("SELECT count(*) " + joins + where, params).fetchone()[0]
        rows = self.db.execute(
            "SELECT o.id,o.message_id,o.session_id,s.source,s.identity AS source_identity,"
            "o.received_at,o.processed_at,o.transport_id,o.stored_crc,o.calculated_crc,"
            "m.classification,m.fields,m.validation,EXISTS(SELECT 1 FROM observations prior "
            "WHERE prior.message_id=o.message_id AND prior.id<o.id) AS repeated_content "
            + joins
            + where
            + " ORDER BY o.id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            fields = json.loads(item.pop("fields"))
            item["declared_sent"] = fields.get("sent") or None
            number = fields.get("CMAC_message_number", [])
            item["protocol_identifier"] = (
                number[0] if len(number) == 1 else fields.get("identifier")
            )
            item["validation"] = json.loads(item["validation"])
            item["repeated_content"] = bool(item["repeated_content"])
            item["transport_id_hex"] = (
                f"0x{item['transport_id']:08X}" if item["transport_id"] is not None else None
            )
            items.append(item)
        return {"total": total, "limit": limit, "offset": offset, "items": items}

    def cap_lifecycle(self, message: dict[str, Any], source: str | None) -> None:
        alert = message["alert"]
        if message["protocol"] != "CAP":
            return
        if message["conflict"]:
            alert["lifecycle"] = "identity_conflict"
            return
        if alert["message_type"] not in ("Alert", "Update"):
            return
        if not message["identity"] or not utc_time(alert["sent"] or ""):
            alert["lifecycle"] = "unknown"
            return
        # Never let a replay/import cancel a live observation of the same content.
        scope = source
        if scope is None:
            sources = set(message["sources"])
            if sources and sources <= {"live_hdhomerun", "live_udp"}:
                scope = "live"
            elif len(sources) == 1:
                scope = next(iter(sources))
            else:
                alert["lifecycle"] = "provenance_review"
                alert["issues"].append("Choose a source group to project reference relationships")
                return
        source_sql, source_params = self.source_filter(scope)
        rows = self.db.execute(
            "SELECT m.id,m.fields,m.identity,r.kind FROM relationships r "
            "JOIN messages m ON m.id=r.message_id WHERE r.target_identity=? "
            "AND m.protocol='CAP' AND r.kind IN ('Update','Cancel') AND EXISTS "
            "(SELECT 1 FROM observations o JOIN sessions s ON s.id=o.session_id "
            f"WHERE o.message_id=m.id AND {source_sql}) LIMIT 1001",
            (json.dumps(message["identity"]), *source_params),
        ).fetchall()
        if len(rows) > 1000:
            alert["lifecycle"] = "reference_review"
            alert["issues"].append("Reference relationship projection limit reached")
            return
        related = []
        for row in rows:
            fields = json.loads(row["fields"])
            sent = utc_time(fields.get("sent", ""))
            original_sent = utc_time(alert["sent"])
            if (
                not alert["status"]
                or fields.get("status") != alert["status"]
                or not alert["scope"]
                or fields.get("scope") != alert["scope"]
                or sent is None
                or original_sent is None
            ):
                continue
            if sent < original_sent:
                alert["lifecycle"] = "reference_review"
                alert["issues"].append(
                    "Referencing message has an earlier sent time than its target"
                )
                continue
            conflict = (
                self.db.execute(
                    "SELECT count(*) FROM messages m WHERE identity=? AND EXISTS "
                    "(SELECT 1 FROM observations o JOIN sessions s ON s.id=o.session_id "
                    f"WHERE o.message_id=m.id AND {source_sql})",
                    (row["identity"], *source_params),
                ).fetchone()[0]
                > 1
            )
            if conflict:
                alert["issues"].append("Conflicting content in a referencing message")
                alert["lifecycle"] = "reference_review"
                continue
            related.append((sent, row["id"], row["kind"], fields["sent"]))
            if row["kind"] == "Cancel":
                cancellation = project_alert("CAP", fields)
                alert["cancellations"].append(
                    {
                        "message_id": row["id"],
                        "sent": fields["sent"],
                        "headline": cancellation["headline"],
                        "note": cancellation["note"],
                        "infos": cancellation["infos"],
                    }
                )
        alert["relationships"] = [
            {"message_id": mid, "type": kind, "sent": stamp}
            for _, mid, kind, stamp in sorted(related)
        ]
        if related and alert["lifecycle"] != "reference_review":
            latest = max(related)
            if len({kind for sent, _, kind, _ in related if sent == latest[0]}) > 1:
                alert["lifecycle"] = "reference_review"
                alert["issues"].append("Update and Cancel share the latest declared sent time")
            else:
                alert["lifecycle"] = "cancelled" if latest[2] == "Cancel" else "superseded"
        alert["lifecycle_interpretation"] = "Declared CAP relationships; authentication not checked"

    def cmac_lifecycle(self, message: dict[str, Any], source: str | None) -> None:
        """Link only an explicitly named CAP counterpart, never all-clear text."""
        if message["protocol"] != "CMAC":
            return
        from warnbridge.domain.alerts import value
        from warnbridge.formats.xml import CMAC

        root = message["fields"].get("tree", {})
        identifier = value(root, CMAC, "CMAC_cap_identifier")
        sender = value(root, CMAC, "CMAC_sender")
        sent = utc_time(value(root, CMAC, "CMAC_cap_sent_date_time") or "")
        if not identifier or not sender or sent is None:
            return
        scope = source
        if scope is None:
            sources = set(message["sources"])
            if sources and sources <= {"live_udp", "live_hdhomerun"}:
                scope = "live"
            elif len(sources) == 1:
                scope = next(iter(sources))
            else:
                return
        source_sql, params = self.source_filter(scope)
        matches = []
        for row in self.db.execute(
            "SELECT m.id,m.fields FROM messages m WHERE m.protocol='CAP' "
            "AND json_extract(m.fields,'$.identifier')=? "
            "AND json_extract(m.fields,'$.sender')=? AND EXISTS "
            "(SELECT 1 FROM observations o JOIN sessions s ON s.id=o.session_id "
            f"WHERE o.message_id=m.id AND {source_sql})",
            (identifier, sender, *params),
        ):
            if utc_time(json.loads(row["fields"]).get("sent", "")) == sent:
                matches.append(row["id"])
        if len(matches) != 1:
            if matches:
                message["alert"]["issues"].append("Ambiguous referenced CAP counterpart")
            return
        counterpart = self.message(matches[0], detail=False, source=scope)
        if counterpart is None:
            return
        message["alert"]["cap_message_id"] = matches[0]
        cap = counterpart["alert"]
        if cap["status"] == message["alert"]["status"] and cap["lifecycle"] in (
            "cancelled",
            "superseded",
            "reference_review",
            "identity_conflict",
        ):
            for key in ("lifecycle", "relationships", "cancellations"):
                message["alert"][key] = cap[key]

    def alerts(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        source: str | None = "live",
        status: str | None = None,
        cancellations: bool = False,
    ) -> dict[str, Any]:
        source_sql, source_params = self.source_filter(source)
        where = (
            "WHERE m.classification NOT IN ('heartbeat','cmac_link_test') "
            "AND (CASE WHEN m.protocol='CAP' AND json_extract(m.fields,'$.msgType')='Cancel' "
            "THEN 1 ELSE 0 END)=? "
            "AND EXISTS (SELECT 1 FROM observations o JOIN sessions s ON s.id=o.session_id "
            f"WHERE o.message_id=m.id AND {source_sql}) "
            "AND (? IS NULL OR COALESCE(NULLIF(json_extract(m.fields,'$.status'),''),"
            "CASE WHEN json_array_length(m.fields,'$.CMAC_status')=1 THEN "
            "NULLIF(json_extract(m.fields,'$.CMAC_status[0]'),'') END,'Unknown')=?)"
        )
        params = (int(cancellations), *source_params, status, status)
        total = self.db.execute(f"SELECT count(*) FROM messages m {where}", params).fetchone()[0]
        rows = self.db.execute(
            f"SELECT m.id FROM messages m {where} ORDER BY "
            "(SELECT max(o.id) FROM observations o JOIN sessions s ON s.id=o.session_id "
            f"WHERE o.message_id=m.id AND {source_sql}) DESC LIMIT ? OFFSET ?",
            (*params, *source_params, limit, offset),
        ).fetchall()
        items = [self.message(row["id"], detail=False, source=source) for row in rows]
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "label": "CAP and non-Link-Test CMAC; declared status, unauthenticated",
            "lifecycle_policy": "Declared CAP timing and same-source references; unauthenticated",
        }

    def record_receiver_status(
        self,
        sid: str,
        host: str,
        tuner: int,
        checked_at: str,
        raw_status: str | None,
        error: str | None = None,
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO receiver_status VALUES(?,?,?,?,?,?) ON CONFLICT(session_id) "
                "DO UPDATE SET checked_at=excluded.checked_at,raw_status=excluded.raw_status,"
                "error=excluded.error",
                (sid, checked_at, host, tuner, raw_status, error),
            )

    def receiver_health(self, stale_after: float = 20.0) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT r.*,s.state AS session_state,s.identity FROM receiver_status r "
            "JOIN sessions s ON s.id=r.session_id ORDER BY s.started_at DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        fields = Tuner.status_fields(row["raw_status"] or "")
        checked = utc_time(row["checked_at"])
        age = max(0.0, (datetime.now(UTC) - checked).total_seconds()) if checked else None
        state = (
            "stopped"
            if row["session_state"] != "running"
            else "stale"
            if age is None or age > stale_after
            else "unavailable"
            if row["error"] or not fields
            else "locked"
            if fields.get("lock") not in (None, "none")
            else "no_lock"
        )
        result.update(state=state, age_seconds=age, stale_after_seconds=stale_after, fields=fields)
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

    def health(
        self, *, rf_stale_after: float = 20.0, heartbeat_stale_after: float = 45.0
    ) -> dict[str, Any]:
        receiver = self.receiver_health(rf_stale_after)
        last: dict[str, Any] = {}
        for label, classification in (("heartbeat", "heartbeat"), ("link_test", "cmac_link_test")):
            row = self.db.execute(
                "SELECT o.received_at,o.processed_at,s.source FROM observations o "
                "JOIN messages m ON o.message_id=m.id JOIN sessions s ON s.id=o.session_id "
                "WHERE m.classification=? ORDER BY o.id DESC LIMIT 1",
                (classification,),
            ).fetchone()
            last[label] = dict(row) if row else None
        live = self.db.execute(
            "SELECT o.id,o.received_at,o.session_id,s.source,s.state AS session_state "
            "FROM observations o JOIN sessions s ON s.id=o.session_id "
            "JOIN messages m ON m.id=o.message_id WHERE m.classification='heartbeat' "
            "AND s.source IN ('live_hdhomerun','live_udp') AND o.received_at IS NOT NULL "
            "ORDER BY o.id DESC LIMIT 1"
        ).fetchone()
        stamp = utc_time(live["received_at"]) if live else None
        age = max(0.0, (datetime.now(UTC) - stamp).total_seconds()) if stamp else None
        latest_session = self.db.execute(
            "SELECT id,state FROM sessions WHERE source IN ('live_hdhomerun','live_udp') "
            "ORDER BY started_at DESC,rowid DESC LIMIT 1"
        ).fetchone()
        state = "waiting"
        if latest_session and latest_session["state"] != "running":
            state = "stopped"
        elif live and latest_session and live["session_id"] == latest_session["id"]:
            state = "stale" if age is None or age > heartbeat_stale_after else "recent"
        connection = {
            "state": state,
            "last_heartbeat": dict(live) if live else None,
            "age_seconds": age,
            "stale_after_seconds": heartbeat_stale_after,
            "scope": "live_only",
        }
        return {
            "connection": connection,
            "application": "ok",
            "rf_tuner": receiver["state"] if receiver else "not_checked",
            "receiver": receiver,
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
            "deliveries": self.db.execute(
                "SELECT count(*) FROM observations WHERE state='message'"
            ).fetchone()[0],
            "observations": self.db.execute("SELECT count(*) FROM observations").fetchone()[0],
            "retained_rejections": self.db.execute(
                "SELECT count(*) FROM observations WHERE state='rejected'"
            ).fetchone()[0],
            "recovered_observations": self.db.execute(
                "SELECT count(*) FROM observation_recoveries"
            ).fetchone()[0],
            "sessions": self.receivers(),
        }
