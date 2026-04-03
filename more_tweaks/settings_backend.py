from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib

from .models import Tweak

_log = logging.getLogger("more_tweaks.settings_backend")


def _unit_for_key(key: str) -> str:
    """Determine a display unit suffix for a tweak based on its key name."""
    if key == "idle-delay" or key == "lock-delay":
        return "s"
    if "delay" in key or "interval" in key:
        return "ms"
    if "speed" in key:
        return ""
    if "size" in key or "width" in key:
        return "px"
    if "age" in key:
        return "days"
    if "port" in key:
        return ""
    return ""


def _list_installed_themes(key: str) -> list[str]:
    """Scan standard directories for installed theme names."""
    dirs: list[Path] = []
    home = Path.home()
    if key == "gtk-theme":
        dirs = [Path("/usr/share/themes"), home / ".themes", home / ".local/share/themes"]
        # A valid GTK theme dir has a gtk-*/gtk.css inside
        check = lambda p: any(p.glob("gtk-*/gtk.css")) or any(p.glob("gtk-*/gtk-*.css"))
    elif key == "icon-theme":
        dirs = [Path("/usr/share/icons"), home / ".icons", home / ".local/share/icons"]
        check = lambda p: (p / "index.theme").is_file()
    elif key == "cursor-theme":
        dirs = [Path("/usr/share/icons"), home / ".icons", home / ".local/share/icons"]
        check = lambda p: (p / "cursors").is_dir()
    else:
        return []

    names: set[str] = set()
    for d in dirs:
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if child.is_dir() and check(child):
                names.add(child.name)
    return sorted(names, key=str.casefold)


class SettingsBackend:
    def __init__(self):
        self._settings: dict[str, Gio.Settings] = {}
        self._schemas: dict[str, Gio.SettingsSchema] = {}
        self._schema_source = Gio.SettingsSchemaSource.get_default()
        self._change_callbacks: list[Callable[[str, str], None]] = []
        self._suppressed: set[tuple[str, str]] = set()
        self._gnome_version: int | None = None

    @property
    def gnome_version(self) -> int:
        if self._gnome_version is None:
            from .animations import detect_gnome_shell_version
            self._gnome_version = detect_gnome_shell_version()
        return self._gnome_version

    def connect_change_callback(self, cb: Callable[[str, str], None]):
        self._change_callbacks.append(cb)

    def disconnect_change_callback(self, cb: Callable[[str, str], None]):
        try:
            self._change_callbacks.remove(cb)
        except ValueError:
            pass

    def suppress(self, schema: str, key: str):
        self._suppressed.add((schema, key))

    def _on_settings_changed(self, _settings: Gio.Settings, key: str, schema: str):
        if (schema, key) in self._suppressed:
            self._suppressed.discard((schema, key))
            return
        for cb in self._change_callbacks:
            cb(schema, key)

    @staticmethod
    def _parse_schema(schema: str) -> tuple[str, str | None]:
        if ":/" in schema:
            schema_id, path = schema.split(":/", 1)
            return schema_id, "/" + path
        return schema, None

    def _get_schema(self, schema: str) -> Gio.SettingsSchema | None:
        schema_id, _ = self._parse_schema(schema)
        if schema_id in self._schemas:
            return self._schemas[schema_id]

        if self._schema_source is None:
            return None

        schema_obj = self._schema_source.lookup(schema_id, True)
        if schema_obj is None:
            return None

        self._schemas[schema_id] = schema_obj
        return schema_obj

    def is_available(self, tweak: Tweak) -> bool:
        schema = self._get_schema(tweak.schema)
        if schema is None:
            return False
        return schema.has_key(tweak.key)

    def unavailable_reason(self, tweak: Tweak) -> str | None:
        """Return a short user-facing reason string, or *None* if available."""
        schema = self._get_schema(tweak.schema)
        if schema is None:
            if tweak.unavailable_hint:
                return tweak.unavailable_hint
            return "Not Installed"
        if not schema.has_key(tweak.key):
            if tweak.unavailable_hint:
                return tweak.unavailable_hint
            ver = self.gnome_version
            if tweak.max_gnome is not None and ver > tweak.max_gnome:
                return f"Removed in GNOME {tweak.max_gnome + 1}"
            if tweak.min_gnome is not None and (ver == 0 or ver < tweak.min_gnome):
                return f"Requires GNOME {tweak.min_gnome}+"
            return "Not Available"
        return None

    def _get_settings(self, schema: str) -> Gio.Settings | None:
        if schema in self._settings:
            return self._settings[schema]

        schema_obj = self._get_schema(schema)
        if schema_obj is None:
            return None

        _, path = self._parse_schema(schema)
        settings = Gio.Settings.new_full(schema_obj, None, path)
        settings.connect("changed", self._on_settings_changed, schema)
        self._settings[schema] = settings
        return settings

    def read(self, tweak: Tweak):
        if not self.is_available(tweak):
            return None

        settings = self._get_settings(tweak.schema)
        if settings is None:
            return None

        value = settings.get_value(tweak.key).unpack()
        if tweak.control == "feature-toggle":
            feature = str(tweak.choices[0].value)
            return feature in value
        if tweak.control == "keybinding":
            return value[0] if value else ""
        if tweak.control == "text-list":
            return ", ".join(value) if isinstance(value, list) else str(value)
        if tweak.value_type == "tuple-ii" and isinstance(value, tuple):
            if tweak.control == "dimensions":
                return value  # return raw tuple for dual spinners
            return f"{value[0]}, {value[1]}"
        return value

    def write(self, tweak: Tweak, value) -> bool:
        if not self.is_available(tweak):
            return False

        settings = self._get_settings(tweak.schema)
        if settings is None:
            return False

        default_value = settings.get_default_value(tweak.key)
        if default_value is None:
            return False

        type_string = default_value.get_type_string()

        try:
            self._suppressed.add((tweak.schema, tweak.key))
            if tweak.control == "feature-toggle":
                current = list(settings.get_value(tweak.key).unpack())
                feature = str(tweak.choices[0].value)
                if value and feature not in current:
                    current.append(feature)
                if not value and feature in current:
                    current.remove(feature)
                return settings.set_value(tweak.key, GLib.Variant(type_string, current))

            if tweak.control == "keybinding":
                value = [value] if value else []
                return settings.set_value(tweak.key, GLib.Variant(type_string, value))

            if tweak.control == "text-list":
                value = [v.strip() for v in str(value).split(",") if v.strip()]
                return settings.set_value(tweak.key, GLib.Variant(type_string, value))

            if tweak.value_type == "tuple-ii":
                parts = [p.strip() for p in str(value).split(",")]
                if len(parts) != 2:
                    return False
                value = (int(parts[0]), int(parts[1]))
                return settings.set_value(tweak.key, GLib.Variant(type_string, value))

            return settings.set_value(tweak.key, GLib.Variant(type_string, value))
        except Exception:
            _log.warning("Failed to write %s::%s", tweak.schema, tweak.key, exc_info=True)
            self._suppressed.discard((tweak.schema, tweak.key))
            return False

    def reset(self, tweak: Tweak) -> bool:
        """Reset a tweak's key back to its GSettings default value."""
        if not self.is_available(tweak):
            return False
        settings = self._get_settings(tweak.schema)
        if settings is None:
            return False
        try:
            self._suppressed.add((tweak.schema, tweak.key))
            settings.reset(tweak.key)
            return True
        except Exception:
            _log.warning("Failed to reset %s::%s", tweak.schema, tweak.key, exc_info=True)
            self._suppressed.discard((tweak.schema, tweak.key))
            return False

    def is_default(self, tweak: Tweak) -> bool:
        """Return True if the tweak's current value matches the schema default."""
        if not self.is_available(tweak):
            return True
        settings = self._get_settings(tweak.schema)
        if settings is None:
            return True
        current = settings.get_value(tweak.key)
        default = settings.get_default_value(tweak.key)
        if default is None:
            return True
        return current.equal(default)
