#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/release/Buzz.app"
BIN="$APP/Contents/MacOS"
mkdir -p "$BIN" "$APP/Contents"
cp "$ROOT/macos/Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
swiftc "$ROOT/macos/Buzz.swift" \
  -o "$BIN/Buzz" \
  -framework AppKit \
  -framework WebKit
DEST="/Applications/Buzz.app"
rm -rf "$DEST"
cp -R "$APP" "$DEST"
echo "Installed $DEST"
open "$DEST"
