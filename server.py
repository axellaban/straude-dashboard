#!/usr/bin/env python3
"""
Servidor local del dashboard.

- Un hilo en segundo plano recalcula el uso real (ccusage + fuentes locales)
  cada BACKGROUND_INTERVAL segundos, en modo offline (pricing cacheado, rápido).
  Las requests a /api/data siempre devuelven lo último calculado, sin bloquear
  esperando a ccusage (que puede tardar varios segundos escaneando disco).
- /api/data?force=1 (botón "Actualizar ahora") sí espera un recálculo fresco,
  con pricing en vivo (no offline), para una lectura exacta a demanda.
"""
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

os.environ.setdefault("DO_NOT_TRACK", "1")

sys.path.insert(0, str(Path(__file__).parent))
import extract_data  # noqa: E402
from config import CONFIG  # noqa: E402

BASE = Path(__file__).parent
PORT = CONFIG["port"]
# Segundos entre refrescos automáticos (offline, rápidos). Editable en config.json.
BACKGROUND_INTERVAL = CONFIG["backgroundIntervalSeconds"]

_lock = threading.Lock()
_cache = {"data": None, "error": None}
_ready = threading.Event()


def _refresh(offline):
    try:
        data = extract_data.collect(offline=offline)
        with _lock:
            _cache["data"] = data
            _cache["error"] = None
    except Exception as e:  # noqa: BLE001
        with _lock:
            _cache["error"] = str(e)
        print(f"refresh error (offline={offline}): {e}", file=sys.stderr)
    finally:
        _ready.set()


def background_loop():
    while True:
        _refresh(offline=True)
        time.sleep(BACKGROUND_INTERVAL)


def get_cached():
    _ready.wait(timeout=120)
    with _lock:
        return _cache["data"], _cache["error"]


CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript",
    ".json": "application/json",
    ".css": "text/css",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/data":
            qs = parse_qs(parsed.query)
            force = qs.get("force", ["0"])[0] == "1"
            if force:
                _refresh(offline=False)
            data, error = get_cached()
            if data is None:
                self._send_json({"error": error or "sin datos todavía"}, status=503)
                return
            self._send_json(data)
            return

        path = parsed.path.lstrip("/") or "dashboard.html"
        file_path = (BASE / path).resolve()
        if BASE not in file_path.parents and file_path != BASE:
            self.send_response(403)
            self.end_headers()
            return
        if not file_path.exists() or not file_path.is_file():
            file_path = BASE / "dashboard.html"
        if file_path.name == "dashboard.html" and not file_path.exists():
            # Instalación limpia: todavía nadie corrió refresh.sh, así que no hay
            # dashboard.html. Se arma al vuelo desde la plantilla con lo que haya
            # en caché, para que el server funcione sin un paso previo.
            self._send_rendered_template()
            return
        ctype = CONTENT_TYPES.get(file_path.suffix, "application/octet-stream")
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_rendered_template(self):
        data, _error = get_cached()
        if data is None:
            data = {"sessions": [], "totals": {}, "pricingInfo": {},
                    "projectNotes": {}, "highlightProject": None}
        template = (BASE / "template.html").read_text()
        html = template.replace("__DASHBOARD_DATA__", json.dumps(data, separators=(",", ":")))
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[".html"])
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # el cliente cortó la conexión (navegación, cierre de pestaña)


def main():
    print("Cargando datos iniciales (primera vez puede tardar ~15-20s)...", file=sys.stderr)
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    get_cached()  # espera la primera carga antes de anunciar el server listo

    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}/"
    print(f"Dashboard en {url}  (Ctrl+C para salir)")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
