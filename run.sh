#!/usr/bin/env bash
set -euo pipefail

editor_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
editor_port="${1:-8778}"
editor_url="http://127.0.0.1:${editor_port}/"

if [[ ! -f "$editor_dir/config.local.json" ]]; then
  printf 'Missing config.local.json. Copy config.example.json to config.local.json and set your local paths.\n' >&2
  exit 1
fi

if curl --silent --fail --max-time 1 "${editor_url}api/status" | grep -q '"dialogue"'; then
  printf 'Editor already running: %s\n' "$editor_url"
  exit 0
fi

printf 'Open %s in your browser. Press Ctrl+C here to stop the editor.\n' "$editor_url"
exec python3 "$editor_dir/app.py" --config "$editor_dir/config.local.json" --port "$editor_port"
