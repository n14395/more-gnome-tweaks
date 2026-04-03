from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .settings_backend import SettingsBackend
from .tweak_row import TweakRow, TextListRow, ExtensionListRow
from ._shared import (
    _ScrollPreservingSection,
    _clear_box,
    _build_runtime_status,
    _build_status_page,
    _check_capability,
)
from .data import filter_tweaks


# ── Gesture choice definitions ─────────────────────────────────────────

# Actions available for every gesture direction.
_GESTURE_ACTIONS = (
    ("default", "Default"),
    ("disabled", "Disabled"),
    ("overview", "Activities overview"),
    ("app-grid", "App grid"),
    ("show-desktop", "Show desktop"),
    ("notification-center", "Notification center"),
    ("quick-settings", "Quick settings"),
    ("workspace-left", "Workspace left"),
    ("workspace-right", "Workspace right"),
    ("screenshot", "Screenshot"),
    ("lock-screen", "Lock screen"),
    ("run-dialog", "Run dialog"),
    ("window-switcher", "Window switcher"),
)

# Ordered list of (gsettings-key, display-label, description).
_GESTURE_ROWS = (
    ("gesture-3f-swipe-up",    "Three-finger swipe up",    "Default: Activities overview"),
    ("gesture-3f-swipe-down",  "Three-finger swipe down",  "Default: close overview"),
    ("gesture-3f-swipe-left",  "Three-finger swipe left",  "No default GNOME binding"),
    ("gesture-3f-swipe-right", "Three-finger swipe right",  "No default GNOME binding"),
    ("gesture-4f-swipe-up",    "Four-finger swipe up",      "No default GNOME binding"),
    ("gesture-4f-swipe-down",  "Four-finger swipe down",    "No default GNOME binding"),
    ("gesture-4f-swipe-left",  "Four-finger swipe left",    "Default: workspace left"),
    ("gesture-4f-swipe-right", "Four-finger swipe right",   "Default: workspace right"),
)


class TouchpadSection(_ScrollPreservingSection):
    """Hybrid section for the Touchpad & Gestures category:
    standard touchpad tweaks + extension-backed gesture overrides."""

    def __init__(self, notify: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, notify=notify)
        self.set_margin_bottom(48)
        self._backend = SettingsBackend()
        self._tweak_rows: list[TweakRow | TextListRow] = []
        self._gesture_widgets: dict[str, Gtk.DropDown] = {}
        self._updating_gestures = False

    def refresh(self):
        sw, pos = self._save_scroll()
        try:
            self._refresh_inner()
        finally:
            self._restore_scroll(sw, pos)

    def _refresh_inner(self):
        self._animation_backend.refresh_runtime_state()
        _clear_box(self)
        self._tweak_rows.clear()
        self._gesture_widgets.clear()

        # ── Standard GSettings touchpad tweaks ─────────────────────────
        tweaks_group = Adw.PreferencesGroup(
            title="Touchpad Settings",
            description="Speed, tapping, scrolling, and click behavior.",
        )
        tweaks = filter_tweaks("", "touchpad")
        for tweak in tweaks:
            if tweak.control == "text-list":
                row = TextListRow(tweak, self._backend)
            elif tweak.control == "extension-list":
                row = ExtensionListRow(tweak, self._backend)
            else:
                row = TweakRow(tweak, self._backend)
            self._tweak_rows.append(row)
            tweaks_group.add(row)
        self.append(tweaks_group)

        # Runtime status — compact single-row display when action needed
        for w in _build_runtime_status(
            self._animation_backend,
            on_install=self._on_install_runtime,
            on_enable_changed=self._on_enable_runtime,
            feature_label="Gesture overrides",
        ):
            self.append(w)

        # ── Gesture overrides (requires the extension) ─────────────────
        if self._animation_backend.needs_shell_restart:
            self.append(_build_status_page(
                icon_name="system-log-out-symbolic",
                title="Log Out Required",
                description=(
                    "The bundled shell runtime has been installed, but GNOME Shell "
                    "needs to restart to detect it.\n\n"
                    "On Wayland, log out and log back in. "
                    "Gesture overrides will become available after that."
                ),
            ))
            return

        if not self._animation_backend.available:
            self.append(_build_status_page(
                icon_name="input-touchpad-symbolic",
                title="Gesture Overrides",
                description=(
                    "Custom three-finger and four-finger swipe actions require "
                    "the bundled GNOME Shell extension.\n\n"
                    "Use the Install button above to set it up."
                ),
            ))
            return

        if page := _check_capability(
            self._animation_backend, "gestures", "Gesture Overrides"):
            self.append(page)
            return

        self._build_gesture_group()

    def _build_gesture_group(self):
        group = Adw.PreferencesGroup(
            title="Gesture Overrides",
            description=(
                "Remap or disable three-finger and four-finger touchpad swipe actions. "
                "Requires the bundled shell extension to be running."
            ),
        )

        # Master switch
        enable_row = Adw.ActionRow(
            title="Enable gesture overrides",
            subtitle="Intercept built-in swipe gestures and apply custom actions.",
        )
        enable_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        enabled = self._animation_backend._get_boolean(
            "gesture-overrides-enabled", default=False)
        enable_switch.set_active(enabled)
        enable_switch.connect("notify::active", self._on_gesture_master_switch)
        enable_row.add_suffix(enable_switch)
        self._gesture_master_switch = enable_switch
        group.add(enable_row)

        self.append(group)

        # Shared action values/labels for dropdowns
        labels = [label for _val, label in _GESTURE_ACTIONS]
        values = [val for val, _label in _GESTURE_ACTIONS]

        # Three-finger group
        group_3f = Adw.PreferencesGroup(title="Three-Finger Swipes")
        for key, title, subtitle in _GESTURE_ROWS:
            if not key.startswith("gesture-3f"):
                continue
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            dropdown = Gtk.DropDown.new_from_strings(labels)
            dropdown.set_valign(Gtk.Align.CENTER)

            current = self._animation_backend._get_string(key, default="default")
            try:
                dropdown.set_selected(values.index(current))
            except ValueError:
                dropdown.set_selected(0)

            dropdown.set_sensitive(enabled)
            dropdown.connect("notify::selected",
                             self._on_gesture_choice_changed, key, values)
            row.add_suffix(dropdown)
            group_3f.add(row)
            self._gesture_widgets[key] = dropdown
        self.append(group_3f)

        # Four-finger group
        group_4f = Adw.PreferencesGroup(title="Four-Finger Swipes")
        for key, title, subtitle in _GESTURE_ROWS:
            if not key.startswith("gesture-4f"):
                continue
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            dropdown = Gtk.DropDown.new_from_strings(labels)
            dropdown.set_valign(Gtk.Align.CENTER)

            current = self._animation_backend._get_string(key, default="default")
            try:
                dropdown.set_selected(values.index(current))
            except ValueError:
                dropdown.set_selected(0)

            dropdown.set_sensitive(enabled)
            dropdown.connect("notify::selected",
                             self._on_gesture_choice_changed, key, values)
            row.add_suffix(dropdown)
            group_4f.add(row)
            self._gesture_widgets[key] = dropdown
        self.append(group_4f)

    def _on_gesture_master_switch(self, switch: Gtk.Switch, _pspec):
        active = switch.get_active()
        self._animation_backend._set_boolean("gesture-overrides-enabled", active)
        for dropdown in self._gesture_widgets.values():
            dropdown.set_sensitive(active)

    def _on_gesture_choice_changed(self, dropdown: Gtk.DropDown, _pspec,
                                   key: str, values: list[str]):
        if self._updating_gestures:
            return
        idx = dropdown.get_selected()
        if 0 <= idx < len(values):
            self._animation_backend._set_string(key, values[idx])
