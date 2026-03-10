#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}/usr/lib/libgtk4-layer-shell.so"
exec python3 "$SCRIPT_DIR/shell.py"
