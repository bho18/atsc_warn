"""Container health checks read local API/database state; never contact a tuner."""

import sys
import urllib.request

from warnbridge.config import load_config
from warnbridge.storage.store import Store

config = load_config(sys.argv[1])
if "--receiver" in sys.argv[2:]:
    store = Store(config.database, readonly=True)
    try:
        raise SystemExit(0 if store.health()["connection"]["state"] == "recent" else 1)
    finally:
        store.close()
else:
    host = "127.0.0.1" if config.bind == "0.0.0.0" else config.bind
    # Never send an internal health request through an inherited HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://{host}:{config.port}/api/v1/health", timeout=2) as response:
        raise SystemExit(0 if response.status == 200 else 1)
