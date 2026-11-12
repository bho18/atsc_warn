from collections.abc import Iterator
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from warnbridge.config import Config
from warnbridge.formats.xml import readable_text
from warnbridge.storage.store import Store


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    # Schema setup only. Serving never starts a receiver, including reload/workers.
    Store(config.database).close()
    app = FastAPI(title="WarnBridge", version="0.1.0", docs_url=None, redoc_url=None)
    allowed = (
        [ip_network(network) for network in config.web_allowed_networks]
        if config.web_allowed_networks is not None
        else None
    )

    def database() -> Iterator[Store]:
        store = Store(config.database, readonly=True)
        try:
            yield store
        finally:
            store.close()

    DB = Annotated[Store, Depends(database)]

    @app.middleware("http")
    async def headers(request: Any, call_next: Any) -> Any:
        permitted = allowed is None
        if allowed is not None and request.client:
            try:
                address = ip_address(request.client.host)
                address = getattr(address, "ipv4_mapped", None) or address
                permitted = any(address in network for network in allowed)
            except ValueError:
                permitted = False
        response = (
            await call_next(request)
            if permitted
            else JSONResponse({"detail": "Access restricted to configured internal networks"}, 403)
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health")
    def health(db: DB) -> dict[str, Any]:
        archive_bytes = sum(
            path.stat().st_size
            for path in (Path(config.database), Path(config.database + "-wal"))
            if path.exists()
        )
        return {
            **db.health(
                rf_stale_after=config.rf_stale_after,
                heartbeat_stale_after=config.heartbeat_stale_after,
            ),
            "display_timezone": config.timezone,
            "storage": {
                "bytes": archive_bytes,
                "limit_bytes": config.max_database_bytes,
                "state": "full"
                if archive_bytes >= config.max_database_bytes
                else "near_limit"
                if archive_bytes >= config.max_database_bytes * 0.8
                else "ok",
            },
        }

    @app.get("/api/v1/receivers")
    def receivers(db: DB) -> list[dict[str, Any]]:
        return db.receivers()

    @app.get("/api/v1/metrics")
    def metrics(db: DB) -> dict[str, Any]:
        return db.metrics()

    @app.get("/api/v1/messages")
    def messages(
        db: DB,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        classification: str | None = None,
        source: Literal["live", "file", "stdin", "replay", "live_udp", "live_hdhomerun"]
        | None = None,
    ) -> dict[str, Any]:
        return db.messages(limit, offset, classification, source)

    @app.get("/api/v1/deliveries")
    def deliveries(
        db: DB,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        message_id: str | None = None,
        source: Literal["live", "file", "stdin", "replay", "live_udp", "live_hdhomerun"]
        | None = None,
        classification: str | None = None,
    ) -> dict[str, Any]:
        return db.deliveries(
            limit, offset, message_id=message_id, source=source, classification=classification
        )

    @app.get("/api/v1/messages/{mid}")
    def message(
        mid: str,
        db: DB,
        source: Literal["live", "file", "stdin", "replay", "live_udp", "live_hdhomerun"]
        | None = None,
    ) -> dict[str, Any]:
        result = db.message(mid, source=source)
        if result is None:
            raise HTTPException(404, "message not found")
        return result

    @app.get("/api/v1/messages/{mid}/raw")
    def raw(
        mid: str,
        db: DB,
        part: Literal["xml", "body", "header", "assembled", "raw_ts"] = "xml",
        observation: int | None = None,
    ) -> Response:
        data = db.raw(mid, part, observation)
        if data is None:
            raise HTTPException(404, "raw part not found")
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{part}.bin"'},
        )

    @app.get("/api/v1/messages/{mid}/text")
    def text_view(
        mid: str,
        db: DB,
        part: Literal["xml", "body"] = "xml",
        observation: int | None = None,
    ) -> Response:
        data = db.raw(mid, part, observation)
        if data is None:
            raise HTTPException(404, "message text not found")
        return Response(readable_text(data), media_type="text/plain")

    @app.get("/api/v1/alerts")
    def alerts(
        db: DB,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        source: Literal[
            "live", "all", "file", "stdin", "replay", "live_udp", "live_hdhomerun"
        ] = "live",
        status: str | None = None,
        cancellations: bool = False,
    ) -> dict[str, Any]:
        return db.alerts(
            limit,
            offset,
            source=None if source == "all" else source,
            status=status,
            cancellations=cancellations,
        )

    @app.get("/api/v1/diagnostics")
    def diagnostics(
        db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ) -> dict[str, Any]:
        rows = db.db.execute(
            "SELECT id,session_id,received_at,processed_at,reason,length(raw_ts) AS bytes "
            "FROM observations WHERE state='rejected' ORDER BY id DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        )
        total = db.db.execute(
            "SELECT count(*) FROM observations WHERE state='rejected'"
        ).fetchone()[0]
        return {"items": [dict(r) for r in rows], "limit": limit, "offset": offset, "total": total}

    @app.get("/api/v1/diagnostics/{oid}/raw")
    def diagnostic_raw(
        oid: int,
        db: DB,
        part: Literal["header", "body", "assembled", "raw_ts"] = "raw_ts",
    ) -> Response:
        row = db.db.execute(
            f"SELECT {part} FROM observations WHERE id=? AND state='rejected'",
            (oid,),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "retained failure not found")
        return Response(
            bytes(row[0]),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="failure-{oid}-{part}.bin"',
            },
        )

    web = Path(__file__).resolve().parent.parent / "web"
    app.mount("/assets", StaticFiles(directory=web), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    return app
