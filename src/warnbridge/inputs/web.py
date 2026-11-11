"""Optional saved-response import only; no unverified endpoint contract/polling."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from warnbridge.storage.store import Store, utc_now


def import_saved(path: Path, database: str) -> dict[str, Any]:
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("saved web response exceeds 2 MiB limit")
    value = json.loads(raw)
    if not isinstance(value, (dict, list)):
        raise ValueError("expected JSON object or array; response contract is unverified")
    store = Store(database)
    try:
        with store.db:
            cursor = store.db.execute(
                "INSERT INTO web_observations(imported_at,source,sha256,"
                "raw_json,comparison) VALUES(?,?,?,?,?)",
                (
                    utc_now(),
                    "saved_json",
                    sha256(raw).hexdigest(),
                    raw,
                    "not_comparable: mapping and API contract unverified",
                ),
            )
            store.db.execute(
                "DELETE FROM web_observations WHERE id NOT IN "
                "(SELECT id FROM web_observations ORDER BY id DESC LIMIT 100)"
            )
        return {"id": cursor.lastrowid, "source": "saved_json", "comparison": "not_comparable"}
    finally:
        store.close()
