#!/usr/bin/env bash

set -euo pipefail

cpu_json() {
    declare -A total_a=() idle_a=() total_b=() idle_b=() temps=()
    local id user nice system idle iowait irq softirq steal guest guest_nice

    while read -r id user nice system idle iowait irq softirq steal guest guest_nice; do
        total_a["$id"]=$((user + nice + system + idle + iowait + irq + softirq + steal))
        idle_a["$id"]=$((idle + iowait))
    done < <(grep '^cpu[0-9]\+' /proc/stat)

    sleep 0.12

    while read -r id user nice system idle iowait irq softirq steal guest guest_nice; do
        total_b["$id"]=$((user + nice + system + idle + iowait + irq + softirq + steal))
        idle_b["$id"]=$((idle + iowait))
    done < <(grep '^cpu[0-9]\+' /proc/stat)

    while read -r line; do
        core_id="$(awk -F'[: ]+' '{print $2}' <<<"$line")"
        temp_value="$(awk '{gsub(/[+°C]/, "", $3); print int($3)}' <<<"$line")"
        temps["cpu$core_id"]="$temp_value"
    done < <(sensors 2>/dev/null | grep '^Core ')

    printf '['
    first=1
    for id in $(printf '%s\n' "${!total_b[@]}" | sort -V); do
        total_diff=$((total_b["$id"] - total_a["$id"]))
        idle_diff=$((idle_b["$id"] - idle_a["$id"]))
        usage=0
        if ((total_diff > 0)); then
            usage=$(((100 * (total_diff - idle_diff)) / total_diff))
        fi
        temp="${temps[$id]:--}"
        [[ $first -eq 0 ]] && printf ','
        first=0
        jq -cn \
            --arg label "${id/cpu/c-}" \
            --argjson usage "$usage" \
            --arg temp "$temp" \
            '{label: $label, usage: $usage, temp: $temp}'
    done
    printf ']'
}

ram_json() {
    mem_total_kb="$(awk '/MemTotal:/ {print $2}' /proc/meminfo)"
    mem_available_kb="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)"
    mem_used_kb=$((mem_total_kb - mem_available_kb))
    mem_pct=$((100 * mem_used_kb / mem_total_kb))
    jq -cn \
        --arg used "$(free -h | awk '/Mem:/ {print $3}')" \
        --arg total "$(free -h | awk '/Mem:/ {print $2}')" \
        --arg free "$(free -h | awk '/Mem:/ {print $4}')" \
        --arg shared "$(free -h | awk '/Mem:/ {print $5}')" \
        --arg cache "$(free -h | awk '/Mem:/ {print $6}')" \
        --arg swap "$(free -h | awk '/Swap:/ {print $3 "/" $2}')" \
        --argjson pct "$mem_pct" \
        '{used: $used, total: $total, free: $free, shared: $shared, cache: $cache, swap: $swap, pct: $pct}'
}

gpu_json() {
    local line name util mem_used mem_total temp power_draw power_limit vram_pct
    line="$(nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit --format=csv,noheader,nounits 2>/dev/null | head -n 1)"
    if [[ -z "$line" ]]; then
        jq -cn '{available:false}'
        return
    fi

    IFS=',' read -r name util mem_used mem_total temp power_draw power_limit <<<"$line"
    name="${name## }"
    util="${util// /}"
    mem_used="${mem_used// /}"
    mem_total="${mem_total// /}"
    temp="${temp// /}"
    power_draw="${power_draw// /}"
    power_limit="${power_limit// /}"
    vram_pct=0
    if [[ -n "$mem_total" && "$mem_total" -gt 0 ]]; then
        vram_pct=$((100 * mem_used / mem_total))
    fi

    jq -cn \
        --arg name "$name" \
        --arg temp "$temp" \
        --arg vram "${mem_used}/${mem_total}M" \
        --arg power "${power_draw}/${power_limit} W" \
        --argjson available true \
        --argjson load "$util" \
        --argjson vram_pct "$vram_pct" \
        '{available:$available, name:$name, temp:$temp, vram:$vram, power:$power, load:$load, vram_pct:$vram_pct}'
}

disks_json() {
    local seen="|"
    local first=1
    printf '['
    while read -r filesystem size used available capacity mountpoint; do
        [[ "$filesystem" == "Filesystem" || -z "$mountpoint" ]] && continue
        case "$mountpoint" in
            /) label="/" ;;
            /home) label="/home" ;;
            /boot|/boot/efi) label="/boot" ;;
            *) label="$mountpoint" ;;
        esac
        if [[ "$seen" == *"|$label|"* ]]; then
            continue
        fi
        seen+="$label|"
        pct="${capacity%%%}"
        [[ $first -eq 0 ]] && printf ','
        first=0
        jq -cn --arg label "$label" --arg usage "${used}/${size}" --argjson pct "$pct" \
            '{label:$label, usage:$usage, pct:$pct}'
    done < <(df -hP / /home /boot /boot/efi 2>/dev/null)
    printf ']'
}

case "${1:-cpu}" in
    cpu) cpu_json ;;
    ram) ram_json ;;
    gpu) gpu_json ;;
    disks) disks_json ;;
esac
