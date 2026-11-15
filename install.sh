#!/bin/bash
# Instalador del dashboard local. Idempotente: podés correrlo de nuevo sin romper nada.
set -uo pipefail
cd "$(dirname "$0")"

YES=0
[[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && YES=1

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
ask() {
  [[ $YES -eq 1 ]] && return 0
  read -r -p "  → $1 [S/n] " r
  [[ -z "$r" || "$r" =~ ^[SsYy]$ ]]
}

say "1. Requisitos"

if ! command -v python3 >/dev/null 2>&1; then
  warn "No encontré python3. Instalalo y volvé a correr este script."
  exit 1
fi
ok "python3 $(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"

IS_MAC=0
[[ "$(uname -s)" == "Darwin" ]] && IS_MAC=1
if [[ $IS_MAC -eq 1 ]]; then
  ok "macOS detectado"
else
  warn "No es macOS: el dashboard y ccusage funcionan igual, pero el launcher de un clic y el extractor de sesiones remotas son solo para Mac."
fi

say "2. ccusage (de dónde salen los datos)"

if command -v ccusage >/dev/null 2>&1; then
  ok "ccusage ya instalado ($(command -v ccusage))"
elif command -v npm >/dev/null 2>&1; then
  if ask "Instalar ccusage global con npm? (si no, se usa npx y cada corrida es más lenta)"; then
    npm install -g ccusage && ok "ccusage instalado" || warn "Falló el install global; el dashboard va a caer a npx."
  else
    warn "Sin ccusage global: el dashboard usa 'npx ccusage@latest' (más lento, necesita red)."
  fi
else
  warn "No encontré npm. Instalá Node.js para que el dashboard pueda leer tu uso: https://nodejs.org"
fi

say "3. Extractor de sesiones remotas (opcional, solo Mac)"
echo "  Lee la caché local de la app de Escritorio de Claude para sumar las"
echo "  sesiones de Cowork/Code que corrieron en la nube y que ccusage no ve."

if [[ $IS_MAC -eq 1 ]] && ask "Instalarlo en .venv-chatextract/?"; then
  python3 -m venv .venv-chatextract \
    && ./.venv-chatextract/bin/pip install --quiet --upgrade pip \
    && ./.venv-chatextract/bin/pip install --quiet -r requirements-remote.txt \
    && ok "Listo. Si falla la lectura, el dashboard lo ignora y sigue funcionando." \
    || warn "No se pudo instalar. El dashboard funciona igual, sin las sesiones remotas."
else
  warn "Salteado. Se puede correr este script otra vez más adelante."
fi

say "4. Tu configuración"

if [[ -f config.json ]]; then
  ok "config.json ya existe, no lo toco"
elif ask "Crear config.json a partir del ejemplo? (para agrupar y destacar proyectos)"; then
  cp config.example.json config.json && ok "config.json creado — editalo a gusto, es opcional"
fi

say "5. Launcher de un clic (opcional, solo Mac)"

if [[ $IS_MAC -eq 1 ]] && ask "Crear 'Straude Dashboard.app' en esta carpeta?"; then
  rm -rf "Straude Dashboard.app"
  if osacompile -o "Straude Dashboard.app" launcher.applescript 2>/dev/null; then
    ok "Creada. Arrastrala al Dock o al Escritorio."
    echo "     Si el server ya corre, abre la pestaña; si no, lo levanta en segundo plano."
    warn "El launcher espera el proyecto en \$HOME/straude-dashboard. Si lo tenés en otra ruta, editá launcher.applescript y volvé a correr este paso."
  else
    warn "osacompile falló. Usá ./start.sh en su lugar."
  fi
fi

say "Listo"
echo "  ./start.sh            dashboard en vivo con auto-refresh"
echo "  ./refresh.sh          snapshot estático de una vez"
echo
echo "  La primera carga tarda ~15-20s mientras ccusage escanea el disco."
