#!/usr/bin/env bash

set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/gtk-shell"
BACKUP_DIR="${TARGET_DIR}.bak.$(date +%Y%m%d-%H%M%S)"

mkdir -p "$(dirname "$TARGET_DIR")"

if [[ -e "$TARGET_DIR" && ! -L "$TARGET_DIR" ]]; then
    mv "$TARGET_DIR" "$BACKUP_DIR"
    printf 'Backed up existing config to %s\n' "$BACKUP_DIR"
fi

rm -rf "$TARGET_DIR"
cp -R "$REPO_DIR/gtk-shell" "$TARGET_DIR"
chmod +x \
    "$TARGET_DIR/start.sh" \
    "$TARGET_DIR/scripts/popup-data.sh" \
    "$TARGET_DIR/scripts/spotify.sh" \
    "$TARGET_DIR/scripts/osd-write.sh" \
    "$TARGET_DIR/scripts/volume-osd.sh" \
    "$TARGET_DIR/scripts/brightness-osd.sh"

printf 'Installed gtk-shell to %s\n' "$TARGET_DIR"
printf 'Add this to Hyprland if needed:\n'
printf 'exec-once = ~/.config/gtk-shell/start.sh\n'
