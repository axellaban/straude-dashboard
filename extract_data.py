#!/usr/bin/env python3
"""
Extrae uso de agentes de IA (Claude, Codex, Antigravity, y el resto) desde
ccusage + fuentes locales crudas, y arma data.json para el dashboard.

Fuentes:
  - ccusage (unificado, --json): agente, modelos, tokens, costo, fecha (metadata.lastActivity)
  - ~/.claude/projects/*/<sessionId>.jsonl -> cwd real del proyecto (Claude)
  - ~/.codex/sessions/<period>.jsonl       -> session_meta.cwd (Codex)
  - ~/.local/share/opencode/opencode.db    -> session.directory (OpenCode / modelos locales)

Antigravity y otros agentes sin fuente de proyecto local conocida quedan
agrupados sin desglose de proyecto (limitación documentada en el dashboard).
"""
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from config import CONFIG
from project_sessions import consolidate

HOME = Path.home()
OUT_PATH = Path(__file__).parent / "data.json"

# Cuando esto se lanza desde fuera de una shell normal (doble clic en la app
# del Escritorio, LaunchAgent, etc.) el PATH heredado es mínimo y no incluye
# node/npm/ccusage aunque estén instalados. Los agregamos a mano.
for _extra in (
    HOME / "node" / "bin",
    HOME / "Library" / "pnpm" / "bin",
    HOME / ".local" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/opt/homebrew/sbin"),
    Path("/usr/local/bin"),
):
    _extra_str = str(_extra)
    if _extra.is_dir() and _extra_str not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _extra_str + os.pathsep + os.environ.get("PATH", "")

KNOWN_GROUPS = {
    "claude": "Claude",
    "codex": "Codex",
    "antigravity": "Antigravity",
}
OTHER_GROUP = "Otros / locales"


def ccusage_command():
    """Prefiere el binario global (rápido, sin lookup a npm en cada corrida).
    Si no está instalado, cae a npx (más lento: resuelve versión por red)."""
    from shutil import which
    global_bin = which("ccusage") or None
    if not global_bin:
        fallback = HOME / "node" / "bin" / "ccusage"
        if fallback.exists():
            global_bin = str(fallback)
    if global_bin:
        return [global_bin]
    npx_bin = which("npx") or str(HOME / "node" / "bin" / "npx")
    return [npx_bin, "ccusage@latest"]


def run_ccusage_session_json(since="20200101", offline=False):
    cmd = ccusage_command() + ["session", "--json", "--since", since,
                               "--config", str(Path(__file__).parent / "ccusage.json")]
    if offline:
        cmd.append("--offline")
    env = dict(os.environ, DO_NOT_TRACK="1")
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180)
    if result.returncode != 0:
        print("ccusage stderr:", result.stderr, file=sys.stderr)
        result.check_returncode()
    return json.loads(result.stdout)


def build_claude_index():
    """sessionId (filename sin extensión) -> ruta completa del jsonl."""
    index = {}
    projects_dir = HOME / ".claude" / "projects"
    if not projects_dir.exists():
        return index
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.glob("*.jsonl"):
            index[f.stem] = f
    return index


def build_workflow_index():
    """workflow runId (wf_...) -> ruta al .jsonl de la sesión padre que lo lanzó."""
    index = {}
    projects_dir = HOME / ".claude" / "projects"
    if not projects_dir.exists():
        return index
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        for wf_file in proj_dir.glob("*/workflows/*.json"):
            run_id = wf_file.stem
            session_folder = wf_file.parent.parent
            sibling_jsonl = proj_dir / f"{session_folder.name}.jsonl"
            if sibling_jsonl.exists():
                index[run_id] = sibling_jsonl
    return index


def find_cwd_in_jsonl(path, max_lines=200):
    try:
        with open(path, "r", errors="ignore") as fh:
            for i, line in enumerate(fh):
                if i >= max_lines:
                    break
                if '"cwd"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = d.get("cwd")
                if cwd:
                    return cwd
                payload = d.get("payload") or {}
                cwd = payload.get("cwd")
                if cwd:
                    return cwd
    except OSError:
        return None
    return None


def resolve_claude_project(session_id, claude_index, workflow_index, cache):
    if session_id in cache:
        return cache[session_id]
    path = claude_index.get(session_id) or workflow_index.get(session_id)
    project = find_cwd_in_jsonl(path) if path else None
    cache[session_id] = project
    return project


def resolve_codex_project(period, cache):
    if period in cache:
        return cache[period]
    path = HOME / ".codex" / "sessions" / f"{period}.jsonl"
    project = find_cwd_in_jsonl(path) if path.exists() else None
    cache[period] = project
    return project


def build_opencode_index():
    """session id -> directory, from the local sqlite db."""
    index = {}
    db_path = HOME / ".local" / "share" / "opencode" / "opencode.db"
    if not db_path.exists():
        return index
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT id, directory FROM session")
        for sid, directory in cur.fetchall():
            index[sid] = directory
        con.close()
    except sqlite3.Error as e:
        print("opencode db read error:", e, file=sys.stderr)
    return index


def shorten_project(path_str):
    if not path_str:
        return None
    home_str = str(HOME)
    if path_str.startswith(home_str):
        rest = path_str[len(home_str):]
        return "~" + rest if rest else "~"
    return path_str


def collect_desktop_remote_sessions():
    """Sesiones de Cowork/Code que corrieron en un sandbox remoto (lanzadas
    desde la app de Escritorio) y por eso no tienen .jsonl local: ccusage no
    las ve. Se extraen de la caché local de IndexedDB de la app (ver
    extract_desktop_conversations.py) corriendo ese script en su propio
    venv (necesita ccl_chromium_reader, que no hace falta instalar en el
    Python del sistema). Si algo falla, se devuelve lista vacía: esta fuente
    es un complemento, nunca debe tumbar el dashboard principal."""
    venv_python = Path(__file__).parent / ".venv-chatextract" / "bin" / "python3"
    script = Path(__file__).parent / "extract_desktop_conversations.py"
    if not venv_python.exists() or not script.exists():
        return []
    try:
        result = subprocess.run(
            [str(venv_python), str(script)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print("extract_desktop_conversations stderr:", result.stderr, file=sys.stderr)
            return []
        return json.loads(result.stdout)
    except Exception as e:  # noqa: BLE001
        print(f"collect_desktop_remote_sessions: se omite ({e})", file=sys.stderr)
        return []


def collect(offline=False):
    """Corre la extracción completa y devuelve el dict de datos (sin tocar disco).
    offline=True usa pricing cacheado de ccusage (mucho más rápido, ~7s vs ~17s,
    apto para refrescos automáticos en segundo plano)."""
    raw = run_ccusage_session_json(offline=offline)
    sessions = raw.get("session", [])

    claude_index = build_claude_index()
    workflow_index = build_workflow_index()
    opencode_index = build_opencode_index()
    claude_cache = {}
    codex_cache = {}

    pricing_info = json.loads((Path(__file__).parent / "pricing_sources.json").read_text())
    out_sessions = []
    for s in sessions:
        agent = s.get("agent", "unknown")
        period = s.get("period", "")
        last_activity = (s.get("metadata") or {}).get("lastActivity")
        date = last_activity[:10] if last_activity else None

        project_raw = None
        if agent == "claude":
            project_raw = resolve_claude_project(period, claude_index, workflow_index, claude_cache)
        elif agent == "codex":
            project_raw = resolve_codex_project(period, codex_cache)
        elif agent == "opencode":
            project_raw = opencode_index.get(period)

        project = shorten_project(project_raw) or f"({agent}: sin datos de proyecto)"
        group = KNOWN_GROUPS.get(agent, OTHER_GROUP)

        models = []
        for mb in s.get("modelBreakdowns", []):
            models.append({
                "model": mb.get("modelName"),
                "cost": mb.get("cost", 0) or 0,
                "inputTokens": mb.get("inputTokens", 0) or 0,
                "outputTokens": mb.get("outputTokens", 0) or 0,
                "cacheCreationTokens": mb.get("cacheCreationTokens", 0) or 0,
                "cacheReadTokens": mb.get("cacheReadTokens", 0) or 0,
                "missingPricing": bool(mb.get("missingPricing", False)),
                "pricing": pricing_info["models"].get(mb.get("modelName")),
            })

        out_sessions.append({
            "id": period,
            "agent": agent,
            "group": group,
            "date": date,
            "lastActivity": last_activity,
            "project": project,
            "models": models,
            "modelsUsed": s.get("modelsUsed", []),
            "totalCost": s.get("totalCost", 0) or 0,
            "totalTokens": s.get("totalTokens", 0) or 0,
            "inputTokens": s.get("inputTokens", 0) or 0,
            "outputTokens": s.get("outputTokens", 0) or 0,
            "cacheCreationTokens": s.get("cacheCreationTokens", 0) or 0,
            "cacheReadTokens": s.get("cacheReadTokens", 0) or 0,
        })

    remote_sessions = collect_desktop_remote_sessions()
    for session in remote_sessions:
        session["group"] = KNOWN_GROUPS.get(session["agent"], OTHER_GROUP)
    out_sessions.extend(remote_sessions)

    out_sessions, project_notes = consolidate(out_sessions)
    out_sessions = [s for s in out_sessions if s["date"]]
    out_sessions.sort(key=lambda s: s["date"])

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "highlightProject": CONFIG["highlightProject"],
        "pricingInfo": pricing_info,
        "projectNotes": project_notes,
        "totals": {key: sum(s.get(key, 0) or 0 for s in out_sessions)
                   for key in ("totalCost", "totalTokens", "inputTokens", "outputTokens",
                               "cacheCreationTokens", "cacheReadTokens")},
        "sessions": out_sessions,
    }


def main():
    print("Consultando ccusage (esto puede tardar unos segundos)...", file=sys.stderr)
    data = collect()
    print(f"{len(data['sessions'])} sesiones encontradas.", file=sys.stderr)
    OUT_PATH.write_text(json.dumps(data, indent=None, separators=(",", ":")))
    print(f"Escrito {OUT_PATH} con {len(data['sessions'])} sesiones.", file=sys.stderr)


if __name__ == "__main__":
    main()
