"""Alias de proyectos, importaciones manuales estables, y una fila por sesión real."""
import copy
import json
import re
from pathlib import Path

from config import CONFIG

METRICS = ('totalCost', 'totalTokens', 'inputTokens', 'outputTokens',
           'cacheCreationTokens', 'cacheReadTokens')

# Alias de config.json: {"Mi SaaS": "mi-saas"} unifica bajo "Mi SaaS" toda
# sesión cuya ruta matchee esa expresión regular. Sin alias, cada carpeta
# queda como su propio proyecto.
_ALIASES = [(name, re.compile(pattern, re.IGNORECASE))
            for name, pattern in CONFIG["projectAliases"].items()]


def canonical_project(project):
    for name, pattern in _ALIASES:
        if pattern.search(project or ''):
            return name
    return project


def consolidate(sessions, manual_path=None):
    manual_path = manual_path or Path(__file__).parent / 'manual_sessions.json'
    manual = json.loads(manual_path.read_text()) if manual_path.exists() else {}
    manual_sessions = [s for s in manual.get('sessions', []) if not str(s.get('id', '')).startswith('_')]
    rows = copy.deepcopy(sessions) + copy.deepcopy(manual_sessions)
    merged = {}
    for row in rows:
        row.setdefault('source', 'claude-desktop-cache' if row.get('agent') == 'claude' and row.get('project', '').startswith('(remoto)') else 'local-usage')
        row.setdefault('accountId', row['source'] + ':' + row['agent'])
        row.setdefault('account', 'Codex' if row['agent'] == 'codex' else 'Claude · fuente remota de esta Mac' if row['source'] == 'claude-desktop-cache' else 'Claude · fuente local de esta Mac' if row['agent'] == 'claude' else row['agent'])
        row.setdefault('projectOriginal', row['project'])
        row['project'] = canonical_project(row['project'])
        key = (row['agent'], row['accountId'], row['id'])
        if key not in merged:
            merged[key] = row
            continue
        existing = merged[key]
        # El extractor remoto emite filas por modelo, disjuntas, para la misma
        # sesión. Ignoramos filas de modelo repetidas para que importar sea idempotente.
        model_names = {m['model'] for m in existing['models']}
        unseen = [m for m in row['models'] if m['model'] not in model_names]
        if not unseen:
            continue
        existing['models'].extend(unseen)
        existing['modelsUsed'] = sorted({m['model'] for m in existing['models']})
        existing['totalCost'] = sum(m.get('cost', 0) for m in existing['models'])
        for field in METRICS[2:]:
            existing[field] = sum(m.get(field, 0) for m in existing['models'])
        existing['totalTokens'] = sum(existing[field] for field in METRICS[2:])
        existing['date'] = max(existing['date'], row['date'])
    notes = {k: v for k, v in (manual.get('projectNotes') or {}).items() if not k.startswith('_')}
    return list(merged.values()), notes
