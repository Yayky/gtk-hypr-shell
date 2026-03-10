#!/usr/bin/env bash

set -euo pipefail

cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/eww"
cache_art="$cache_dir/spotify-art"
placeholder="$HOME/.config/eww/icons/spotify.svg"
mkdir -p "$cache_dir"

format_time() {
    local seconds="$1"
    awk -v s="$seconds" 'BEGIN {
        if (s < 0) s = 0
        m = int(s / 60)
        sec = int(s % 60)
        printf "%d:%02d", m, sec
    }'
}

metadata() {
    playerctl metadata "$1" 2>/dev/null || true
}

position() {
    playerctl position 2>/dev/null || printf '0'
}

length_seconds() {
    local length_us
    length_us="$(metadata mpris:length)"
    if [[ -z "$length_us" ]]; then
        printf '0'
    else
        awk -v us="$length_us" 'BEGIN {printf "%.0f", us / 1000000}'
    fi
}

art_path() {
    local url target
    url="$(metadata mpris:artUrl)"
    if [[ -z "$url" ]]; then
        printf '%s\n' "$placeholder"
        return
    fi

    if [[ "$url" == file://* ]]; then
        printf '%s\n' "${url#file://}"
        return
    fi

    target="${cache_art}-$(printf '%s' "$url" | sha1sum | awk '{print $1}').img"
    if curl -fsSL "$url" -o "$target" >/dev/null 2>&1; then
        printf '%s\n' "$target"
        return
    fi

    printf '%s\n' "$placeholder"
}

case "${1:-status}" in
    status)
        playerctl status 2>/dev/null || echo "Stopped"
        ;;
    title)
        metadata title | sed 's/^$/Nothing playing/'
        ;;
    artist)
        metadata artist
        ;;
    album)
        metadata album
        ;;
    art-path)
        art_path
        ;;
    progress)
        pos="$(position)"
        len="$(length_seconds)"
        if [[ "$len" -le 0 ]]; then
            printf '0\n'
        else
            awk -v p="$pos" -v l="$len" 'BEGIN {
                value = int((p / l) * 100)
                if (value < 0) value = 0
                if (value > 100) value = 100
                printf "%d\n", value
            }'
        fi
        ;;
    elapsed)
        format_time "$(position)"
        ;;
    remaining)
        pos="$(position)"
        len="$(length_seconds)"
        awk -v p="$pos" -v l="$len" 'BEGIN {
            remaining = l - p
            if (remaining < 0) remaining = 0
            m = int(remaining / 60)
            sec = int(remaining % 60)
            printf "-%d:%02d", m, sec
        }'
        ;;
    prev)
        playerctl previous
        ;;
    toggle)
        playerctl play-pause
        ;;
    next)
        playerctl next
        ;;
esac
