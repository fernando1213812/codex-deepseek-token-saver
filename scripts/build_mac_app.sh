#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_NAME="Reasonix Room Console"
BUILD_ROOT="$ROOT/work/mac-app"
DIST_DIR="$BUILD_ROOT/dist"
BUILD_DIR="$BUILD_ROOT/build"
SPEC_DIR="$BUILD_ROOT/spec"
ICON_DIR="$BUILD_ROOT/icon"
ICON_PNG="$ICON_DIR/room-console.png"
ICON_ICNS="$ICON_DIR/room-console.icns"

mkdir -p "$BUILD_ROOT" "$DIST_DIR" "$BUILD_DIR" "$ICON_DIR" "$SPEC_DIR"
rm -rf "$DIST_DIR/$APP_NAME.app" "$BUILD_DIR" "$SPEC_DIR"/*.spec

python3 scripts/generate_room_console_icon.py \
  --png "$ICON_PNG" \
  --icns "$ICON_ICNS"

pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --icon "$ICON_ICNS" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR" \
  --specpath "$SPEC_DIR" \
  --collect-all webview \
  --hidden-import bottle \
  --hidden-import tkinter \
  --hidden-import tkinter.filedialog \
  --hidden-import tkinter.messagebox \
  --exclude-module numpy \
  --exclude-module pytest \
  --add-data "$ROOT/dashboard:dashboard" \
  --add-data "$ROOT/assets:assets" \
  --add-data "$ROOT/skills/deepseek-token-saver/scripts:skills/deepseek-token-saver/scripts" \
  deepseek_room_desktop.py

echo "$DIST_DIR/$APP_NAME.app"
