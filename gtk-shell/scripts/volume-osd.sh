#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
sink="@DEFAULT_AUDIO_SINK@"
action="${1:-}"

case "$action" in
    up)
        wpctl set-mute "$sink" 0
        wpctl set-volume "$sink" 5%+
        ;;
    down)
        wpctl set-mute "$sink" 0
        wpctl set-volume "$sink" 5%-
        ;;
    mute)
        wpctl set-mute "$sink" toggle
        ;;
    *)
        printf 'usage: %s <up|down|mute>\n' "${0##*/}" >&2
        exit 1
        ;;
esac

state="$(wpctl get-volume "$sink" 2>/dev/null || true)"
value="$(awk '/Volume:/ {printf("%d", (($2 + 0) * 100) + 0.5)}' <<<"$state")"
muted=false
if [[ "$state" == *"[MUTED]"* ]]; then
    muted=true
fi

if [[ -z "$value" ]]; then
    value=0
fi

"$script_dir/osd-write.sh" volume "$value" "$muted"
