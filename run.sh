#!/usr/bin/env sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd -- "$SCRIPT_DIR" || exit 1

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN=python
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf '%s\n' "Python 3.12 or newer is required to run the uncompiled client."
    printf '%s\n' "Download information: https://www.python.org/downloads/"
    exit 1
fi

if "$PYTHON_BIN" main.py "$@"; then
    exit 0
else
    status=$?
    printf '\n%s\n' "fsociety failed to start. Install dependencies with:"
    printf '    %s\n' "$PYTHON_BIN -m pip install -r requirements.txt"
    exit "$status"
fi
