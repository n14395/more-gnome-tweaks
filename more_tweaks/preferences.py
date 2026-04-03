"""App preferences stored in ~/.config/more-tweaks/preferences.json."""
from __future__ import annotations

import json
import logging
import os
import pwd
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk

_log = logging.getLogger("more_tweaks.preferences")

_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
_CONFIG_DIR = _REAL_HOME / ".config" / "more-tweaks"
_PREFS_FILE = _CONFIG_DIR / "preferences.json"

_DEFAULTS: dict[str, object] = {
    "hide_unavailable": False,
    "show_command_hints": True,
    "confirm_individual_reset": False,
    "default_export_dir": "",
    "startup_category": "last",
}


class Preferences:
    """Lightweight JSON-backed preference store."""

    def __init__(self):
        self._data: dict[str, object] = dict(_DEFAULTS)
        self._callbacks: list[Callable[[str], None]] = []
        self._load()

    def _load(self):
        if _PREFS_FILE.exists():
            try:
                saved = json.loads(_PREFS_FILE.read_text(encoding="utf-8"))
                for key, default in _DEFAULTS.items():
                    if key in saved and isinstance(saved[key], type(default)):
                        self._data[key] = saved[key]
            except (json.JSONDecodeError, OSError):
                _log.warning("Failed to load preferences", exc_info=True)

    def _save(self):
        try:
            _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _PREFS_FILE.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except OSError:
            _log.warning("Failed to save preferences", exc_info=True)

    def get(self, key: str) -> object:
        return self._data.get(key, _DEFAULTS.get(key))

    def set(self, key: str, value: object):
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._save()
        for cb in self._callbacks:
            cb(key)

    def connect_changed(self, callback: Callable[[str], None]):
        self._callbacks.append(callback)

    @property
    def hide_unavailable(self) -> bool:
        return bool(self.get("hide_unavailable"))

    @property
    def show_command_hints(self) -> bool:
        return bool(self.get("show_command_hints"))

    @property
    def confirm_individual_reset(self) -> bool:
        return bool(self.get("confirm_individual_reset"))

    @property
    def default_export_dir(self) -> str:
        return str(self.get("default_export_dir") or "")

    @property
    def startup_category(self) -> str:
        return str(self.get("startup_category") or "last")


_instance: Preferences | None = None


def get_preferences() -> Preferences:
    global _instance
    if _instance is None:
        _instance = Preferences()
    return _instance


class PreferencesDialog(Adw.PreferencesWindow):
    """App preferences dialog."""

    def __init__(self, prefs: Preferences, categories: list | None = None, **kwargs):
        super().__init__(
            title="Preferences",
            search_enabled=False,
            **kwargs,
        )
        self.prefs = prefs
        self.set_default_size(480, 520)

        page = Adw.PreferencesPage()

        # --- Appearance group ---
        appearance = Adw.PreferencesGroup(
            title="Appearance",
            description="Control what is shown in the tweak list.",
        )

        hide_row = Adw.ActionRow(
            title="Hide unavailable tweaks",
            subtitle="Don't show tweaks whose GSettings schema is missing.",
        )
        hide_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        hide_switch.set_active(prefs.hide_unavailable)
        hide_switch.connect("notify::active", self._on_bool_changed, "hide_unavailable")
        hide_row.add_suffix(hide_switch)
        hide_row.set_activatable_widget(hide_switch)
        appearance.add(hide_row)

        hints_row = Adw.ActionRow(
            title="Show command hints",
            subtitle="Display a copy button for the gsettings command on each tweak.",
        )
        hints_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        hints_switch.set_active(prefs.show_command_hints)
        hints_switch.connect("notify::active", self._on_bool_changed, "show_command_hints")
        hints_row.add_suffix(hints_switch)
        hints_row.set_activatable_widget(hints_switch)
        appearance.add(hints_row)

        page.add(appearance)

        # --- Behavior group ---
        behavior = Adw.PreferencesGroup(
            title="Behavior",
            description="Control how the app behaves.",
        )

        confirm_row = Adw.ActionRow(
            title="Confirm before resetting",
            subtitle="Ask for confirmation before resetting an individual tweak to its default.",
        )
        confirm_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        confirm_switch.set_active(prefs.confirm_individual_reset)
        confirm_switch.connect("notify::active", self._on_bool_changed, "confirm_individual_reset")
        confirm_row.add_suffix(confirm_switch)
        confirm_row.set_activatable_widget(confirm_switch)
        behavior.add(confirm_row)

        # Startup category
        startup_row = Adw.ActionRow(
            title="Startup category",
            subtitle="Which category to show when the app opens.",
        )
        startup_options = ["Remember last"]
        startup_values = ["last"]
        if categories:
            for cat in categories:
                startup_options.append(cat.name)
                startup_values.append(cat.id)
        self._startup_values = startup_values

        startup_dd = Gtk.DropDown.new_from_strings(startup_options)
        startup_dd.set_valign(Gtk.Align.CENTER)
        current = prefs.startup_category
        try:
            startup_dd.set_selected(startup_values.index(current))
        except ValueError:
            startup_dd.set_selected(0)
        startup_dd.connect("notify::selected", self._on_startup_changed)
        startup_row.add_suffix(startup_dd)
        behavior.add(startup_row)

        page.add(behavior)

        # --- Export group ---
        export_group = Adw.PreferencesGroup(
            title="Export",
            description="Defaults for exporting settings.",
        )

        export_row = Adw.ActionRow(
            title="Default export folder",
            subtitle=prefs.default_export_dir or "None (use system default)",
        )
        self._export_row = export_row

        choose_btn = Gtk.Button(label="Choose")
        choose_btn.set_valign(Gtk.Align.CENTER)
        choose_btn.connect("clicked", self._on_choose_export_dir)
        export_row.add_suffix(choose_btn)

        if prefs.default_export_dir:
            clear_btn = Gtk.Button.new_from_icon_name("edit-clear-symbolic")
            clear_btn.set_valign(Gtk.Align.CENTER)
            clear_btn.add_css_class("flat")
            clear_btn.set_tooltip_text("Clear default folder")
            clear_btn.connect("clicked", self._on_clear_export_dir)
            export_row.add_suffix(clear_btn)
            self._export_clear_btn = clear_btn
        else:
            self._export_clear_btn = None

        export_group.add(export_row)
        page.add(export_group)

        self.add(page)

    def _on_bool_changed(self, switch: Gtk.Switch, _pspec, key: str):
        self.prefs.set(key, switch.get_active())

    def _on_startup_changed(self, dropdown: Gtk.DropDown, _pspec):
        idx = dropdown.get_selected()
        if idx < len(self._startup_values):
            self.prefs.set("startup_category", self._startup_values[idx])

    def _on_choose_export_dir(self, _btn):
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose default export folder")
        current = self.prefs.default_export_dir
        if current and Path(current).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(current))
        dialog.select_folder(self, None, self._on_export_dir_chosen)

    def _on_export_dir_chosen(self, dialog: Gtk.FileDialog, result):
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        self.prefs.set("default_export_dir", path)
        self._export_row.set_subtitle(path)

    def _on_clear_export_dir(self, _btn):
        self.prefs.set("default_export_dir", "")
        self._export_row.set_subtitle("None (use system default)")
