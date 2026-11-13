"""Age-based diagnostic cleanup. Alert content and its deliveries are never selected."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from warnbridge.config import Config


def record_maintenance(db: sqlite3.Connection, kind: str, details: dict[str, Any]) -> None:
    db.execute(
        "INSERT INTO maintenance_status VALUES(?,?,?) ON CONFLICT(kind) "
        "DO UPDATE SET at=excluded.at,details=excluded.details",
        (kind, datetime.now(UTC).isoformat(), json.dumps(details)),
    )


def delete_observations(db: sqlite3.Connection, predicate: str, params: tuple[Any, ...]) -> int:
    # Recovery audits reference the observations being intentionally expired.
    db.execute(
        f"DELETE FROM observation_recoveries WHERE observation_id IN "
        f"(SELECT id FROM observations WHERE {predicate})",
        params,
    )
    return db.execute(f"DELETE FROM observations WHERE {predicate}", params).rowcount


def retain(
    db: sqlite3.Connection, config: Config, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    diagnostics_before = (now - timedelta(days=config.diagnostic_retention_days)).isoformat()
    failures_before = (now - timedelta(days=config.failure_retention_days)).isoformat()
    removed = {}
    # Serialize with ingestion and manual purges. Never VACUUM the live receiver DB.
    with db:
        db.execute("BEGIN IMMEDIATE")
        removed["diagnostic_deliveries"] = delete_observations(
            db,
            "state='message' AND processed_at<? AND message_id IN "
            "(SELECT id FROM messages WHERE classification IN ('heartbeat','cmac_link_test'))",
            (diagnostics_before,),
        )
        removed["failures"] = delete_observations(
            db, "state='rejected' AND processed_at<?", (failures_before,)
        )
        # Content stays while ANY source still has a retained delivery. Unknown,
        # invalid, CAP Test/System and other alert content are intentionally excluded.
        unused = (
            "SELECT m.id FROM messages m WHERE classification IN ('heartbeat','cmac_link_test') "
            "AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.message_id=m.id)"
        )
        db.execute(f"DELETE FROM relationships WHERE message_id IN ({unused})")
        removed["diagnostic_contents"] = db.execute(
            f"DELETE FROM messages WHERE id IN ({unused})"
        ).rowcount
        removed["health_events"] = db.execute(
            "DELETE FROM health_events WHERE at<?", (diagnostics_before,)
        ).rowcount
        removed["web_observations"] = db.execute(
            "DELETE FROM web_observations WHERE imported_at<?", (diagnostics_before,)
        ).rowcount
        db.execute(
            "DELETE FROM receiver_status WHERE checked_at<? AND session_id IN "
            "(SELECT id FROM sessions WHERE state!='running')",
            (diagnostics_before,),
        )
        removed["sessions"] = db.execute(
            "DELETE FROM sessions WHERE state!='running' AND coalesce(ended_at,started_at)<? "
            "AND NOT EXISTS (SELECT 1 FROM observations o WHERE o.session_id=sessions.id) "
            "AND NOT EXISTS (SELECT 1 FROM health_events h WHERE h.session_id=sessions.id) "
            "AND NOT EXISTS (SELECT 1 FROM receiver_status r WHERE r.session_id=sessions.id)",
            (diagnostics_before,),
        ).rowcount
        record_maintenance(db, "automatic", removed)
    return removed


def failure_preview(db: sqlite3.Connection, older_than_days: int) -> dict[str, Any]:
    before = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
    # IDs never get reused after retention, including when the entire DB is empty.
    through_id = db.execute(
        "SELECT last_id FROM observation_sequence WHERE singleton=1"
    ).fetchone()[0]
    reasons = [
        dict(row)
        for row in db.execute(
            "SELECT reason,count(*) AS count FROM observations WHERE state='rejected' "
            "AND processed_at<? AND id<=? GROUP BY reason ORDER BY count(*) DESC,reason",
            (before, through_id),
        )
    ]
    return {
        "before": before,
        "through_id": through_id,
        "count": sum(row["count"] for row in reasons),
        "reasons": reasons,
        "scope": "Retained failures from all sources; accepted messages are kept",
    }


def purge_failures(db: sqlite3.Connection, before: str, through_id: int) -> int:
    with db:
        db.execute("BEGIN IMMEDIATE")
        removed = delete_observations(
            db, "state='rejected' AND processed_at<? AND id<=?", (before, through_id)
        )
        record_maintenance(
            db, "purge_failures", {"removed": removed, "before": before, "through_id": through_id}
        )
    return removed


def storage_usage(path: str, db: sqlite3.Connection) -> dict[str, int]:
    from pathlib import Path

    size = sum(p.stat().st_size for p in (Path(path), Path(path + "-wal")) if p.exists())
    page_size = db.execute("PRAGMA page_size").fetchone()[0]
    pages = db.execute("PRAGMA page_count").fetchone()[0]
    free = db.execute("PRAGMA freelist_count").fetchone()[0]
    # Logical occupied pages include uncheckpointed changes. Freelist pages are
    # reusable; counting the file high-water mark would keep a purged archive full.
    return {
        "bytes": size,
        "used_bytes": (pages - free) * page_size,
        "reusable_bytes": free * page_size,
    }
