#!/usr/bin/env python3
"""Build deterministic synthetic TS demos.

Run as python -m scripts.build_alert_demo; never contacts hardware.
"""

from pathlib import Path

from tests.fixtures.alert_examples import CMAC, cap
from tests.fixtures.synthetic import wrap

REFERENCE = "synthetic.warnbridge.example,demo-alert,2026-11-12T01:00:00Z"
messages = [
    cap(),
    cap("demo-update", "Update", references=REFERENCE, sent="2026-11-12T01:01:00Z"),
    cap("demo-cancel", "Cancel", references=REFERENCE, sent="2026-11-12T01:02:00Z"),
    cap("demo-test", status="Test"),
    cap("demo-expired", expires="2026-11-12T01:00:01Z"),
    cap("demo-open", expires="2026-11-14T01:00:00Z"),
    CMAC,
]
packets = []
cc = 0
for index, body in enumerate(messages):
    raw = wrap(body, ident=0x6AF3C24C + index, cc=cc)
    packets.append(raw)
    cc = (cc + len(raw) // 188) % 16
path = Path("tests/fixtures/alert-demo.ts")
path.write_bytes(b"".join(packets))
print(
    f"Built {path}: {len(messages)} synthetic messages, {path.stat().st_size} bytes. Replay only."
)
