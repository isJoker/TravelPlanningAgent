#!/usr/bin/env bash
# Start the frontend dev server.
set -e
cd "$(dirname "$0")/../ui"
[ -d node_modules ] || npm install
exec npm run dev -- --host
