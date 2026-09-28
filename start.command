#!/bin/bash
# Dubbelklik om de prijsvergelijker te starten.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Eerste keer: installeren..."
  python3 -m venv .venv && .venv/bin/pip install -q playwright || exit 1
fi
exec .venv/bin/python app.py
