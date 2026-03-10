# gtk-hypr-shell

A custom GTK4 + `gtk4-layer-shell` top bar for Hyprland with attached popovers for media, network, Bluetooth, VPN, power, calendar, and system stats.

## Features

- native GTK4 layer-shell bar for Hyprland
- attached GTK popovers instead of offset Rofi/Eww windows
- occupied-only workspace buttons
- inline media controls plus a richer media popover
- Wi-Fi, VPN, Bluetooth, battery/power, calendar, CPU, RAM, GPU, and disk popovers
- orange/brown rice with muted translucent cards

## Screenshots

![Bar](docs/screenshots/bar-clean.png)
![Media](docs/screenshots/media-popover.png)
![Network](docs/screenshots/network-popover.png)
![Calendar](docs/screenshots/calendar-popover.png)

## Dependencies

Runtime tools used by the shell:

- `python`
- `python-gobject`
- `gtk4`
- `gtk4-layer-shell`
- `hyprctl`
- `jq`
- `playerctl`
- `nmcli`
- `bluetoothctl`
- `powerprofilesctl`
- `lm_sensors`
- `nvidia-smi` for NVIDIA GPU data
- `kitty` and `nmtui` for fallback network/VPN management

## Install

Clone the repo and run:

```bash
./install.sh
```

Then add this to Hyprland:

```ini
exec-once = ~/.config/gtk-shell/start.sh
```

A ready-to-copy snippet is included in [examples/hyprland.conf.snippet](examples/hyprland.conf.snippet).

## Notes

- The GTK shell reads its helper scripts from the local `gtk-shell/scripts` directory.
- Spotify artwork is cached under `~/.cache/gtk-shell`.
- The VPN popover integrates with NetworkManager profiles and can optionally launch ProtonVPN if installed.

## Repository Layout

```text
gtk-shell/
  shell.py
  style.css
  start.sh
  scripts/
  assets/
examples/
docs/screenshots/
install.sh
```
