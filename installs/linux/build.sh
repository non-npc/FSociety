#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CLIENT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
PLATFORM_ROOT="$CLIENT_ROOT/installs/linux"
PYTHON_BIN=${PYTHON_BIN:-python3}
export PYTHONPATH="$CLIENT_ROOT/src"

"$PYTHON_BIN" "$CLIENT_ROOT/scripts/check_source_secrets.py"

if ! "$PYTHON_BIN" -c 'import PyInstaller' >/dev/null 2>&1; then
    echo "ERROR: PyInstaller is not available in this Python environment." >&2
    echo "Install the packages listed in client/requirements.txt, then retry." >&2
    exit 1
fi

FSOCIETY_VERSION=$(
    "$PYTHON_BIN" -c 'import fsociety_client; print(fsociety_client.__version__)'
)
ARCH=$(uname -m)
PACKAGE_NAME="fsociety-open-beta-v${FSOCIETY_VERSION}-linux-${ARCH}"
PACKAGE_DIR="$PLATFORM_ROOT/dist/$PACKAGE_NAME"
ARCHIVE_PATH="$PLATFORM_ROOT/dist/${PACKAGE_NAME}.tar.gz"

echo "Building fsociety Open Beta v${FSOCIETY_VERSION} for Linux ${ARCH}..."
"$PYTHON_BIN" -m PyInstaller \
    --noconfirm \
    --clean \
    --onefile \
    --windowed \
    --name fsociety \
    --add-data "$CLIENT_ROOT/assets:assets" \
    --paths "$CLIENT_ROOT/src" \
    --collect-all nostr_sdk \
    --hidden-import PyQt6.QtMultimedia \
    --hidden-import PyQt6.QtMultimediaWidgets \
    --distpath "$PLATFORM_ROOT/pyinstaller-dist" \
    --workpath "$PLATFORM_ROOT/build" \
    --specpath "$PLATFORM_ROOT/build" \
    "$CLIENT_ROOT/main.py"

rm -rf -- "$PACKAGE_DIR"
mkdir -p -- "$PACKAGE_DIR"
install -m 0755 "$PLATFORM_ROOT/pyinstaller-dist/fsociety" "$PACKAGE_DIR/fsociety"
install -m 0755 "$PLATFORM_ROOT/install.sh" "$PACKAGE_DIR/install.sh"
install -m 0644 "$PLATFORM_ROOT/fsociety.desktop" "$PACKAGE_DIR/fsociety.desktop"
install -m 0644 "$CLIENT_ROOT/assets/fsociety.png" "$PACKAGE_DIR/fsociety.png"
install -m 0644 "$PLATFORM_ROOT/PACKAGE_README.txt" "$PACKAGE_DIR/README.txt"

(
    cd "$PACKAGE_DIR"
    sha256sum fsociety > SHA256SUMS.txt
)
rm -f -- "$ARCHIVE_PATH"
tar -C "$PLATFORM_ROOT/dist" -czf "$ARCHIVE_PATH" "$PACKAGE_NAME"

echo
echo "Build complete:"
echo "  $ARCHIVE_PATH"
