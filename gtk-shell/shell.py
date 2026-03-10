#!/usr/bin/env python3

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import hashlib
import urllib.request
from typing import Any

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Gtk4LayerShell, Pango  # noqa: E402


CONFIG_DIR = pathlib.Path(__file__).resolve().parent
STYLE_PATH = CONFIG_DIR / "style.css"
POPUP_DATA_SCRIPT = CONFIG_DIR / "scripts" / "popup-data.sh"
SPOTIFY_SCRIPT = CONFIG_DIR / "scripts" / "spotify.sh"
SPOTIFY_PLACEHOLDER = CONFIG_DIR / "assets" / "spotify.svg"
ART_CACHE_DIR = pathlib.Path.home() / ".cache" / "gtk-shell"


def run(args: list[str], timeout: float = 4.0) -> str:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def run_ok(args: list[str], timeout: float = 8.0) -> bool:
    try:
        result = subprocess.run(args, check=False, timeout=timeout)
    except Exception:
        return False
    return result.returncode == 0


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def dispatch_exec(command: str) -> bool:
    return run_ok(["hyprctl", "dispatch", "exec", command], timeout=2.0)


def run_json(args: list[str], timeout: float = 4.0, fallback: Any = None) -> Any:
    text = run(args, timeout=timeout)
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def truncate(text: str, length: int) -> str:
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[: max(0, length - 1)] + "…"


def load_stats(kind: str) -> Any:
    if kind == "cpu":
        return load_cpu_rows()
    return run_json([str(POPUP_DATA_SCRIPT), kind], fallback=[] if kind in {"cpu", "disks"} else {})


def read_proc_cpu_snapshot() -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    try:
        with pathlib.Path("/proc/stat").open() as handle:
            for line in handle:
                if not line.startswith("cpu") or line.startswith("cpu "):
                    continue
                parts = line.split()
                if len(parts) < 6:
                    continue
                values = [int(value) for value in parts[1:9]]
                total = sum(values)
                idle = values[3] + (values[4] if len(values) > 4 else 0)
                snapshot[parts[0]] = (total, idle)
    except Exception:
        return {}
    return snapshot


def read_cpu_temps() -> dict[str, str]:
    if not command_exists("sensors"):
        return {}
    temps: dict[str, str] = {}
    output = run(["sensors"], timeout=1.0)
    for line in output.splitlines():
        match = re.match(r"Core\s+(\d+):\s+\+?([0-9]+(?:\.[0-9]+)?)°C", line.strip())
        if not match:
            continue
        temps[f"cpu{match.group(1)}"] = str(int(float(match.group(2))))
    return temps


def load_cpu_rows() -> list[dict[str, Any]]:
    first = read_proc_cpu_snapshot()
    if not first:
        return []
    time.sleep(0.12)
    second = read_proc_cpu_snapshot()
    if not second:
        return []
    temps = read_cpu_temps()
    rows: list[dict[str, Any]] = []
    for cpu_id in sorted(second.keys(), key=lambda value: int(value.removeprefix("cpu"))):
        first_total, first_idle = first.get(cpu_id, second[cpu_id])
        second_total, second_idle = second[cpu_id]
        total_diff = second_total - first_total
        idle_diff = second_idle - first_idle
        usage = 0
        if total_diff > 0:
            usage = max(0, min(100, int((100 * (total_diff - idle_diff)) / total_diff)))
        rows.append(
            {
                "label": cpu_id.replace("cpu", "c"),
                "usage": usage,
                "temp": temps.get(cpu_id, "-"),
            }
        )
    return rows


def playerctl(args: list[str]) -> str:
    return run(["playerctl", *args], timeout=1.2)


def battery_info() -> dict[str, str]:
    batteries = list(pathlib.Path("/sys/class/power_supply").glob("BAT*"))
    if not batteries:
        return {"capacity": "--", "status": "Unknown"}
    battery = batteries[0]
    try:
        capacity = (battery / "capacity").read_text().strip()
    except Exception:
        capacity = "--"
    try:
        status = (battery / "status").read_text().strip()
    except Exception:
        status = "Unknown"
    return {"capacity": capacity, "status": status}


def find_spotify_client() -> dict[str, Any] | None:
    clients = run_json(["hyprctl", "-j", "clients"], fallback=[]) or []
    for client in clients:
        klass = (client.get("class") or client.get("initialClass") or "").lower()
        title = (client.get("title") or client.get("initialTitle") or "").lower()
        if "spotify" in klass or "spotify" in title:
            return client
    return None


def cache_art_from_url(url: str) -> str:
    if not url:
        return str(SPOTIFY_PLACEHOLDER) if SPOTIFY_PLACEHOLDER.exists() else ""
    if url.startswith("file://"):
        return url.removeprefix("file://")
    ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = ART_CACHE_DIR / f"art-{hashlib.sha1(url.encode('utf-8')).hexdigest()}.img"
    if target.exists() and target.stat().st_size > 0:
        return str(target)
    try:
        with urllib.request.urlopen(url, timeout=4) as response, target.open("wb") as handle:
            handle.write(response.read())
    except Exception:
        return str(SPOTIFY_PLACEHOLDER) if SPOTIFY_PLACEHOLDER.exists() else ""
    return str(target)


class MinimalBarWindow(Gtk.Window):
    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app)
        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("shell-bar")

        Gtk4LayerShell.init_for_window(self)
        Gtk4LayerShell.set_namespace(self, "gtk-shell-bar")
        Gtk4LayerShell.set_layer(self, Gtk4LayerShell.Layer.TOP)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.TOP, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.LEFT, True)
        Gtk4LayerShell.set_anchor(self, Gtk4LayerShell.Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.TOP, 8)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.LEFT, 14)
        Gtk4LayerShell.set_margin(self, Gtk4LayerShell.Edge.RIGHT, 14)
        Gtk4LayerShell.set_exclusive_zone(self, 46)
        self.set_default_size(self.bar_width_hint(), 48)
        self.current_wifi_device = ""
        self.bluetooth_scanning = False
        self.has_spotify = command_exists("spotify")
        self.has_spotify_launcher = command_exists("spotify-launcher")
        self._ui_poll_inflight = False
        self._media_poll_inflight = False
        self._slow_poll_inflight = False
        self._workspace_signature: tuple[int, tuple[int, ...]] | None = None
        self._last_title = ""
        self._last_media_key = ""
        self._last_media_art_path = str(SPOTIFY_PLACEHOLDER) if SPOTIFY_PLACEHOLDER.exists() else ""
        self._last_media_art_url = ""

        self.build_ui()
        self.load_css()
        self.refresh_all()
        self.schedule_updates()
        self.debug_target = os.environ.get("GTK_SHELL_DEBUG_POPOVER", "").strip()
        if self.debug_target:
            GLib.timeout_add(1500, self.open_debug_popover)

    def load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_path(str(STYLE_PATH))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def bar_width_hint(self) -> int:
        monitors = run_json(["hyprctl", "-j", "monitors"], fallback=[]) or []
        if monitors:
            width = int(monitors[0].get("width", 1920))
            return max(width - 28, 400)
        return 1892

    def build_ui(self) -> None:
        surface = Gtk.CenterBox()
        surface.add_css_class("bar-surface")
        surface.set_size_request(-1, 36)
        surface.set_hexpand(True)
        surface.set_halign(Gtk.Align.FILL)

        self.left_cluster = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.left_cluster.set_valign(Gtk.Align.CENTER)
        self.workspaces_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.left_cluster.append(self.workspaces_box)

        self.center_cluster = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.center_cluster.set_valign(Gtk.Align.CENTER)
        self.media_cluster = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.media_cluster.add_css_class("compound-bubble")
        self.media_cluster.add_css_class("media-cluster")
        self.media_button, self.media_bubble, self.media_label, media_shell = self.make_menu_bubble("󰎆  Nothing playing")
        self.media_bubble.add_css_class("media-bubble")
        self.media_button.add_css_class("compound-menu-button")
        self.build_media_popover(media_shell)
        self.media_cluster.append(self.media_button)
        self.media_cluster.append(self.make_compound_separator())
        self.media_prev = self.make_inline_icon_button("󰒮", lambda _btn: run_ok([str(SPOTIFY_SCRIPT), "prev"]))
        self.media_toggle = self.make_inline_icon_button("󰐊", lambda _btn: self.toggle_media())
        self.media_next = self.make_inline_icon_button("󰒭", lambda _btn: run_ok([str(SPOTIFY_SCRIPT), "next"]))
        self.media_cluster.append(self.media_prev)
        self.media_cluster.append(self.media_toggle)
        self.media_cluster.append(self.media_next)
        self.left_cluster.append(self.media_cluster)
        self.title_bubble, self.title_label = self.make_bubble_label("󰇄  desktop")
        self.title_bubble.add_css_class("title-bubble")
        self.center_cluster.append(self.title_bubble)

        self.right_cluster = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.right_cluster.set_valign(Gtk.Align.CENTER)
        self.network_button, self.network_bubble, self.network_label, network_shell = self.make_menu_bubble("󰤮  offline")
        self.build_network_popover(network_shell)
        self.vpn_button, self.vpn_bubble, self.vpn_label, vpn_shell = self.make_menu_bubble("󰦝  vpn")
        self.build_vpn_popover(vpn_shell)
        self.bluetooth_button, self.bluetooth_bubble, self.bluetooth_label, bluetooth_shell = self.make_menu_bubble(
            "󰂲  off"
        )
        self.build_bluetooth_popover(bluetooth_shell)
        self.cpu_button, self.cpu_bubble, self.cpu_label, cpu_shell = self.make_menu_bubble("  0%")
        self.build_cpu_popover(cpu_shell)
        self.ram_button, self.ram_bubble, self.ram_label, ram_shell = self.make_menu_bubble("  0%")
        self.build_ram_popover(ram_shell)
        self.gpu_button, self.gpu_bubble, self.gpu_label, gpu_shell = self.make_menu_bubble("󰢮")
        self.build_gpu_popover(gpu_shell)
        self.disk_button, self.disk_bubble, self.disk_label, disk_shell = self.make_menu_bubble("󰋊  --%")
        self.build_disk_popover(disk_shell)
        self.battery_button, self.battery_bubble, self.battery_label, power_shell = self.make_menu_bubble("󰁹  --%")
        self.build_power_popover(power_shell)
        self.date_button, self.date_bubble, self.date_label, calendar_shell = self.make_menu_bubble("󰃭  -- ---")
        self.build_calendar_popover(calendar_shell)
        self.time_bubble, self.time_label = self.make_bubble_label("󰥔  --:--")
        self.attach_stats_refresh(self.cpu_button)
        self.attach_stats_refresh(self.ram_button)
        self.attach_stats_refresh(self.gpu_button)
        self.attach_stats_refresh(self.disk_button)
        for bubble in (
            self.network_button,
            self.vpn_button,
            self.bluetooth_button,
            self.cpu_button,
            self.ram_button,
            self.gpu_button,
            self.disk_button,
            self.battery_button,
            self.date_button,
            self.time_bubble,
        ):
            self.right_cluster.append(bubble)
        surface.set_start_widget(self.left_cluster)
        surface.set_center_widget(self.center_cluster)
        surface.set_end_widget(self.right_cluster)

        self.set_child(surface)

    def attach_stats_refresh(self, menu: Gtk.MenuButton) -> None:
        popover = menu.get_popover()
        if popover is None:
            return
        popover.connect("notify::visible", self.on_stats_popover_visible)

    def on_stats_popover_visible(self, popover: Gtk.Popover, _pspec) -> None:
        if popover.get_visible():
            self.queue_slow_refresh()

    def make_bubble_label(self, text: str) -> tuple[Gtk.Box, Gtk.Label]:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.add_css_class("bubble-box")
        label = Gtk.Label(label=text)
        label.add_css_class("bubble-label")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_xalign(0.5)
        box.append(label)
        return box, label

    def make_menu_bubble(self, text: str) -> tuple[Gtk.MenuButton, Gtk.Box, Gtk.Label, Gtk.Box]:
        menu = Gtk.MenuButton()
        menu.add_css_class("bubble-menu")
        menu.set_direction(Gtk.ArrowType.DOWN)
        menu.set_always_show_arrow(False)
        menu.set_can_shrink(True)
        bubble_box, label = self.make_bubble_label(text)
        menu.set_child(bubble_box)

        popover = Gtk.Popover()
        popover.set_has_arrow(False)
        popover.set_position(Gtk.PositionType.BOTTOM)
        popover.set_autohide(True)
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        shell.add_css_class("popover-shell")
        popover.set_child(shell)
        menu.set_popover(popover)
        return menu, bubble_box, label, shell

    def make_icon_button(self, text: str, callback) -> Gtk.Button:
        button = Gtk.Button(label=text)
        button.add_css_class("bubble-button")
        button.add_css_class("icon-button")
        button.connect("clicked", callback)
        return button

    def make_inline_icon_button(self, text: str, callback) -> Gtk.Button:
        button = Gtk.Button(label=text)
        button.add_css_class("compound-icon-button")
        button.add_css_class("icon-button")
        button.set_has_frame(False)
        button.connect("clicked", callback)
        return button

    def make_compound_separator(self) -> Gtk.Box:
        separator = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        separator.add_css_class("compound-separator")
        return separator

    def make_popover_card(self, title: str, width: int = 260) -> Gtk.Box:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("popover-card")
        card.set_size_request(width, -1)
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("popover-title")
        title_label.set_xalign(0)
        card.append(title_label)
        return card

    def make_popover_text(self) -> Gtk.Label:
        label = Gtk.Label()
        label.add_css_class("popover-text")
        label.set_xalign(0)
        label.set_yalign(0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        return label

    def make_popover_button(self, text: str, callback, accent: bool = False) -> Gtk.Button:
        button = Gtk.Button(label=text)
        button.add_css_class("popover-button")
        if accent:
            button.add_css_class("popover-button-accent")
        button.connect("clicked", callback)
        return button

    def make_actions_row(self) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class("popover-actions-row")
        return row

    def make_separator(self) -> Gtk.Separator:
        separator = Gtk.Separator.new(Gtk.Orientation.HORIZONTAL)
        separator.add_css_class("popover-separator")
        return separator

    def make_list_row_button(
        self,
        title: str,
        subtitle: str,
        suffix: str,
        callback,
        *,
        accent: bool = False,
    ) -> Gtk.Button:
        button = Gtk.Button()
        button.add_css_class("list-row-button")
        if accent:
            button.add_css_class("list-row-button-accent")
        button.connect("clicked", callback)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("list-row-title")
        title_label.set_xalign(0)
        subtitle_label = Gtk.Label(label=subtitle)
        subtitle_label.add_css_class("list-row-subtitle")
        subtitle_label.set_xalign(0)
        subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        column.append(title_label)
        if subtitle:
            column.append(subtitle_label)
        row.append(column)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        row.append(spacer)

        if suffix:
            suffix_label = Gtk.Label(label=suffix)
            suffix_label.add_css_class("list-row-suffix")
            suffix_label.set_xalign(1)
            row.append(suffix_label)

        button.set_child(row)
        return button

    def clear_box(self, box: Gtk.Box) -> None:
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def build_media_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("Now Playing", width=320)
        card.add_css_class("media-popover-card")
        shell.append(card)

        self.media_status_label = Gtk.Label(label="Spotify")
        self.media_status_label.add_css_class("media-status-chip")
        self.media_status_label.set_xalign(0)
        card.append(self.media_status_label)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class("media-top-row")
        cover_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cover_slot.add_css_class("media-cover-slot")
        cover_slot.set_size_request(82, 82)
        cover_slot.set_halign(Gtk.Align.START)
        cover_slot.set_valign(Gtk.Align.START)
        self.media_cover = Gtk.Picture()
        self.media_cover.add_css_class("media-cover")
        self.media_cover.set_can_shrink(True)
        self.media_cover.set_content_fit(Gtk.ContentFit.COVER)
        self.media_cover.set_size_request(82, 82)
        self.media_cover.set_halign(Gtk.Align.FILL)
        self.media_cover.set_valign(Gtk.Align.FILL)
        self.media_cover.set_overflow(Gtk.Overflow.HIDDEN)
        cover_slot.append(self.media_cover)
        row.append(cover_slot)

        meta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        meta.add_css_class("media-meta")
        meta.set_hexpand(True)
        meta.set_valign(Gtk.Align.CENTER)
        self.media_pop_title = self.make_popover_text()
        self.media_pop_title.add_css_class("popover-title-large")
        self.media_pop_title.set_wrap(False)
        self.media_pop_title.set_ellipsize(Pango.EllipsizeMode.END)
        self.media_pop_artist = self.make_popover_text()
        self.media_pop_artist.add_css_class("popover-subtitle")
        self.media_pop_artist.set_wrap(False)
        self.media_pop_artist.set_ellipsize(Pango.EllipsizeMode.END)
        self.media_pop_album = self.make_popover_text()
        self.media_pop_album.add_css_class("popover-subtitle")
        self.media_pop_album.set_wrap(False)
        self.media_pop_album.set_ellipsize(Pango.EllipsizeMode.END)
        meta.append(self.media_pop_title)
        meta.append(self.media_pop_artist)
        meta.append(self.media_pop_album)
        row.append(meta)
        card.append(row)

        card.append(self.make_separator())

        self.media_progress = Gtk.ProgressBar()
        self.media_progress.add_css_class("media-progress")
        card.append(self.media_progress)

        times = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        times.add_css_class("media-times-row")
        self.media_elapsed = self.make_popover_text()
        self.media_elapsed.add_css_class("popover-subtitle")
        self.media_remaining = self.make_popover_text()
        self.media_remaining.add_css_class("popover-subtitle")
        remaining_spacer = Gtk.Box()
        remaining_spacer.set_hexpand(True)
        times.append(self.media_elapsed)
        times.append(remaining_spacer)
        times.append(self.media_remaining)
        card.append(times)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.add_css_class("media-controls-row")
        prev_button = self.make_popover_button("󰒮", lambda _btn: run_ok([str(SPOTIFY_SCRIPT), "prev"]))
        prev_button.add_css_class("media-control-button")
        play_button = self.make_popover_button("󰐊", lambda _btn: self.toggle_media(), accent=True)
        play_button.add_css_class("media-control-button")
        next_button = self.make_popover_button("󰒭", lambda _btn: run_ok([str(SPOTIFY_SCRIPT), "next"]))
        next_button.add_css_class("media-control-button")
        controls.append(prev_button)
        controls.append(play_button)
        controls.append(next_button)
        self.media_open_button = self.make_popover_button("Open Spotify", lambda _btn: self.launch_spotify())
        self.media_open_button.add_css_class("media-open-button")
        controls.append(self.media_open_button)
        card.append(controls)

    def build_network_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("Network", width=252)
        card.add_css_class("list-popover-card")
        shell.append(card)
        self.network_detail = self.make_popover_text()
        self.network_detail.add_css_class("popover-detail")
        card.append(self.network_detail)
        self.network_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.append(self.network_rows)
        actions = self.make_actions_row()
        actions.append(self.make_popover_button("Refresh", lambda _btn: self.rescan_wifi(), accent=True))
        actions.append(self.make_popover_button("nmtui", lambda _btn: dispatch_exec("kitty -e nmtui")))
        card.append(actions)

    def build_vpn_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("VPN", width=246)
        card.add_css_class("list-popover-card")
        shell.append(card)
        self.vpn_detail = self.make_popover_text()
        self.vpn_detail.add_css_class("popover-detail")
        card.append(self.vpn_detail)
        self.vpn_profiles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.append(self.vpn_profiles_box)
        actions = self.make_actions_row()
        actions.append(self.make_popover_button("nmtui", lambda _btn: dispatch_exec("kitty -e nmtui")))
        self.vpn_external_button = None
        if command_exists("protonvpn-app"):
            self.vpn_external_button = self.make_popover_button("Proton", lambda _btn: dispatch_exec("protonvpn-app"))
            actions.append(self.vpn_external_button)
        elif command_exists("protonvpn"):
            self.vpn_external_button = self.make_popover_button("Proton", lambda _btn: dispatch_exec("protonvpn"))
            actions.append(self.vpn_external_button)
        card.append(actions)

    def build_bluetooth_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("Bluetooth", width=268)
        card.add_css_class("list-popover-card")
        shell.append(card)
        self.bluetooth_detail = self.make_popover_text()
        self.bluetooth_detail.add_css_class("popover-detail")
        card.append(self.bluetooth_detail)
        self.bluetooth_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.append(self.bluetooth_rows)
        actions = self.make_actions_row()
        self.bluetooth_power_button = self.make_popover_button("Toggle", lambda _btn: self.toggle_bluetooth(), accent=True)
        actions.append(self.bluetooth_power_button)
        self.bluetooth_scan_button = self.make_popover_button("Scan", lambda _btn: self.start_bluetooth_scan())
        actions.append(self.bluetooth_scan_button)
        actions.append(self.make_popover_button("Refresh", lambda _btn: self.refresh_bluetooth()))
        card.append(actions)

    def build_cpu_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("CPU Details", width=272)
        card.add_css_class("stats-popover-card")
        shell.append(card)
        self.cpu_detail = self.make_popover_text()
        self.cpu_detail.add_css_class("stats-text")
        self.cpu_detail.set_wrap(False)
        self.cpu_detail.set_text("Loading…")
        card.append(self.cpu_detail)

    def build_ram_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("Memory", width=238)
        card.add_css_class("stats-popover-card")
        shell.append(card)
        self.ram_detail = self.make_popover_text()
        self.ram_detail.add_css_class("stats-text")
        self.ram_detail.set_wrap(False)
        self.ram_detail.set_text("Loading…")
        card.append(self.ram_detail)

    def build_gpu_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("GPU Details", width=256)
        card.add_css_class("stats-popover-card")
        shell.append(card)
        self.gpu_detail = self.make_popover_text()
        self.gpu_detail.add_css_class("stats-text")
        self.gpu_detail.set_wrap(False)
        self.gpu_detail.set_text("Loading…")
        card.append(self.gpu_detail)

    def build_disk_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("Disks", width=252)
        card.add_css_class("stats-popover-card")
        shell.append(card)
        self.disk_detail = self.make_popover_text()
        self.disk_detail.add_css_class("stats-text")
        self.disk_detail.set_wrap(False)
        self.disk_detail.set_text("Loading…")
        card.append(self.disk_detail)

    def build_power_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("Power Profile", width=226)
        card.add_css_class("list-popover-card")
        shell.append(card)
        self.power_detail = self.make_popover_text()
        self.power_detail.add_css_class("popover-detail")
        card.append(self.power_detail)
        self.power_buttons_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.append(self.power_buttons_box)

    def build_calendar_popover(self, shell: Gtk.Box) -> None:
        card = self.make_popover_card("Calendar", width=272)
        card.add_css_class("calendar-popover-card")
        shell.append(card)
        self.calendar_summary = Gtk.Label(label="")
        self.calendar_summary.add_css_class("calendar-summary")
        self.calendar_summary.set_xalign(0)
        card.append(self.calendar_summary)
        card.append(self.make_separator())
        calendar_frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        calendar_frame.add_css_class("calendar-frame")
        self.calendar = Gtk.Calendar.new()
        self.calendar.add_css_class("calendar-view")
        self.calendar.set_show_week_numbers(False)
        self.calendar.set_show_day_names(True)
        self.calendar.set_show_heading(True)
        calendar_frame.append(self.calendar)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        footer.add_css_class("calendar-footer")
        today_button = self.make_popover_button("Today", lambda _btn: self.jump_calendar_today(), accent=True)
        today_button.add_css_class("calendar-today-button")
        footer.append(today_button)
        calendar_frame.append(footer)
        card.append(calendar_frame)

    def make_workspace_button(self, workspace_id: int, active: bool) -> Gtk.Button:
        button = Gtk.Button(label=str(workspace_id))
        button.add_css_class("workspace-button")
        if active:
            button.add_css_class("workspace-active")
        button.connect("clicked", lambda _btn: run_ok(["hyprctl", "dispatch", "workspace", str(workspace_id)]))
        return button

    def schedule_updates(self) -> None:
        GLib.timeout_add(180, self.tick_fast)
        GLib.timeout_add_seconds(1, self.tick_clock)
        GLib.timeout_add(1800, self.tick_media)
        GLib.timeout_add(3200, self.tick_slow)

    def tick_fast(self) -> bool:
        self.queue_ui_refresh()
        return True

    def tick_clock(self) -> bool:
        self.refresh_clock()
        return True

    def tick_media(self) -> bool:
        self.queue_media_refresh()
        return True

    def tick_slow(self) -> bool:
        self.queue_slow_refresh()
        return True

    def refresh_all(self) -> None:
        self.queue_ui_refresh()
        self.refresh_clock()
        self.queue_media_refresh()
        self.queue_slow_refresh()

    def queue_ui_refresh(self) -> None:
        if self._ui_poll_inflight:
            return
        self._ui_poll_inflight = True
        threading.Thread(target=self._ui_worker, daemon=True).start()

    def _ui_worker(self) -> None:
        try:
            state = self.collect_ui_state()
        except Exception:
            state = {}
        GLib.idle_add(self.apply_ui_state, state)

    def queue_media_refresh(self) -> None:
        if self._media_poll_inflight:
            return
        self._media_poll_inflight = True
        threading.Thread(target=self._media_worker, daemon=True).start()

    def _media_worker(self) -> None:
        try:
            state = self.collect_media_state()
        except Exception:
            state = {}
        GLib.idle_add(self.apply_media_state, state)

    def queue_slow_refresh(self) -> None:
        if self._slow_poll_inflight:
            return
        self._slow_poll_inflight = True
        threading.Thread(target=self._slow_worker, daemon=True).start()

    def _slow_worker(self) -> None:
        try:
            state = self.collect_slow_state()
        except Exception:
            state = {}
        GLib.idle_add(self.apply_slow_state, state)

    def refresh_workspaces(self) -> None:
        workspaces = run_json(["hyprctl", "-j", "workspaces"], fallback=[]) or []
        active_workspace = run_json(["hyprctl", "-j", "activeworkspace"], fallback={}) or {}
        active_id = int(active_workspace.get("id", 1))
        visible = {active_id}
        for workspace in workspaces:
            wid = int(workspace.get("id", 0))
            if 1 <= wid <= 9 and int(workspace.get("windows", 0)) > 0:
                visible.add(wid)
        signature = (active_id, tuple(sorted(visible)))
        if signature == self._workspace_signature:
            return
        self._workspace_signature = signature

        child = self.workspaces_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.workspaces_box.remove(child)
            child = nxt

        for wid in sorted(visible):
            self.workspaces_box.append(self.make_workspace_button(wid, wid == active_id))

    def refresh_title(self) -> None:
        active = run_json(["hyprctl", "activewindow", "-j"], fallback={}) or {}
        title = active.get("title") or active.get("class") or "desktop"
        text = f"󰇄  {truncate(title, 34)}"
        if text == self._last_title:
            return
        self._last_title = text
        self.title_label.set_text(text)

    def collect_ui_state(self) -> dict[str, Any]:
        workspaces = run_json(["hyprctl", "-j", "workspaces"], fallback=[]) or []
        active_workspace = run_json(["hyprctl", "-j", "activeworkspace"], fallback={}) or {}
        active_window = run_json(["hyprctl", "activewindow", "-j"], fallback={}) or {}
        active_id = int(active_workspace.get("id", 1))
        visible = {active_id}
        for workspace in workspaces:
            wid = int(workspace.get("id", 0))
            if 1 <= wid <= 9 and int(workspace.get("windows", 0)) > 0:
                visible.add(wid)
        title = active_window.get("title") or active_window.get("class") or "desktop"
        return {
            "active_id": active_id,
            "visible": tuple(sorted(visible)),
            "title": f"󰇄  {truncate(title, 34)}",
        }

    def apply_ui_state(self, state: dict[str, Any]) -> bool:
        active_id = int(state.get("active_id", 1))
        visible = tuple(state.get("visible", (active_id,)))
        signature = (active_id, visible)
        if signature != self._workspace_signature:
            self._workspace_signature = signature
            child = self.workspaces_box.get_first_child()
            while child is not None:
                nxt = child.get_next_sibling()
                self.workspaces_box.remove(child)
                child = nxt
            for wid in visible:
                self.workspaces_box.append(self.make_workspace_button(wid, wid == active_id))
        title_text = state.get("title", "󰇄  desktop")
        if title_text != self._last_title:
            self._last_title = title_text
            self.title_label.set_text(title_text)
        self._ui_poll_inflight = False
        return False

    def set_media_cover_path(self, path: str) -> None:
        if not path or not pathlib.Path(path).exists():
            self.media_cover.set_paintable(None)
            return
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 82, 82, True)
            texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self.media_cover.set_paintable(texture)
        except Exception:
            self.media_cover.set_paintable(None)

    def collect_media_state(self) -> dict[str, Any]:
        status = playerctl(["status"]) or "Stopped"
        metadata = playerctl(
            [
                "metadata",
                "--format",
                "{{title}}\t{{artist}}\t{{album}}\t{{playerName}}\t{{mpris:artUrl}}\t{{mpris:length}}",
            ]
        )
        fields = (metadata.split("\t") + ["", "", "", "", "", ""])[:6]
        title, artist, album, player_name, art_url, length_us = fields
        title = title or "Nothing playing"
        media_key = f"{player_name}|{artist}|{album}|{title}"
        if status in {"Playing", "Paused"} and art_url and art_url != self._last_media_art_url:
            self._last_media_art_url = art_url
            self._last_media_art_path = cache_art_from_url(art_url)
        elif not art_url:
            self._last_media_art_url = ""
            self._last_media_art_path = str(SPOTIFY_PLACEHOLDER) if SPOTIFY_PLACEHOLDER.exists() else ""
        art_path = self._last_media_art_path
        pos_text = playerctl(["position"])
        try:
            position = float(pos_text or "0")
        except Exception:
            position = 0.0
        try:
            length_seconds = max(float(length_us) / 1000000.0, 0.0)
        except Exception:
            length_seconds = 0.0
        progress_value = 0
        if length_seconds > 0:
            progress_value = int(max(0.0, min((position / length_seconds) * 100.0, 100.0)))
        elapsed = f"{int(position // 60)}:{int(position % 60):02d}"
        remaining_seconds = max(length_seconds - position, 0.0)
        remaining = f"-{int(remaining_seconds // 60)}:{int(remaining_seconds % 60):02d}"
        self._last_media_key = media_key
        return {
            "status": status,
            "title": title,
            "artist": artist,
            "album": album,
            "player_name": player_name,
            "art_path": art_path,
            "progress": str(progress_value),
            "elapsed": elapsed,
            "remaining": remaining,
        }

    def apply_media_state(self, state: dict[str, Any]) -> bool:
        status = state.get("status", "Stopped")
        title = state.get("title", "Nothing playing")
        artist = state.get("artist", "")
        album = state.get("album", "")
        player_name = state.get("player_name", "")
        art_path = state.get("art_path", "")
        progress = state.get("progress", "0")
        elapsed = state.get("elapsed", "0:00")
        remaining = state.get("remaining", "-0:00")
        active = status in {"Playing", "Paused"}
        self.media_cluster.set_visible(active or self.has_spotify or self.has_spotify_launcher)
        self.media_prev.set_sensitive(active)
        self.media_toggle.set_sensitive(active)
        self.media_next.set_sensitive(active)
        if not active:
            self.media_label.set_text("󰎆  Spotify")
            self.media_status_label.set_text("Ready")
            self.media_pop_title.set_text("No media playing")
            self.media_pop_artist.set_text("Open Spotify to start playback")
            self.media_pop_album.set_text("")
            self.media_elapsed.set_text("0:00")
            self.media_remaining.set_text("-0:00")
            self.media_progress.set_fraction(0.0)
            self.set_media_cover_path(str(SPOTIFY_PLACEHOLDER) if SPOTIFY_PLACEHOLDER.exists() else "")
            self.media_open_button.set_visible(self.has_spotify or self.has_spotify_launcher)
            self.media_toggle.set_label("󰐊")
            self._media_poll_inflight = False
            return False
        summary = truncate(f"{artist} - {title}" if artist else title, 28)
        self.media_label.set_text(f"󰎆  {summary}")
        self.media_toggle.set_label("󰏤" if status == "Playing" else "󰐊")
        self.media_status_label.set_text(f"{status.lower()}  •  {(player_name or 'player').title()}")
        self.media_pop_title.set_text(truncate(title, 30))
        self.media_pop_artist.set_text(artist or (player_name.title() if player_name else "Unknown artist"))
        self.media_pop_album.set_text(truncate(album or player_name or "", 32))
        self.media_elapsed.set_text(elapsed or "0:00")
        self.media_remaining.set_text(remaining or "-0:00")
        self.media_open_button.set_visible(self.has_spotify or self.has_spotify_launcher)
        try:
            self.media_progress.set_fraction(max(0.0, min(float(progress) / 100.0, 1.0)))
        except Exception:
            self.media_progress.set_fraction(0.0)
        if art_path and pathlib.Path(art_path).exists():
            self.set_media_cover_path(art_path)
        else:
            self.set_media_cover_path(str(SPOTIFY_PLACEHOLDER) if SPOTIFY_PLACEHOLDER.exists() else "")
        self._media_poll_inflight = False
        return False

    def refresh_media(self) -> None:
        self.queue_media_refresh()

    def collect_slow_state(self) -> dict[str, Any]:
        status_lines = run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"]).splitlines()
        wifi = next((line.split(":") for line in status_lines if ":wifi:" in line and ":connected:" in line), None)
        ethernet = next((line.split(":") for line in status_lines if ":ethernet:" in line and ":connected:" in line), None)
        current_wifi_device = next((line.split(":")[0] for line in status_lines if ":wifi:" in line), "")
        wifi_lines = run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"]).splitlines()
        candidates: dict[str, tuple[bool, int, str]] = {}
        for line in wifi_lines:
            parts = line.split(":")
            if len(parts) < 4:
                continue
            active_flag, ssid, signal, security = parts[:4]
            ssid = ssid or "<hidden>"
            is_active = active_flag in {"yes", "*"}
            try:
                signal_value = int(signal)
            except Exception:
                signal_value = 0
            current = candidates.get(ssid)
            if current is None or (is_active and not current[0]) or (is_active == current[0] and signal_value > current[1]):
                candidates[ssid] = (is_active, signal_value, security or "open")
        wifi_rows = []
        for ssid, (is_active, signal_value, security) in sorted(
            candidates.items(),
            key=lambda item: (not item[1][0], -item[1][1], item[0].lower()),
        ):
            wifi_rows.append(
                {
                    "ssid": ssid,
                    "is_active": is_active,
                    "signal": signal_value,
                    "security": security or "open",
                }
            )
            if len(wifi_rows) >= 6:
                break
        active = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"]).splitlines()
        current = next((line.split(":")[0] for line in active if line.endswith(":vpn")), "")
        self.vpn_label.set_text(f"󰒃  {truncate(current, 12)}" if current else "󰦝  vpn")
        profiles = []
        for line in run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"]).splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "vpn":
                profiles.append(parts[0])
        adapter = run(["bluetoothctl", "show"])
        powered = "Powered: yes" in adapter
        connected_lines = run(["bluetoothctl", "devices", "Connected"]).splitlines()
        paired = run(["bluetoothctl", "devices", "Paired"]).splitlines()
        all_devices = run(["bluetoothctl", "devices"]).splitlines()
        connected = len(connected_lines)
        summary = [f"Power: {'on' if powered else 'off'}"]
        if self.bluetooth_scanning:
            summary.append("Scanning for devices…")
        if connected_lines:
            summary.append("Connected:")
            summary.extend(f"• {line.split(' ', 2)[2]}" for line in connected_lines if " " in line)
        elif paired:
            summary.append("Paired devices available")
        else:
            summary.append("No paired devices")
        connected_macs = {line.split(" ", 2)[1] for line in connected_lines if len(line.split(" ", 2)) >= 3}
        bluetooth_rows = []
        for line in all_devices:
            parts = line.split(" ", 2)
            if len(parts) < 3:
                continue
            _device, mac, name = parts
            is_connected = mac in connected_macs
            is_paired = any(p.startswith(f"Device {mac} ") for p in paired)
            bluetooth_rows.append(
                {
                    "mac": mac,
                    "name": name,
                    "subtitle": "connected" if is_connected else "paired" if is_paired else "available",
                    "is_connected": is_connected,
                }
            )
            if len(bluetooth_rows) >= 5:
                break
        cpu_rows = load_stats("cpu") or []
        ram = load_stats("ram") or {}
        gpu = load_stats("gpu") or {}
        disks = load_stats("disks") or []
        info = battery_info()
        profile = run(["powerprofilesctl", "get"]) or "unknown"
        return {
            "network": {
                "wifi": wifi,
                "ethernet": ethernet,
                "current_wifi_device": current_wifi_device,
                "rows": wifi_rows,
            },
            "vpn": {"current": current, "profiles": profiles[:5]},
            "bluetooth": {
                "powered": powered,
                "connected_count": connected,
                "summary": "\n".join(summary),
                "rows": bluetooth_rows,
            },
            "stats": {"cpu_rows": cpu_rows, "ram": ram, "gpu": gpu, "disks": disks},
            "battery": {"info": info, "profile": profile},
        }

    def apply_slow_state(self, state: dict[str, Any]) -> bool:
        self.apply_network_state(state.get("network", {}))
        self.apply_vpn_state(state.get("vpn", {}))
        self.apply_bluetooth_state(state.get("bluetooth", {}))
        self.apply_stats_state(state.get("stats", {}))
        self.apply_battery_state(state.get("battery", {}))
        self._slow_poll_inflight = False
        return False

    def apply_network_state(self, state: dict[str, Any]) -> None:
        wifi = state.get("wifi")
        ethernet = state.get("ethernet")
        self.current_wifi_device = state.get("current_wifi_device", "")
        if wifi:
            self.network_label.set_text(f"󰤨  {truncate(wifi[3], 14)}")
            self.network_detail.set_text(f"Connected via Wi-Fi\n{truncate(wifi[3], 28)}")
        elif ethernet:
            self.network_label.set_text(f"󰈀  {truncate(ethernet[3] or ethernet[0], 14)}")
            self.network_detail.set_text(f"Connected via Ethernet\n{truncate(ethernet[3] or ethernet[0], 28)}")
        else:
            self.network_label.set_text("󰤮  offline")
            self.network_detail.set_text("Network offline")
        self.clear_box(self.network_rows)
        rows = state.get("rows", [])
        if not rows:
            self.network_rows.append(
                self.make_list_row_button(
                    "No Wi-Fi networks",
                    "Open nmtui for manual setup",
                    "",
                    lambda _btn: dispatch_exec("kitty -e nmtui"),
                )
            )
            return
        for row_data in rows:
            ssid = row_data.get("ssid", "<hidden>")
            is_active = bool(row_data.get("is_active", False))
            signal_value = int(row_data.get("signal", 0))
            security = row_data.get("security", "open")
            self.network_rows.append(
                self.make_list_row_button(
                    ("✓ " if is_active else "") + truncate(ssid, 22),
                    truncate(security or "open", 20),
                    f"{signal_value}%",
                    lambda _btn, ssid=ssid, is_active=is_active: self.activate_wifi_row(ssid, is_active),
                    accent=is_active,
                )
            )

    def apply_vpn_state(self, state: dict[str, Any]) -> None:
        current = state.get("current", "")
        profiles = state.get("profiles", [])
        self.vpn_label.set_text(f"󰒃  {truncate(current, 12)}" if current else "󰦝  vpn")
        self.vpn_detail.set_text(current if current else "No active VPN")
        self.clear_box(self.vpn_profiles_box)
        if not profiles:
            self.vpn_profiles_box.append(
                self.make_list_row_button(
                    "No VPN profiles",
                    "Open nmtui to add or import one",
                    "",
                    lambda _btn: dispatch_exec("kitty -e nmtui"),
                )
            )
            return
        for name in profiles:
            is_active = name == current
            self.vpn_profiles_box.append(
                self.make_list_row_button(
                    truncate(name, 22),
                    "active" if is_active else "available",
                    "on" if is_active else "off",
                    lambda _btn, name=name, is_active=is_active: self.toggle_vpn_connection(name, is_active),
                    accent=is_active,
                )
            )

    def apply_bluetooth_state(self, state: dict[str, Any]) -> None:
        connected = int(state.get("connected_count", 0))
        powered = bool(state.get("powered", False))
        if connected:
            self.bluetooth_label.set_text(f"󰂱  {connected}")
        else:
            self.bluetooth_label.set_text("󰂯  on" if powered else "󰂲  off")
        self.bluetooth_detail.set_text(state.get("summary", "No paired devices"))
        self.bluetooth_power_button.set_label("Power off" if powered else "Power on")
        self.bluetooth_scan_button.set_label("Scanning…" if self.bluetooth_scanning else "Scan")
        self.clear_box(self.bluetooth_rows)
        rows = state.get("rows", [])
        if not rows:
            self.bluetooth_rows.append(
                self.make_list_row_button(
                    "No devices found",
                    "Start a scan to discover nearby devices",
                    "",
                    lambda _btn: self.start_bluetooth_scan(),
                )
            )
            return
        for row_data in rows:
            mac = row_data.get("mac", "")
            name = row_data.get("name", "device")
            is_connected = bool(row_data.get("is_connected", False))
            self.bluetooth_rows.append(
                self.make_list_row_button(
                    truncate(name, 22),
                    row_data.get("subtitle", "available"),
                    "",
                    lambda _btn, mac=mac, is_connected=is_connected: self.toggle_bluetooth_device(mac, is_connected),
                    accent=is_connected,
                )
            )

    def apply_stats_state(self, state: dict[str, Any]) -> None:
        cpu_rows = state.get("cpu_rows", []) or []
        ram = state.get("ram", {}) or {}
        gpu = state.get("gpu", {}) or {}
        disks = state.get("disks", []) or []

        if cpu_rows:
            avg_cpu = int(sum(int(row.get("usage", 0)) for row in cpu_rows) / len(cpu_rows))
            self.cpu_label.set_text(f"  {avg_cpu}%")
            cpu_lines = []
            for index in range(0, min(len(cpu_rows), 12), 2):
                left = cpu_rows[index]
                right = cpu_rows[index + 1] if index + 1 < len(cpu_rows) else None
                left_text = f"{left.get('label','c0'):>3} {left.get('usage', 0):>2}%  {left.get('temp', '--'):>2}C"
                if right:
                    right_text = f"{right.get('label','c1'):>3} {right.get('usage', 0):>2}%  {right.get('temp', '--'):>2}C"
                    cpu_lines.append(f"{left_text}    {right_text}")
                else:
                    cpu_lines.append(left_text)
            self.cpu_detail.set_text("\n".join(cpu_lines))
        elif not self.cpu_detail.get_text():
            self.cpu_detail.set_text("Loading…")

        if ram:
            self.ram_label.set_text(f"  {ram.get('pct', 0)}%")
            self.ram_detail.set_text(
                "\n".join(
                    [
                        f"used   {ram.get('used', '--')} / {ram.get('total', '--')}  {ram.get('pct', 0)}%",
                        f"free   {ram.get('free', '--')}",
                        f"cache  {ram.get('cache', '--')}",
                        f"shared {ram.get('shared', '--')}",
                        f"swap   {ram.get('swap', '--')}",
                    ]
                )
            )

        if gpu:
            self.gpu_label.set_text("󰢮" if gpu.get("available", True) else "󰢮?")
        if gpu.get("available", False):
            self.gpu_detail.set_text(
                "\n".join(
                    [
                        truncate(gpu.get("name", "GPU"), 28),
                        f"load   {gpu.get('load', 0)}%",
                        f"temp   {gpu.get('temp', '--')}C",
                        f"vram   {gpu.get('vram', '--')}  {gpu.get('vram_pct', 0)}%",
                        f"power  {gpu.get('power', '--')}",
                    ]
                )
            )
        elif gpu and not gpu.get("available", True):
            self.gpu_detail.set_text("No NVIDIA GPU data")

        if disks:
            root_disk = next((disk for disk in disks if disk.get("label") == "/"), {})
            self.disk_label.set_text(f"󰋊  {root_disk.get('pct', '--')}%")
            self.disk_detail.set_text(
                "\n".join(f"{disk.get('label','?'):6} {disk.get('pct','--'):>3}%  {disk.get('usage','--')}" for disk in disks)
            )

    def apply_battery_state(self, state: dict[str, Any]) -> None:
        info = state.get("info", {}) or {}
        profile = state.get("profile", "unknown")
        self.battery_label.set_text(f"󰁹  {info.get('capacity', '--')}%")
        self.power_detail.set_text(f"battery {info.get('capacity', '--')}%  {info.get('status', 'Unknown').lower()}\nprofile {profile}")
        self.clear_box(self.power_buttons_box)
        for profile_name in ("performance", "balanced", "power-saver"):
            button = self.make_popover_button(
                profile_name,
                lambda _btn, profile_name=profile_name: self.set_power_profile(profile_name),
                accent=profile_name == profile,
            )
            self.power_buttons_box.append(button)

    def refresh_network(self) -> None:
        self.queue_slow_refresh()

    def refresh_vpn(self) -> None:
        self.queue_slow_refresh()

    def refresh_bluetooth(self) -> None:
        self.queue_slow_refresh()

    def refresh_stats(self) -> None:
        self.queue_slow_refresh()

    def refresh_battery(self) -> None:
        self.queue_slow_refresh()

    def refresh_clock(self) -> None:
        now = GLib.DateTime.new_now_local()
        self.date_label.set_text(now.format("󰃭  %d %b"))
        self.time_label.set_text(now.format("󰥔  %H:%M"))
        self.calendar_summary.set_text(now.format("%A, %d %B"))

    def jump_calendar_today(self) -> None:
        now = GLib.DateTime.new_now_local()
        self.calendar.set_year(now.get_year())
        self.calendar.set_month(now.get_month() - 1)
        self.calendar.select_day(now)

    def toggle_media(self) -> None:
        run_ok([str(SPOTIFY_SCRIPT), "toggle"])
        self.refresh_media()

    def toggle_bluetooth(self) -> None:
        adapter = run(["bluetoothctl", "show"])
        powered = "Powered: yes" in adapter
        run_ok(["bluetoothctl", "power", "off" if powered else "on"])
        self.refresh_bluetooth()

    def toggle_bluetooth_device(self, mac: str, is_connected: bool) -> None:
        run_ok(["bluetoothctl", "disconnect" if is_connected else "connect", mac], timeout=12.0)
        self.refresh_bluetooth()

    def start_bluetooth_scan(self) -> None:
        self.bluetooth_scanning = True
        self.refresh_bluetooth()
        subprocess.Popen(
            ["sh", "-lc", "bluetoothctl scan on >/dev/null 2>&1; sleep 8; bluetoothctl scan off >/dev/null 2>&1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        GLib.timeout_add_seconds(1, self.bluetooth_scan_tick)
        GLib.timeout_add_seconds(9, self.finish_bluetooth_scan)

    def bluetooth_scan_tick(self) -> bool:
        if not self.bluetooth_scanning:
            return False
        self.refresh_bluetooth()
        return True

    def finish_bluetooth_scan(self) -> bool:
        self.bluetooth_scanning = False
        self.refresh_bluetooth()
        return False

    def activate_wifi_row(self, ssid: str, is_active: bool) -> None:
        if is_active and self.current_wifi_device:
            run_ok(["nmcli", "device", "disconnect", self.current_wifi_device], timeout=12.0)
        else:
            success = run_ok(["nmcli", "device", "wifi", "connect", ssid], timeout=20.0)
            if not success:
                dispatch_exec("kitty -e nmtui")
        self.refresh_network()

    def rescan_wifi(self) -> None:
        if self.current_wifi_device:
            run_ok(["nmcli", "device", "wifi", "rescan", "ifname", self.current_wifi_device], timeout=8.0)
        else:
            run_ok(["nmcli", "device", "wifi", "rescan"], timeout=8.0)
        self.refresh_network()

    def toggle_vpn_connection(self, name: str, is_active: bool) -> None:
        if is_active:
            run_ok(["nmcli", "connection", "down", name], timeout=12.0)
        else:
            run_ok(["nmcli", "connection", "up", name], timeout=20.0)
        self.refresh_vpn()
        self.refresh_network()

    def set_power_profile(self, profile_name: str) -> None:
        run_ok(["powerprofilesctl", "set", profile_name], timeout=6.0)
        self.refresh_battery()

    def launch_spotify(self) -> None:
        client = find_spotify_client()
        if client:
            workspace_id = int((client.get("workspace") or {}).get("id", 1))
            run_ok(["hyprctl", "dispatch", "workspace", str(workspace_id)], timeout=2.0)
            klass = client.get("class") or client.get("initialClass") or "Spotify"
            run_ok(["hyprctl", "dispatch", "focuswindow", f"class:^({klass})$"], timeout=2.0)
            return
        run_ok(["hyprctl", "dispatch", "workspace", "6"], timeout=2.0)
        if self.has_spotify:
            dispatch_exec("spotify")
        elif self.has_spotify_launcher:
            dispatch_exec("spotify-launcher")

    def open_debug_popover(self) -> bool:
        mapping = {
            "media": self.media_button,
            "network": self.network_button,
            "vpn": self.vpn_button,
            "bluetooth": self.bluetooth_button,
            "cpu": self.cpu_button,
            "ram": self.ram_button,
            "gpu": self.gpu_button,
            "disk": self.disk_button,
            "power": self.battery_button,
            "date": self.date_button,
        }
        target = mapping.get(self.debug_target)
        if target is not None:
            target.set_active(True)
            target.popup()
        return False


class MinimalBarApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="local.yayky.MinimalGtkBar")
        self.window: MinimalBarWindow | None = None

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MinimalBarWindow(self)
        self.window.present()


def main() -> int:
    app = MinimalBarApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
