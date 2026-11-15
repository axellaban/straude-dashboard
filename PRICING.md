# Tarifas

Verificadas el 5 de octubre de 2026. Importes en USD por millón de tokens.

El dashboard carga `ccusage.json` en cada extracción, incluso en modo offline, y `pricing_sources.json` conserva fuentes, correspondencias y fecha de verificación. **Los costos representan equivalentes de API, no cargos de tus suscripciones.**

| Modelo | Entrada | Salida | Escritura de caché (5 min) | Lectura de caché |
|---|---:|---:|---:|---:|
| GPT-6.1 Sol | 2 | 10 | 2,50 | 0,10 |
| Claude Opus 5.5 | 4 | 20 | 5 | 0,20 |
| Claude Sonnet 5.5 | 2 | 10 | 2,50 | 0,20 |
| Gemini 3.1 Flash Lite (M50) | 0,25 | 1,50 | — | 0,025 |
| Gemini 3.6 Flash (M264) | 0,75 | 3,75 | — | 0,075 |
| Gemini 3.8 Flash (M322) | 0,75 | 3,75 | — | 0,075 |
| Qwen3-14B y Qwen2.5-14B por mlx-local | 0 | 0 | 0 | 0 |
| Big Pickle por OpenCode | 0 | 0 | 0 | 0 |

ccusage ya trae tarifas propias para los modelos que conoce. Esta tabla existe para los que no: modelos nuevos, modelos locales (costo cero) y los identificadores internos de Antigravity.

## Cómo actualizarlas

Las tarifas cambian. Para corregir o agregar un modelo hay que editar **los dos** archivos:

- `ccusage.json` → `defaults.pricingOverrides`, en **costo por token** (dividí la tarifa por millón entre 1.000.000). Es lo que usa ccusage para calcular.
- `pricing_sources.json` → `models`, en **USD por millón** más la fuente. Es lo que el dashboard muestra en el diálogo "Fuentes y cómo se calcula".

Si un modelo aparece sin tarifa, el dashboard lo avisa en el pie en vez de inventar un número: nunca estima un costo que no puede justificar.

## Advertencias

Las correspondencias M50/M264/M322 son estimadas a partir del registro documentado por Antigravity Context Window Monitor, que advierte que los identificadores pueden reasignarse. Las tarifas promocionales de Gemini 3.6/3.8 vencen el 31 de diciembre de 2026: para actividad posterior hay que revisar el precio oficial. No se infiere costo eléctrico de los modelos locales.

El recolector calcula tarifas por evento. Verificación con un ejemplo: 2.938.665 tokens de entrada sin caché × $2/M + 356.825 de salida × $10/M + 87.418.368 de lectura de caché × $0,10/M = $18,19.

## Fuentes

- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://platform.claude.com/docs/en/about-claude/pricing
- https://ai.google.dev/gemini-api/docs/pricing
- https://opencode.ai/docs/zen/
- https://github.com/AGI-is-going-to-arrive/Antigravity-Context-Window-Monitor/blob/main/README.md
