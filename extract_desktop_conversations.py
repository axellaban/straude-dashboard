#!/usr/bin/env python3
"""
Extrae sesiones de "Claude Code"/"Cowork" lanzadas desde la app de Escritorio
que corrieron en un sandbox remoto (Cowork en la nube), y que por eso NUNCA
tocan ~/.claude/projects en esta Mac -> ccusage no las ve.

La app cachea localmente (para que la UI muestre el historial) una copia de
esas conversaciones en IndexedDB (base "claude-conversation-store", dentro de
Application Support/Claude). Esa copia SÍ incluye el uso real de tokens/costo
por turno (los mismos eventos "result" que produce el CLI), así que se puede
reconstruir el consumo de las sesiones remotas que faltan.

Limitaciones conocidas (documentadas, no "bugs" a arreglar):
  - Formato interno no oficial de Chromium (IndexedDB LevelDB + V8 structured
    clone). Si Chrome/Electron cambia el layout, esto puede romperse.
  - Solo están las conversaciones que la app todavía tiene cacheadas (Chrome
    puede haber recolectado blobs viejos -> esos registros se saltean, no se
    inventan datos).
  - Las conversaciones "chat" (charla normal, no agente) NO tienen tokens acá
    ni en ningún otro lado local: el plan Pro/Max no expone ese dato por
    mensaje, solo un % de uso agregado (ver plan-usage-history.json). Por eso
    esta función no las incluye.
  - El contador de costo/tokens que manda la app en cada evento "result" es
    ACUMULATIVO dentro de una sub-sesión y se resetea cuando hay un
    "compact". Se suma el máximo de cada tramo (antes de cada reset) en vez
    de tomar el último valor, para no subcontar.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HOME = Path.home()
CLAUDE_APP_SUPPORT = HOME / "Library" / "Application Support" / "Claude"
IDB_LEVELDB = CLAUDE_APP_SUPPORT / "IndexedDB" / "https_claude.ai_0.indexeddb.leveldb"
IDB_BLOB = CLAUDE_APP_SUPPORT / "IndexedDB" / "https_claude.ai_0.indexeddb.blob"

GROUP_NAME = "Claude (Cowork remoto)"
CONVO_DB_NAME = "claude-conversation-store"
TREES_STORE_NAME = "trees"

# No vale la pena copiar/parsear el IndexedDB (puede pesar decenas de MB) en
# cada refresh de 45s del server. Se cachea el resultado unos minutos.
_CACHE_TTL_SECONDS = 600
_cache = {"at": 0.0, "sessions": []}


def _safe_snapshot(tmp_dir: Path):
    """Copia de solo lectura del IndexedDB en vivo. Nunca escribe sobre el
    original: si la app de Escritorio está abierta y escribiendo, en el peor
    caso copiamos un archivo a mitad de escritura y ese registro puntual
    falla al parsear (se descarta más abajo), pero no se toca el original."""
    if not IDB_LEVELDB.exists():
        return None, None
    dst_leveldb = tmp_dir / "leveldb"
    dst_blob = tmp_dir / "blob"
    shutil.copytree(IDB_LEVELDB, dst_leveldb)
    if IDB_BLOB.exists():
        shutil.copytree(IDB_BLOB, dst_blob)
    else:
        dst_blob = None
    return dst_leveldb, dst_blob


def _iter_tree_records(db, db_id, store_id):
    """Reimplementación de IndexedDb.iterate_records que no aborta toda la
    iteración cuando un registro puntual referencia un blob externo que ya
    no existe (blob recolectado por Chrome). La librería original corta el
    generador entero ante la primera excepción."""
    from ccl_chromium_reader.ccl_chromium_indexeddb import (
        IdbKey,
        _le_varint_from_bytes,
        ccl_blink_value_deserializer,
        ccl_v8_value_deserializer,
        ccl_leveldb,
    )
    from ccl_chromium_reader import ccl_chromium_indexeddb as idb_mod

    blink_deserializer = ccl_blink_value_deserializer.BlinkV8Deserializer()
    prefix = idb_mod.IndexedDb.make_prefix(db_id, store_id, 1)

    for record in db._fetched_records:  # noqa: SLF001 (API interna, sin alternativa pública)
        if not record.key.startswith(prefix):
            continue
        if record.state != ccl_leveldb.KeyState.Live:
            continue
        if not record.value:
            continue
        key = IdbKey(record.key[len(prefix):])
        try:
            _version, varint_raw = _le_varint_from_bytes(record.value)
            val_idx = len(varint_raw)
            precursor = db.read_record_precursor(key, db_id, store_id, record.value[val_idx:], None)
            if precursor is None:
                continue
            _blink_version, obj_raw, _trailer, _external_path = precursor
            deserializer = ccl_v8_value_deserializer.Deserializer(obj_raw, host_object_delegate=blink_deserializer.read)
            value = deserializer.read()
        except Exception:
            continue
        yield key, value


def _dedupe_latest(records):
    """Quedarse con la versión más reciente (mayor fetchedAt) de cada
    conversationUuid; LevelDB conserva versiones viejas hasta compactar."""
    best = {}
    for _key, value in records:
        if not isinstance(value, dict):
            continue
        cu = value.get("conversationUuid")
        if not cu:
            continue
        fetched_at = value.get("fetchedAt") or 0
        if cu not in best or fetched_at >= best[cu].get("fetchedAt", 0):
            best[cu] = value
    return best


def _extract_flat_messages(conversation):
    """Devuelve una lista plana de dicts tipo evento (los que traen
    session_id / modelUsage / usage / total_cost_usd), para 'code' y
    'cowork' por igual pese a que la forma del árbol difiere:
      - code:   tree.messages -> lista directa de eventos
      - cowork: tree.events   -> lista de {kind, payload}, nos interesa
                                  kind == "message" -> payload es el evento
    """
    tree = conversation.get("tree") or {}
    if "messages" in tree:
        return [m for m in tree.get("messages", []) if isinstance(m, dict)]
    if "events" in tree:
        out = []
        for e in tree.get("events", []):
            if isinstance(e, dict) and e.get("kind") == "message":
                payload = e.get("payload")
                if isinstance(payload, dict):
                    out.append(payload)
        return out
    return []


def _sum_with_resets(events):
    """Suma tokens/costo por (session_id, modelo) tratando cada serie como
    un contador acumulativo-con-reset: cuando el costo baja respecto al
    evento anterior, asumimos un 'compact' y arrancamos un tramo nuevo. El
    total real es la suma del máximo de cada tramo."""
    # state[(session_id, model)] = {"prev_cost":..., "segment_max":{campo: valor}, "total":{campo: valor}}
    fields = ("inputTokens", "outputTokens", "cacheCreationInputTokens", "cacheReadInputTokens", "costUSD")
    state = {}

    for ev in events:
        session_id = ev.get("session_id") or "sin-session-id"
        model_usage = ev.get("modelUsage")
        if not isinstance(model_usage, dict):
            continue
        for model, usage in model_usage.items():
            if not isinstance(usage, dict):
                continue
            k = (session_id, model)
            st = state.setdefault(k, {"prev_cost": 0.0, "segment": {f: 0.0 for f in fields}, "total": {f: 0.0 for f in fields}})
            cost_now = float(usage.get("costUSD") or 0)
            if cost_now < st["prev_cost"] - 1e-9:
                # reset detectado: el tramo anterior ya terminó, se archiva
                for f in fields:
                    st["total"][f] += st["segment"][f]
                st["segment"] = {f: float(usage.get(f) or 0) for f in fields}
            else:
                for f in fields:
                    st["segment"][f] = max(st["segment"][f], float(usage.get(f) or 0))
            st["prev_cost"] = cost_now

    # cerrar el último tramo de cada serie
    totals = {}  # (session_id, model) -> dict de totales
    for k, st in state.items():
        for f in fields:
            st["total"][f] += st["segment"][f]
        totals[k] = st["total"]
    return totals


def _guess_label(events):
    for ev in events:
        cwd = ev.get("cwd")
        if cwd and isinstance(cwd, str):
            return cwd
    return None


def _load_local_session_ids():
    """session_id (nombre de archivo sin extensión) de todo lo que YA está
    en ~/.claude/projects, para no duplicar sesiones que ccusage ya cuenta."""
    ids = set()
    projects_dir = HOME / ".claude" / "projects"
    if not projects_dir.exists():
        return ids
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.glob("*.jsonl"):
            ids.add(f.stem)
    return ids


def collect_remote_sessions(force=False):
    """Devuelve sesiones (mismo shape que extract_data.out_sessions) para
    conversaciones 'code'/'cowork' cacheadas por la app de Escritorio cuyo
    session_id NO tiene un .jsonl local (o sea: corrieron en un sandbox
    remoto y ccusage nunca las va a poder ver)."""
    now = time.time()
    if not force and (now - _cache["at"]) < _CACHE_TTL_SECONDS:
        return _cache["sessions"]

    sessions = []
    try:
        sessions = _collect_uncached()
    except Exception as e:  # noqa: BLE001
        print(f"extract_desktop_conversations: fallo silencioso, se omite ({e})", file=sys.stderr)
        sessions = _cache["sessions"]  # preferir el último dato bueno antes que romper el dashboard

    _cache["at"] = now
    _cache["sessions"] = sessions
    return sessions


def _collect_uncached():
    if not IDB_LEVELDB.exists():
        return []

    try:
        from ccl_chromium_reader import ccl_chromium_indexeddb as idb
    except ImportError:
        print("extract_desktop_conversations: falta ccl_chromium_reader (pip install en .venv-chatextract), se omite", file=sys.stderr)
        return []

    local_ids = _load_local_session_ids()

    with tempfile.TemporaryDirectory(prefix="straude-idb-") as tmp:
        tmp_dir = Path(tmp)
        dst_leveldb, dst_blob = _safe_snapshot(tmp_dir)
        if dst_leveldb is None:
            return []

        db = idb.IndexedDb(dst_leveldb, dst_blob)

        db_id = None
        for d in db.global_metadata.db_ids:
            if d.name == CONVO_DB_NAME:
                db_id = d.dbid_no
                break
        if db_id is None:
            return []

        store_id = None
        for sid in range(0, 10):
            try:
                name = db.get_object_store_metadata(db_id, sid, idb.ObjectStoreMetadataType.StoreName)
            except Exception:
                continue
            if name == TREES_STORE_NAME:
                store_id = sid
                break
        if store_id is None:
            return []

        records = list(_iter_tree_records(db, db_id, store_id))
        conversations = _dedupe_latest(records)

    out_sessions = []
    for cu, conv in conversations.items():
        product = conv.get("product")
        if product not in ("code", "cowork"):
            continue  # "chat" no tiene tokens locales, no hay nada que sumar

        events = _extract_flat_messages(conv)
        if not events:
            continue

        totals_by_key = _sum_with_resets(events)
        label = _guess_label(events)
        conv_updated = conv.get("conversationUpdatedAt")
        date = None
        if conv_updated:
            from datetime import datetime, timezone
            try:
                date = datetime.fromtimestamp(conv_updated / 1000, tz=timezone.utc).date().isoformat()
            except (OverflowError, OSError, ValueError):
                date = None

        for (session_id, model), totals in totals_by_key.items():
            if session_id in local_ids:
                continue  # ya está contado vía ccusage/~/.claude/projects, no duplicar
            if totals["costUSD"] <= 0 and totals["inputTokens"] <= 0 and totals["outputTokens"] <= 0:
                continue

            total_tokens = (
                totals["inputTokens"] + totals["outputTokens"]
                + totals["cacheCreationInputTokens"] + totals["cacheReadInputTokens"]
            )
            project_label = f"(remoto) {label}" if label else f"({product}: sandbox remoto, sin cwd)"

            out_sessions.append({
                "id": session_id,
                "title": conv.get("name") or conv.get("title") or None,
                "source": "claude-desktop-cache",
                "agent": "claude",
                "group": GROUP_NAME,
                "date": date,
                "lastActivity": None,
                "project": project_label,
                "models": [{
                    "model": model,
                    "cost": totals["costUSD"],
                    "inputTokens": int(totals["inputTokens"]),
                    "outputTokens": int(totals["outputTokens"]),
                    "cacheCreationTokens": int(totals["cacheCreationInputTokens"]),
                    "cacheReadTokens": int(totals["cacheReadInputTokens"]),
                    "missingPricing": False,
                }],
                "modelsUsed": [model],
                "totalCost": totals["costUSD"],
                "totalTokens": int(total_tokens),
                "inputTokens": int(totals["inputTokens"]),
                "outputTokens": int(totals["outputTokens"]),
                "cacheCreationTokens": int(totals["cacheCreationInputTokens"]),
                "cacheReadTokens": int(totals["cacheReadInputTokens"]),
            })

    return [s for s in out_sessions if s["date"]]


if __name__ == "__main__":
    import json
    sessions = collect_remote_sessions(force=True)
    print(f"{len(sessions)} sesiones remotas encontradas (no estaban en ~/.claude/projects).", file=sys.stderr)
    print(json.dumps(sessions, indent=2, ensure_ascii=False))
