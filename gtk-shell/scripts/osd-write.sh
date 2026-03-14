#!/usr/bin/env bash

set -euo pipefail

kind="${1:?missing kind}"
value="${2:-0}"
muted="${3:-false}"

cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/gtk-shell"
event_file="$cache_dir/osd-event.json"
tmp_file="$event_file.tmp"

mkdir -p "$cache_dir"
printf '{"kind":"%s","value":%s,"muted":%s,"ts":%s}\n' \
    "$kind" "$value" "$muted" "$(date +%s%N)" > "$tmp_file"
mv "$tmp_file" "$event_file"
