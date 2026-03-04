#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT_DIR/native/sck_capture/main.swift"
OUT_DIR="$ROOT_DIR/bin"
OUT="$OUT_DIR/ateamei-sck-capture"

mkdir -p "$OUT_DIR"

ARCH="$(uname -m)"
MIN_VER="13.0"

echo "Building ateamei-sck-capture -> $OUT"
swiftc \
  -O \
  -parse-as-library \
  -target "${ARCH}-apple-macosx${MIN_VER}" \
  "$SRC" \
  -o "$OUT"

echo "Done."
