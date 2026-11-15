#!/bin/bash
# Levanta el dashboard en vivo: http://localhost:8934
# Corre en foreground -- dejá la terminal abierta, o lanzalo con nohup/& si
# preferís que siga corriendo en segundo plano.
set -e
cd "$(dirname "$0")"
export DO_NOT_TRACK=1
python3 server.py
