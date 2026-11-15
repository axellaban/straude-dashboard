#!/bin/bash
# Modo snapshot (sin servidor): regenera dashboard.html una vez con los datos
# de ahora y lo abre. Para que se actualice solo mientras lo mirás, usá
# start.sh en cambio (levanta el servidor local con auto-refresh).
set -e
cd "$(dirname "$0")"
export DO_NOT_TRACK=1
python3 extract_data.py
python3 build_dashboard.py
open dashboard.html
