#!/usr/bin/env bash
# Start the backend dev server.
set -e
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
export PYTHONPATH=.
exec python -m uvicorn api.server:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}" --reload
