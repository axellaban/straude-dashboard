"""Carga config.json (opcional) para no hardcodear nada propio de una máquina.

Sin config.json todo funciona con los valores por defecto: el dashboard
muestra cada carpeta como su propio proyecto y no destaca ninguno.
"""
import json
import os
from pathlib import Path

BASE = Path(__file__).parent
DEFAULTS = {
    "port": 8934,
    "projectAliases": {},
    "highlightProject": None,
    "backgroundIntervalSeconds": 45,
}


def load():
    cfg = dict(DEFAULTS)
    path = BASE / "config.json"
    if path.exists():
        try:
            user = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise SystemExit(f"config.json tiene un error de sintaxis: {e}")
        for key, value in user.items():
            if key.startswith("_"):
                continue  # claves de comentario
            cfg[key] = value
    cfg["projectAliases"] = {
        name: pattern
        for name, pattern in (cfg.get("projectAliases") or {}).items()
        if not name.startswith("_")
    }
    # La variable de entorno gana: permite correr dos instancias en puertos distintos.
    if os.environ.get("DASHBOARD_PORT"):
        cfg["port"] = int(os.environ["DASHBOARD_PORT"])
    return cfg


CONFIG = load()
