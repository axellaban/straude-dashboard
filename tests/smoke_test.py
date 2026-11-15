#!/usr/bin/env python3
"""Prueba de humo: levanta el server con datos falsos y verifica las rutas.

No necesita ccusage ni historial de uso. Corré:  python3 tests/smoke_test.py
"""
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

FAKE = {
    "generatedAt": "2026-11-15T00:00:00+00:00", "highlightProject": "Mi SaaS",
    "pricingInfo": {"models": {}}, "projectNotes": {"Mi SaaS": "nota de prueba"},
    "totals": {"totalCost": 12.5, "totalTokens": 1000, "inputTokens": 100,
               "outputTokens": 100, "cacheCreationTokens": 100, "cacheReadTokens": 700},
    "sessions": [{
        "id": "s1", "agent": "claude", "group": "Claude", "date": "2026-11-10",
        "lastActivity": "2026-11-10T10:00:00Z", "project": "Mi SaaS",
        "source": "local-usage",
        "models": [{"model": "claude-opus-5-5", "cost": 12.5, "inputTokens": 100,
                    "outputTokens": 100, "cacheCreationTokens": 100,
                    "cacheReadTokens": 700, "missingPricing": False}],
        "modelsUsed": ["claude-opus-5-5"], "totalCost": 12.5, "totalTokens": 1000,
        "inputTokens": 100, "outputTokens": 100, "cacheCreationTokens": 100,
        "cacheReadTokens": 700}],
}

PORT = 8957


def main():
    import extract_data
    extract_data.collect = lambda offline=False: FAKE
    import server
    server.PORT = PORT

    threading.Thread(target=server.main, daemon=True).start()
    time.sleep(2.5)
    base = f"http://127.0.0.1:{PORT}"

    html = urllib.request.urlopen(base + "/").read().decode()
    assert "__DASHBOARD_DATA__" not in html, "la plantilla quedó sin datos inyectados"
    assert "Mi SaaS" in html, "los datos no llegaron al HTML"
    print(f"ok  /              HTML servido sin dashboard.html ({len(html)} bytes)")

    api = json.loads(urllib.request.urlopen(base + "/api/data").read())
    assert api["totals"]["totalCost"] == 12.5, "el API no devolvió los totales"
    print(f"ok  /api/data      {len(api['sessions'])} sesión, costo {api['totals']['totalCost']}")

    assert urllib.request.urlopen(base + "/template.html").status == 200
    print("ok  /template.html  archivos estáticos")

    import project_sessions
    assert project_sessions.canonical_project("~/code/algo") == "~/code/algo"
    print("ok  alias           sin config.json no toca los nombres")

    print("\nTodo en orden.")


if __name__ == "__main__":
    main()
