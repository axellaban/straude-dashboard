#!/bin/bash
# Genera y abre un dashboard con datos inventados. No necesita ccusage, ni
# Node, ni tener historial de uso: sirve para ver cómo se ve antes de instalar.
set -e
cd "$(dirname "$0")"
python3 demo/make_demo.py
if command -v open >/dev/null 2>&1; then open demo/dashboard-demo.html
elif command -v xdg-open >/dev/null 2>&1; then xdg-open demo/dashboard-demo.html
else echo "Abrí demo/dashboard-demo.html en tu navegador."; fi
