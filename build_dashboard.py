#!/usr/bin/env python3
"""Inyecta data.json dentro de template.html -> dashboard.html (autocontenido)."""
import json
from pathlib import Path

BASE = Path(__file__).parent
data = json.loads((BASE / "data.json").read_text())
template = (BASE / "template.html").read_text()

out = template.replace("__DASHBOARD_DATA__", json.dumps(data, separators=(",", ":")))
(BASE / "dashboard.html").write_text(out)
print(f"Escrito {BASE / 'dashboard.html'} ({len(out)} bytes)")
