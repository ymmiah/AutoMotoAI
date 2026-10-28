#!/usr/bin/env bash
# AutoMoto AI v4 - starts the local web UI (http://127.0.0.1:8765)
set -euo pipefail
cd "$(dirname "$0")"
[ -d venv ] || { echo "Run ./setup.sh first"; exit 1; }
. venv/bin/activate
exec python -m automoto serve "$@"
