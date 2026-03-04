#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ateamei"
URL_FILE="$CONFIG_DIR/standup_url.txt"

if [[ ! -f "$URL_FILE" ]]; then
  exit 0
fi

URL="$(head -n 1 "$URL_FILE" | tr -d '\r\n')"
if [[ -z "$URL" ]]; then
  exit 0
fi

open "$URL" >/dev/null 2>&1 || true

