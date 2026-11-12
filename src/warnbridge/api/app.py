from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from warnbridge.config import Config
from warnbridge.storage.store import Store


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config()
    # Schema setup only. Serving never starts a receiver, including reload/workers.
    Store(config.database).close()
    app = FastAPI(title="WarnBridge", version="0.1.0", docs_url=None, redoc_url=None)

    def database() -> Iterator[Store]:
        store = Store(config.database, readonly=True)
        try:
            yield store
        finally:
            store.close()

    DB = Annotated[Store, Depends(database)]

    @app.middleware("http")
    async def headers(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health")
    def health(db: DB) -> dict[str, Any]:
        return {
            **db.health(
                rf_stale_after=config.rf_stale_after,
                heartbeat_stale_after=config.heartbeat_stale_after,
            ),
            "display_timezone": config.timezone,
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

    @app.get("/api/v1/alerts")
    def alerts(
        db: DB,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        source: Literal[
            "live", "all", "file", "stdin", "replay", "live_udp", "live_hdhomerun"
        ] = "live",
        status: str | None = None,
    ) -> dict[str, Any]:
        return db.alerts(limit, offset, source=None if source == "all" else source, status=status)

    @app.get("/api/v1/diagnostics")
    def diagnostics(
        db: DB, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
    ) -> dict[str, Any]:
        rows = db.db.execute(
            "SELECT id,session_id,processed_at,reason,length(raw_ts) AS bytes "
            "FROM observations WHERE state='rejected' ORDER BY id DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return {"items": [dict(r) for r in rows], "limit": limit, "offset": offset}

    web = Path(__file__).resolve().parent.parent / "web"
    app.mount("/assets", StaticFiles(directory=web), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    return app
