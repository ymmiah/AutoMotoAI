#!/usr/bin/env bash
# AutoMoto AI v5 - macOS / Linux setup
set -euo pipefail
python3 -m venv venv
. venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Done. Add at least one API key to .env, then run ./run.sh"
