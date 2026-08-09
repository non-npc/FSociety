#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BIN_DIR=${XDG_BIN_HOME:-"$HOME/.local/bin"}
DATA_DIR=${XDG_DATA_HOME:-"$HOME/.local/share"}

mkdir -p -- "$BIN_DIR" "$DATA_DIR/applications" "$DATA_DIR/icons/hicolor/256x256/apps"
install -m 0755 "$SCRIPT_DIR/fsociety" "$BIN_DIR/fsociety"
install -m 0644 "$SCRIPT_DIR/fsociety.desktop" "$DATA_DIR/applications/fsociety.desktop"
install -m 0644 "$SCRIPT_DIR/fsociety.png" "$DATA_DIR/icons/hicolor/256x256/apps/fsociety.png"

echo "fsociety installed for the current user."
echo "Executable: $BIN_DIR/fsociety"
