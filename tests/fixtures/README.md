# Fixture provenance

- `golden.py`: exact supplied XML/header/CRC literals, with synthetic TS framing.
- `reconstructed.ts`: 752 bytes, synthetic four-packet demonstration generated from
  golden.py. NOT the 56-packet original capture. CC 14,15,0,1.
- `cap.xml`: synthetic Test-status, expired CAP-like XML; multiple languages,
  areas, repeated parameters, extensions and escaped hostile text. No XSD claim.
- `synthetic.py`: convenience wrapping for synthetic/corruption tests. Its CRC is
  computed, so it is not used as independent CRC evidence.

- `alert_examples.py` / `alert-demo.ts`: seven deterministic synthetic messages
  (six CAP including Update/Cancel/Test/expired examples, one unverified CMAC
  field-review example). Fixed November 2026 dates, DEMO ONLY text; no real alerts,
  XSD/signature claims or independent CRC vectors. Build with
  `.venv/bin/python -m scripts.build_alert_demo`. Replay source must stay replay.

No actual user captures or copied historical implementation code are included.
