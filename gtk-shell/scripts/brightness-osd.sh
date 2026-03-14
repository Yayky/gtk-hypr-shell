#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
action="${1:-}"

case "$action" in
    up)
        brightnessctl s +5% >/dev/null
        ;;
    down)
        brightnessctl s 5%- >/dev/null
        ;;
    *)
        printf 'usage: %s <up|down>\n' "${0##*/}" >&2
        exit 1
        ;;
esac

value="$(brightnessctl -m 2>/dev/null | awk -F, '{gsub(/%/, "", $4); print int($4 + 0)}')"
if [[ -z "$value" ]]; then
    value=0
fi

"$script_dir/osd-write.sh" brightness "$value" false
