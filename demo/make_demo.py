#!/usr/bin/env python3
"""Genera un dashboard de demostración con datos inventados.

Sirve para dos cosas: ver el dashboard sin instalar nada ni tener historial de
uso, y producir las capturas del README sin exponer el consumo real de nadie.

Los datos son sintéticos y deterministas (semilla fija), pero los costos se
calculan con las tarifas reales de pricing_sources.json, así que los números
cierran si alguien los verifica a mano.

    python3 demo/make_demo.py          -> demo/dashboard-demo.html
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "demo" / "dashboard-demo.html"
SEED = 20261115

PRICING = json.loads((BASE / "pricing_sources.json").read_text())

# (modelo, agente, grupo) y cuánto peso tiene en el mix de la demo
MIX = [
    ("claude-opus-5-5",                        "claude",      "Claude",          30),
    ("claude-sonnet-5-5",                      "claude",      "Claude",          22),
    ("gpt-6.1-sol",                            "codex",       "Codex",           18),
    ("model_placeholder_m264",                 "antigravity", "Antigravity",     12),
    ("mlx-community/Qwen3-14B-4bit",           "opencode",    "Otros / locales",  9),
    ("big-pickle",                             "opencode",    "Otros / locales",  9),
]

PROJECTS = [
    # (ruta como la vería el extractor, peso, agentes que la tocan)
    ("~/code/mi-saas/api",        26, ("claude", "codex")),
    ("~/code/mi-saas/web",        18, ("claude", "codex", "opencode")),
    ("~/code/cliente-x/panel",    16, ("claude", "codex")),
    ("~/code/landing-nueva",       9, ("claude", "opencode")),
    ("~/code/scripts-internos",    7, ("opencode", "codex")),
    ("~/code/experimentos-rag",    6, ("claude",)),
]

TITLES = [
    "Migrar el login a passkeys", "Refactor del cliente de pagos",
    "Tests del importador de CSV", "Arreglar el N+1 del listado",
    "Caché de la home", "Webhooks de facturación",
    "Panel de métricas", "Migración de schema",
    "Rate limiting del API", "Exportar a PDF",
    "Buscador con embeddings", "Limpiar deuda del seed",
]


def rates(model):
    r = PRICING["models"][model]["ratesUSDPerMillion"]
    return {k: v / 1_000_000 for k, v in r.items()}


def cost_of(model, inp, out, cc, cr):
    r = rates(model)
    return round(
        inp * r["inputCostPerToken"] + out * r["outputCostPerToken"]
        + cc * r["cacheCreationInputTokenCost"] + cr * r["cacheReadInputTokenCost"], 6)


def build():
    rng = random.Random(SEED)
    today = date(2026, 11, 14)
    start = today - timedelta(days=56)

    models_by_agent = {}
    for model, agent, group, weight in MIX:
        models_by_agent.setdefault(agent, []).append((model, group, weight))

    sessions = []
    for i in range(64):
        # Más actividad en días de semana y hacia el final del período.
        day = start + timedelta(days=int(rng.triangular(0, 56, 44)))
        if day.weekday() >= 5 and rng.random() < 0.6:
            day += timedelta(days=2 - day.weekday() % 2)
        day = min(day, today)

        path, _w, agents = rng.choices(
            PROJECTS, weights=[p[1] for p in PROJECTS])[0]
        agent = rng.choice(agents)
        model, group, _w = rng.choices(
            models_by_agent[agent], weights=[m[2] for m in models_by_agent[agent]])[0]

        # Una sesión de agente: poca entrada nueva, mucha lectura de caché.
        scale = rng.choice([0.3, 0.6, 1.0, 1.0, 1.8, 3.2])
        inp = int(rng.uniform(40_000, 320_000) * scale)
        out = int(rng.uniform(25_000, 160_000) * scale)
        cc = int(rng.uniform(120_000, 900_000) * scale)
        cr = int(rng.uniform(4_000_000, 38_000_000) * scale)

        sessions.append({
            "id": f"demo-{i:03d}",
            "title": rng.choice(TITLES),
            "agent": agent,
            "group": group,
            "source": "local-usage",
            "accountId": f"local-usage:{agent}",
            "account": {"claude": "Claude · fuente local de esta Mac",
                        "codex": "Codex"}.get(agent, agent),
            "date": day.isoformat(),
            "lastActivity": f"{day.isoformat()}T{rng.randint(9, 22):02d}:{rng.randint(0, 59):02d}:00Z",
            "project": path,
            "projectOriginal": path,
            "models": [{
                "model": model, "cost": cost_of(model, inp, out, cc, cr),
                "inputTokens": inp, "outputTokens": out,
                "cacheCreationTokens": cc, "cacheReadTokens": cr,
                "missingPricing": False,
                "pricing": PRICING["models"].get(model),
            }],
            "modelsUsed": [model],
            "totalCost": cost_of(model, inp, out, cc, cr),
            "totalTokens": inp + out + cc + cr,
            "inputTokens": inp, "outputTokens": out,
            "cacheCreationTokens": cc, "cacheReadTokens": cr,
        })

    # Una sesión de Antigravity sin ruta de proyecto, como pasa de verdad.
    for i in range(6):
        day = today - timedelta(days=rng.randint(1, 40))
        inp, out, cc, cr = 180_000, 90_000, 0, 6_400_000
        model = "model_placeholder_m264"
        sessions.append({
            "id": f"demo-ag-{i}", "title": None, "agent": "antigravity",
            "group": "Antigravity", "source": "local-usage",
            "accountId": "local-usage:antigravity", "account": "antigravity",
            "date": day.isoformat(), "lastActivity": None,
            "project": "(antigravity: sin datos de proyecto)",
            "projectOriginal": "(antigravity: sin datos de proyecto)",
            "models": [{"model": model, "cost": cost_of(model, inp, out, cc, cr),
                        "inputTokens": inp, "outputTokens": out,
                        "cacheCreationTokens": cc, "cacheReadTokens": cr,
                        "missingPricing": False,
                        "pricing": PRICING["models"].get(model)}],
            "modelsUsed": [model], "totalCost": cost_of(model, inp, out, cc, cr),
            "totalTokens": inp + out + cc + cr, "inputTokens": inp,
            "outputTokens": out, "cacheCreationTokens": cc, "cacheReadTokens": cr,
        })

    # Un informe cargado a mano, para mostrar cómo se ve esa fuente.
    inp, out, cc, cr = 120_000, 740_000, 2_100_000, 148_000_000
    sessions.append({
        "id": "manual:cuenta-2:mi-saas:20261102", "title": "Sprint de gráficos (2da cuenta)",
        "agent": "claude", "group": "Claude", "source": "manual-user-report",
        "accountId": "cuenta-2", "account": "Claude · 2da cuenta",
        "date": "2026-11-02", "startDate": "2026-10-31", "lastActivity": None,
        "reportedAt": "2026-11-02", "dateBasis": "fecha del informe; última actividad no informada",
        "project": "Mi SaaS", "projectOriginal": "Mi SaaS · 2da cuenta",
        "costBasis": "registro informado por el usuario", "tokensApproximate": True,
        "models": [{"model": "claude-opus-5-5",
                    "cost": cost_of("claude-opus-5-5", inp, out, cc, cr),
                    "inputTokens": inp, "outputTokens": out,
                    "cacheCreationTokens": cc, "cacheReadTokens": cr,
                    "missingPricing": False,
                    "pricing": PRICING["models"].get("claude-opus-5-5")}],
        "modelsUsed": ["claude-opus-5-5"],
        "totalCost": cost_of("claude-opus-5-5", inp, out, cc, cr),
        "totalTokens": inp + out + cc + cr, "inputTokens": inp, "outputTokens": out,
        "cacheCreationTokens": cc, "cacheReadTokens": cr,
    })

    # Alias: unifica las dos carpetas de mi-saas bajo un solo proyecto,
    # igual que haría projectAliases en config.json.
    for s in sessions:
        if "mi-saas" in s["project"]:
            s["project"] = "Mi SaaS"

    sessions.sort(key=lambda s: s["date"])
    keys = ("totalCost", "totalTokens", "inputTokens", "outputTokens",
            "cacheCreationTokens", "cacheReadTokens")
    return {
        "generatedAt": f"{today.isoformat()}T21:30:00+00:00",
        "demo": True,
        "highlightProject": "Mi SaaS",
        "pricingInfo": PRICING,
        "projectNotes": {"Mi SaaS": "Datos de demostración, inventados. Incluye un informe "
                                    "manual del 2/11 para mostrar cómo se ve esa fuente junto "
                                    "a las automáticas."},
        "totals": {k: round(sum(s[k] for s in sessions), 6) for k in keys},
        "sessions": sessions,
    }


def main():
    data = build()
    template = (BASE / "template.html").read_text()
    html = template.replace("__DASHBOARD_DATA__", json.dumps(data, separators=(",", ":")))
    OUT.write_text(html)
    t = data["totals"]
    print(f"{len(data['sessions'])} sesiones · US${t['totalCost']:,.2f} · "
          f"{t['totalTokens'] / 1e9:.2f} mil M de tokens")
    print(f"Escrito {OUT.relative_to(BASE)}")


if __name__ == "__main__":
    main()
