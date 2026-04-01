from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from .animation_preview import AnimationPreviewWidget
from .animations import AnimationBackend, PROFILE_NAMES
from .animation_catalog import PER_APP_ACTIONS, OPEN_PRESETS
from .custom_presets import CustomPresetStore
from .data import CATEGORIES, CHILD_CATEGORIES, TWEAKS, filter_tweaks
from .models import Category, Tweak
from .preset_data import TRANSFORM_PRESETS
from .timeline_widget import AnimationTimelineWidget


# Modifier keycodes that should not finalise a shortcut on their own.
_MODIFIER_KEYVALS = {
    Gdk.KEY_Shift_L, Gdk.KEY_Shift_R,
    Gdk.KEY_Control_L, Gdk.KEY_Control_R,
    Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
    Gdk.KEY_Super_L, Gdk.KEY_Super_R,
    Gdk.KEY_Meta_L, Gdk.KEY_Meta_R,
    Gdk.KEY_Hyper_L, Gdk.KEY_Hyper_R,
    Gdk.KEY_ISO_Level3_Shift,  # AltGr
    Gdk.KEY_Caps_Lock, Gdk.KEY_Num_Lock, Gdk.KEY_Scroll_Lock,
}


class ShortcutRecorderButton(Gtk.Button):
    """A button that records a keyboard shortcut when clicked.

    Click once to start recording.  Press a key combination (with or without
    modifiers) to capture it.  Press Escape to cancel.  Press Backspace with
    no modifiers to clear the binding.  The result is emitted as
    ``shortcut-set(accel_string)`` where *accel_string* uses the GSettings
    accelerator format (e.g. ``<Super>a``, ``<Control><Alt>t``).
    """

    __gsignals__ = {
        "shortcut-set": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._recording = False
        self._accel = ""

        self.add_css_class("flat")
        self.set_valign(Gtk.Align.CENTER)

        self._label = Gtk.Label()
        self.set_child(self._label)
        self._update_display()

        # Key controller for capturing shortcuts while recording.
        self._key_controller = Gtk.EventControllerKey()
        self._key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(self._key_controller)

        # Stop recording if focus leaves the button.
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("leave", self._on_focus_leave)
        self.add_controller(focus_controller)

        self.connect("clicked", self._on_clicked)

    # -- public API ----------------------------------------------------------

    def get_accel(self) -> str:
        return self._accel

    def set_accel(self, accel: str):
        self._accel = accel
        if not self._recording:
            self._update_display()

    # -- internals -----------------------------------------------------------

    def _update_display(self):
        if self._recording:
            self._label.set_markup(
                '<span style="italic" alpha="60%">Press a shortcut…</span>'
            )
            self.add_css_class("suggested-action")
        else:
            self.remove_css_class("suggested-action")
            if self._accel:
                # Use Gtk.accelerator_parse to get components, then render
                # a human-friendly label via Gtk.ShortcutLabel.
                display = self._pretty_label(self._accel)
                self._label.set_text(display)
            else:
                self._label.set_markup(
                    '<span alpha="50%">Disabled</span>'
                )

    @staticmethod
    def _pretty_label(accel: str) -> str:
        """Return a human-readable label for an accelerator string."""
        parsed, keyval, mods = Gtk.accelerator_parse(accel)
        if not parsed or keyval == 0:
            return accel
        return Gtk.accelerator_get_label(keyval, mods)

    def _start_recording(self):
        self._recording = True
        self._update_display()
        self.grab_focus()

    def _stop_recording(self):
        self._recording = False
        self._update_display()

    def _on_clicked(self, _btn):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _on_focus_leave(self, _ctrl):
        if self._recording:
            self._stop_recording()

    def _on_key_pressed(self, _ctrl, keyval, keycode, state):
        if not self._recording:
            return False

        # Mask out lock modifiers (Caps Lock, Num Lock, etc.)
        mods = state & Gtk.accelerator_get_default_mod_mask()

        # Escape cancels recording.
        if keyval == Gdk.KEY_Escape and not mods:
            self._stop_recording()
            return True

        # Backspace with no modifiers clears the binding.
        if keyval == Gdk.KEY_BackSpace and not mods:
            self._accel = ""
            self._stop_recording()
            self.emit("shortcut-set", "")
            return True

        # Ignore bare modifier presses — wait for a real key.
        if keyval in _MODIFIER_KEYVALS:
            return True

        # Build the accelerator string.
        accel = Gtk.accelerator_name(keyval, mods)
        if accel:
            self._accel = accel
            self._stop_recording()
            self.emit("shortcut-set", accel)
            return True

        return False



def _find_ancestor_scrolled_window(widget: Gtk.Widget) -> Gtk.ScrolledWindow | None:
    """Walk up the widget tree to find the nearest ScrolledWindow ancestor."""
    parent = widget.get_parent()
    while parent is not None:
        if isinstance(parent, Gtk.ScrolledWindow):
            return parent
        parent = parent.get_parent()
    return None


def _clear_box(box: Gtk.Box):
    child = box.get_first_child()
    while child is not None:
        next_child = child.get_next_sibling()
        box.remove(child)
        child = next_child


# Minimum GNOME Shell version for the bundled extension (ESM imports).
_MIN_GNOME_FOR_EXTENSION = 45


def _check_capability(
    ab: "AnimationBackend",
    capability: str,
    feature_label: str,
) -> Gtk.Box | None:
    """Return a status page if *capability* is unavailable, else ``None``.

    Checks both the GNOME Shell version floor and the runtime capability
    flags reported by the extension.  Returns ``None`` when the feature is
    usable so callers can just ``if page := ...: self.append(page); return``.
    """
    shell_ver = ab.get_detected_shell_version()
    if 0 < shell_ver < _MIN_GNOME_FOR_EXTENSION:
        return _build_status_page(
            icon_name="dialog-warning-symbolic",
            title=f"Requires GNOME {_MIN_GNOME_FOR_EXTENSION}+",
            description=(
                f"Your system is running GNOME {shell_ver}. "
                f"{feature_label} requires GNOME {_MIN_GNOME_FOR_EXTENSION} or later."
            ),
        )
    caps = ab.get_active_capabilities()
    if caps and not caps.get(capability, True):
        desc = (
            f"{feature_label} could not initialize on this version of GNOME Shell. "
            "This may be fixed in a future update."
        )
        if shell_ver > 0:
            desc = (
                f"{feature_label} is not available on GNOME {shell_ver}. "
                "This may be fixed in a future update."
            )
        return _build_status_page(
            icon_name="dialog-warning-symbolic",
            title=f"{feature_label} Unavailable",
            description=desc,
        )
    return None


def _build_status_page(icon_name: str, title: str, description: str) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_halign(Gtk.Align.CENTER)
    box.set_margin_top(36)
    box.set_margin_bottom(36)
    box.set_margin_start(24)
    box.set_margin_end(24)

    icon = Gtk.Image.new_from_icon_name(icon_name)
    icon.set_pixel_size(64)
    icon.add_css_class("dim-label")
    box.append(icon)

    title_label = Gtk.Label(label=title)
    title_label.add_css_class("title-1")
    box.append(title_label)

    desc_label = Gtk.Label(
        label=description,
        wrap=True,
        max_width_chars=50,
        justify=Gtk.Justification.CENTER,
    )
    desc_label.add_css_class("dim-label")
    box.append(desc_label)

    return box


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
            return tweak.unavailable_hint or "Not Installed"
        if not schema.has_key(tweak.key):
            return tweak.unavailable_hint or "Requires GNOME Update"
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


_unavailable_css_loaded = False


def _ensure_unavailable_css():
    global _unavailable_css_loaded
    if _unavailable_css_loaded:
        return
    _unavailable_css_loaded = True
    provider = Gtk.CssProvider()
    provider.load_from_string(
        ".unavailable-badge {"
        "  background: alpha(@warning_color, 0.15);"
        "  color: @warning_color;"
        "  border-radius: 99px;"
        "  padding: 2px 10px;"
        "  font-size: 0.8em;"
        "  font-weight: bold;"
        "}"
    )
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def _make_unavailable_badge() -> Gtk.Label:
    _ensure_unavailable_css()
    badge = Gtk.Label()
    badge.add_css_class("unavailable-badge")
    badge.set_valign(Gtk.Align.CENTER)
    badge.set_visible(False)
    return badge


class TweakRow(Adw.ActionRow):
    def __init__(self, tweak: Tweak, backend: SettingsBackend):
        super().__init__()
        self.tweak = tweak
        self.backend = backend
        self._updating = False

        self.set_title(tweak.name)

        self.set_subtitle(tweak.summary)

        # "Not Available" / "Requires GNOME Update" badge (hidden by default)
        self._unavailable_badge = _make_unavailable_badge()
        self.add_suffix(self._unavailable_badge)

        # Reset-to-default button (first suffix)
        self.reset_button = Gtk.Button(icon_name="edit-undo-symbolic")
        self.reset_button.add_css_class("flat")
        self.reset_button.set_valign(Gtk.Align.CENTER)
        self.reset_button.set_tooltip_text("Reset to default")
        self.reset_button.connect("clicked", self._on_reset_clicked)
        self.add_suffix(self.reset_button)

        control = self._build_control()
        if control is not None:
            self.add_suffix(control)

        # Copy command_hint button
        if tweak.command_hint is not None:
            copy_button = Gtk.Button(icon_name="edit-copy-symbolic")
            copy_button.add_css_class("flat")
            copy_button.set_valign(Gtk.Align.CENTER)
            copy_button.set_tooltip_text("Copy command")
            copy_button.connect("clicked", self._on_copy_command_clicked)
            self.add_suffix(copy_button)

        self.refresh()

    def _build_control(self) -> Gtk.Widget | None:
        if self.tweak.control in {"boolean", "boolean-inverted", "feature-toggle"}:
            self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            self.switch.connect("notify::active", self._on_switch_changed)
            return self.switch

        if self.tweak.control == "number":
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            box.set_valign(Gtk.Align.CENTER)

            self.spin = Gtk.SpinButton.new_with_range(
                self.tweak.min_value or 0,
                self.tweak.max_value or 100,
                self.tweak.step or 1,
            )
            self.spin.set_numeric(True)
            self.spin.set_valign(Gtk.Align.CENTER)
            self.spin.set_width_chars(6)
            self.spin.connect("value-changed", self._on_spin_changed)
            focus_ctrl = Gtk.EventControllerFocus()
            focus_ctrl.connect("leave", self._on_spin_focus_leave)
            self.spin.add_controller(focus_ctrl)
            box.append(self.spin)

            unit = _unit_for_key(self.tweak.key)
            if unit:
                unit_label = Gtk.Label(label=unit)
                unit_label.add_css_class("dim-label")
                unit_label.add_css_class("caption")
                box.append(unit_label)

            return box

        if self.tweak.control == "duration":
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            box.set_valign(Gtk.Align.CENTER)
            max_secs = int(self.tweak.max_value or 7200)
            self._dur_h = Gtk.SpinButton.new_with_range(0, max_secs // 3600, 1)
            self._dur_h.set_width_chars(2)
            self._dur_h.set_numeric(True)
            self._dur_h.connect("value-changed", self._on_duration_changed)
            self._dur_m = Gtk.SpinButton.new_with_range(0, 59, 1)
            self._dur_m.set_width_chars(2)
            self._dur_m.set_numeric(True)
            self._dur_m.connect("value-changed", self._on_duration_changed)
            self._dur_s = Gtk.SpinButton.new_with_range(0, 59, 5)
            self._dur_s.set_width_chars(2)
            self._dur_s.set_numeric(True)
            self._dur_s.connect("value-changed", self._on_duration_changed)
            for spin, label in [(self._dur_h, "h"), (self._dur_m, "m"), (self._dur_s, "s")]:
                box.append(spin)
                lbl = Gtk.Label(label=label)
                lbl.add_css_class("dim-label")
                lbl.add_css_class("caption")
                box.append(lbl)
            return box

        if self.tweak.control == "choice":
            labels = [choice.label for choice in self.tweak.choices]
            self.dropdown = Gtk.DropDown.new_from_strings(labels)
            self.dropdown.set_valign(Gtk.Align.CENTER)
            self.dropdown.connect("notify::selected", self._on_choice_changed)
            return self.dropdown

        if self.tweak.control == "keybinding":
            self.recorder = ShortcutRecorderButton()
            self.recorder.connect("shortcut-set", self._on_shortcut_set)
            return self.recorder

        if self.tweak.control == "font":
            dialog = Gtk.FontDialog()
            dialog.set_title(f"Choose {self.tweak.name}")
            self.font_button = Gtk.FontDialogButton(dialog=dialog)
            self.font_button.set_valign(Gtk.Align.CENTER)
            self.font_button.set_use_font(True)
            self.font_button.connect("notify::font-desc", self._on_font_changed)
            return self.font_button

        if self.tweak.control == "dimensions":
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            box.set_valign(Gtk.Align.CENTER)
            self._width_spin = Gtk.SpinButton.new_with_range(200, 7680, 10)
            self._width_spin.set_width_chars(5)
            self._width_spin.set_numeric(True)
            self._width_spin.connect("value-changed", self._on_dimensions_changed)
            box.append(self._width_spin)
            box.append(Gtk.Label(label="\u00d7"))  # × symbol
            self._height_spin = Gtk.SpinButton.new_with_range(200, 4320, 10)
            self._height_spin.set_width_chars(5)
            self._height_spin.set_numeric(True)
            self._height_spin.connect("value-changed", self._on_dimensions_changed)
            box.append(self._height_spin)
            px_label = Gtk.Label(label="px")
            px_label.add_css_class("dim-label")
            px_label.add_css_class("caption")
            box.append(px_label)
            return box

        if self.tweak.control == "time-of-day":
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_valign(Gtk.Align.CENTER)
            self._hour_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
            self._hour_spin.set_width_chars(2)
            self._hour_spin.set_numeric(True)
            self._hour_spin.connect("value-changed", self._on_time_changed)
            box.append(self._hour_spin)
            box.append(Gtk.Label(label=":"))
            self._min_spin = Gtk.SpinButton.new_with_range(0, 45, 15)
            self._min_spin.set_width_chars(2)
            self._min_spin.set_numeric(True)
            self._min_spin.connect("value-changed", self._on_time_changed)
            box.append(self._min_spin)
            return box

        if self.tweak.control == "theme":
            self._theme_names = _list_installed_themes(self.tweak.key)
            labels = self._theme_names if self._theme_names else ["(none found)"]
            self.dropdown = Gtk.DropDown.new_from_strings(labels)
            self.dropdown.set_valign(Gtk.Align.CENTER)
            self.dropdown.connect("notify::selected", self._on_theme_changed)
            return self.dropdown

        if self.tweak.control == "color":
            dialog = Gtk.ColorDialog()
            dialog.set_title(f"Choose {self.tweak.name}")
            dialog.set_with_alpha(False)
            self.color_button = Gtk.ColorDialogButton(dialog=dialog)
            self.color_button.set_valign(Gtk.Align.CENTER)
            self.color_button.connect("notify::rgba", self._on_color_changed)
            return self.color_button

        if self.tweak.control == "file":
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_valign(Gtk.Align.CENTER)
            self._file_label = Gtk.Label(label="None")
            self._file_label.set_ellipsize(Pango.EllipsizeMode.START)
            self._file_label.set_max_width_chars(24)
            self._file_label.add_css_class("dim-label")
            box.append(self._file_label)
            file_btn = Gtk.Button(icon_name="document-open-symbolic")
            file_btn.set_tooltip_text("Choose file")
            file_btn.connect("clicked", self._on_file_choose_clicked)
            box.append(file_btn)
            return box

        if self.tweak.control == "folder":
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_valign(Gtk.Align.CENTER)
            self._folder_label = Gtk.Label(label="None")
            self._folder_label.set_ellipsize(Pango.EllipsizeMode.START)
            self._folder_label.set_max_width_chars(24)
            self._folder_label.add_css_class("dim-label")
            box.append(self._folder_label)
            folder_btn = Gtk.Button(icon_name="folder-open-symbolic")
            folder_btn.set_tooltip_text("Choose folder")
            folder_btn.connect("clicked", self._on_folder_choose_clicked)
            box.append(folder_btn)
            return box

        if self.tweak.control in {"text", "text-list"}:
            self.entry = Gtk.Entry()
            self.entry.set_width_chars(18)
            self.entry.set_max_width_chars(24)
            self.entry.set_hexpand(False)
            self.entry.set_valign(Gtk.Align.CENTER)
            if self.tweak.control == "text-list":
                self.entry.set_placeholder_text("comma-separated")
            else:
                self.entry.set_placeholder_text("Enter value")
            self.entry.connect("activate", self._on_entry_commit)
            self.entry.connect("notify::has-focus", self._on_entry_focus_changed)
            return self.entry

        return None

    def refresh(self):
        available = self.backend.is_available(self.tweak)
        self.set_sensitive(available)

        if not available:
            self.reset_button.set_visible(False)
            reason = self.backend.unavailable_reason(self.tweak) or "Not Available"
            self._unavailable_badge.set_label(reason)
            self._unavailable_badge.set_visible(True)
            return

        self._unavailable_badge.set_visible(False)
        value = self.backend.read(self.tweak)

        # Show/hide reset button based on whether value differs from default
        self.reset_button.set_visible(not self.backend.is_default(self.tweak))

        self._updating = True
        try:
            if self.tweak.control in {"boolean", "boolean-inverted", "feature-toggle"}:
                active = bool(value)
                if self.tweak.control == "boolean-inverted":
                    active = not active
                self.switch.set_active(active)
            elif self.tweak.control == "number":
                self.spin.set_value(float(value or 0))
            elif self.tweak.control == "duration":
                total = int(value or 0)
                self._dur_h.set_value(total // 3600)
                self._dur_m.set_value((total % 3600) // 60)
                self._dur_s.set_value(total % 60)
            elif self.tweak.control == "choice":
                selected = 0
                for index, choice in enumerate(self.tweak.choices):
                    if choice.value == value:
                        selected = index
                        break
                self.dropdown.set_selected(selected)
            elif self.tweak.control == "dimensions":
                if isinstance(value, tuple) and len(value) == 2:
                    self._width_spin.set_value(value[0])
                    self._height_spin.set_value(value[1])
                elif isinstance(value, str) and "," in value:
                    parts = value.split(",")
                    self._width_spin.set_value(int(parts[0].strip()))
                    self._height_spin.set_value(int(parts[1].strip()))
            elif self.tweak.control == "time-of-day":
                hours = float(value or 0)
                h = int(hours)
                m = int(round((hours - h) * 60))
                self._hour_spin.set_value(h)
                self._min_spin.set_value(m)
            elif self.tweak.control == "theme":
                try:
                    idx = self._theme_names.index(str(value))
                except ValueError:
                    idx = 0
                self.dropdown.set_selected(idx)
            elif self.tweak.control == "font":
                desc = Pango.FontDescription.from_string(str(value) if value else "")
                self.font_button.set_font_desc(desc)
            elif self.tweak.control == "color":
                rgba = Gdk.RGBA()
                rgba.parse(str(value) if value else "#000000")
                self.color_button.set_rgba(rgba)
            elif self.tweak.control == "file":
                text = str(value) if value else ""
                if text.startswith("file://"):
                    self._file_label.set_text(Path(text[7:]).name or text)
                    self._file_label.set_tooltip_text(text)
                else:
                    self._file_label.set_text(text or "None")
            elif self.tweak.control == "folder":
                text = str(value) if value else ""
                self._folder_label.set_text(Path(text).name if text else "Default")
                self._folder_label.set_tooltip_text(text or "")
            elif self.tweak.control == "keybinding":
                self.recorder.set_accel(str(value) if value else "")
            elif self.tweak.control in {"text", "text-list"}:
                if self.entry.get_text() != str(value):
                    self.entry.set_text(str(value))
        finally:
            self._updating = False

    def _on_reset_clicked(self, _button: Gtk.Button):
        self.backend.reset(self.tweak)
        self.refresh()

    def _on_copy_command_clicked(self, _button: Gtk.Button):
        if self.tweak.command_hint is not None:
            clipboard = Gdk.Display.get_default().get_clipboard()
            clipboard.set(self.tweak.command_hint)

    def _on_font_changed(self, button: Gtk.FontDialogButton, _pspec):
        if self._updating:
            return
        desc = button.get_font_desc()
        if desc is None:
            return
        value = desc.to_string()
        if not self.backend.write(self.tweak, value):
            self.refresh()
            return
        self.refresh()

    def _on_dimensions_changed(self, _spin: Gtk.SpinButton):
        if self._updating:
            return
        w = int(self._width_spin.get_value())
        h = int(self._height_spin.get_value())
        # Write as the tuple-ii string format the backend expects
        if not self.backend.write(self.tweak, f"{w}, {h}"):
            self.refresh()
            return
        self.refresh()

    def _on_time_changed(self, _spin: Gtk.SpinButton):
        if self._updating:
            return
        h = int(self._hour_spin.get_value())
        m = int(self._min_spin.get_value())
        value = h + m / 60.0
        if not self.backend.write(self.tweak, value):
            self.refresh()
            return
        self.refresh()

    def _on_theme_changed(self, dropdown: Gtk.DropDown, _pspec):
        if self._updating:
            return
        idx = dropdown.get_selected()
        if idx >= len(self._theme_names):
            return
        value = self._theme_names[idx]
        if not self.backend.write(self.tweak, value):
            self.refresh()
            return
        self.refresh()

    def _on_color_changed(self, button: Gtk.ColorDialogButton, _pspec):
        if self._updating:
            return
        rgba = button.get_rgba()
        value = rgba.to_string()
        # GSettings stores colors as #RRGGBB hex; Gdk.RGBA.to_string() gives
        # "rgb(r,g,b)" in GTK 4, so convert to hex.
        r = int(round(rgba.red * 255))
        g = int(round(rgba.green * 255))
        b = int(round(rgba.blue * 255))
        value = f"#{r:02x}{g:02x}{b:02x}"
        if not self.backend.write(self.tweak, value):
            self.refresh()
            return
        self.refresh()

    def _on_file_choose_clicked(self, _button: Gtk.Button):
        dialog = Gtk.FileDialog()
        dialog.set_title(f"Choose {self.tweak.name}")
        img_filter = Gtk.FileFilter()
        img_filter.set_name("Images")
        img_filter.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(img_filter)
        all_filter = Gtk.FileFilter()
        all_filter.set_name("All files")
        all_filter.add_pattern("*")
        filters.append(all_filter)
        dialog.set_filters(filters)
        # Pre-select current file if possible
        current = self.backend.read(self.tweak)
        if current and str(current).startswith("file://"):
            try:
                dialog.set_initial_file(Gio.File.new_for_uri(str(current)))
            except Exception:
                pass
        dialog.open(self.get_root(), None, self._on_file_chosen)

    def _on_file_chosen(self, dialog: Gtk.FileDialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        uri = gfile.get_uri()
        if not self.backend.write(self.tweak, uri):
            self.refresh()
            return
        self.refresh()

    def _on_folder_choose_clicked(self, _button: Gtk.Button):
        dialog = Gtk.FileDialog()
        dialog.set_title(f"Choose {self.tweak.name}")
        current = self.backend.read(self.tweak)
        if current:
            try:
                dialog.set_initial_folder(Gio.File.new_for_path(str(current)))
            except Exception:
                pass
        dialog.select_folder(self.get_root(), None, self._on_folder_chosen)

    def _on_folder_chosen(self, dialog: Gtk.FileDialog, result):
        try:
            gfile = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path is None:
            return
        if not self.backend.write(self.tweak, path):
            self.refresh()
            return
        self.refresh()

    def _on_switch_changed(self, switch: Gtk.Switch, _pspec):
        if self._updating:
            return

        value = switch.get_active()
        if self.tweak.control == "boolean-inverted":
            value = not value

        if not self.backend.write(self.tweak, value):
            self.refresh()
            return
        self.refresh()

    def _on_spin_changed(self, spin: Gtk.SpinButton):
        if self._updating:
            return

        value = spin.get_value()
        if self.tweak.value_type in {"int", "uint32"}:
            value = int(round(value))

        if not self.backend.write(self.tweak, value):
            self.refresh()
            return
        self.refresh()

    def _on_duration_changed(self, _spin: Gtk.SpinButton):
        if self._updating:
            return
        h = int(self._dur_h.get_value())
        m = int(self._dur_m.get_value())
        s = int(self._dur_s.get_value())
        total = h * 3600 + m * 60 + s
        if not self.backend.write(self.tweak, total):
            self.refresh()
            return
        self.refresh()

    def _on_choice_changed(self, dropdown: Gtk.DropDown, _pspec):
        if self._updating:
            return

        selected = dropdown.get_selected()
        if selected >= len(self.tweak.choices):
            return

        value = self.tweak.choices[selected].value
        if not self.backend.write(self.tweak, value):
            self.refresh()
            return
        self.refresh()

    def _on_shortcut_set(self, _recorder, accel: str):
        if self._updating:
            return
        if not self.backend.write(self.tweak, accel):
            self.refresh()
            return
        self.refresh()

    def _on_spin_focus_leave(self, _ctrl):
        self.spin.update()
        val = self.spin.get_value()
        lo = self.tweak.min_value or 0
        hi = self.tweak.max_value or 100
        if val < lo or val > hi:
            self.spin.add_css_class("error")
            GLib.timeout_add(1500, self.spin.remove_css_class, "error")

    def _on_entry_commit(self, entry: Gtk.Entry):
        self._commit_entry(entry)

    def _on_entry_focus_changed(self, entry: Gtk.Entry, _pspec):
        if not entry.has_focus():
            self._commit_entry(entry)

    def _validate_entry(self, text: str) -> bool:
        if "picture-uri" in self.tweak.key:
            if text and not text.startswith("file://"):
                return False
        return True

    def _commit_entry(self, entry: Gtk.Entry):
        if self._updating:
            return

        text = entry.get_text()
        if not self._validate_entry(text):
            entry.add_css_class("error")
            return
        entry.remove_css_class("error")

        if not self.backend.write(self.tweak, text):
            self.refresh()
            return
        self.refresh()


class TextListRow(Adw.ExpanderRow):
    """Editable string list with per-item remove, add, and drag-to-reorder."""

    def __init__(self, tweak: Tweak, backend: SettingsBackend):
        super().__init__()
        self.tweak = tweak
        self.backend = backend
        self._items: list[str] = []
        self._sub_rows: list[Gtk.Widget] = []

        self.set_title(tweak.name)
        self.set_subtitle(tweak.summary)

        self._unavailable_badge = _make_unavailable_badge()
        self.add_suffix(self._unavailable_badge)

        self.count_label = Gtk.Label()
        self.count_label.add_css_class("dim-label")
        self.count_label.add_css_class("caption")
        self.add_suffix(self.count_label)

        self.refresh()

    def refresh(self):
        available = self.backend.is_available(self.tweak)
        self.set_sensitive(available)
        if not available:
            reason = self.backend.unavailable_reason(self.tweak) or "Not Available"
            self._unavailable_badge.set_label(reason)
            self._unavailable_badge.set_visible(True)
            self.count_label.set_visible(False)
            return
        self._unavailable_badge.set_visible(False)
        self.count_label.set_visible(True)
        self._items = self._read_items()
        self.count_label.set_text(f"{len(self._items)} items")
        self._rebuild_rows()

    def _read_items(self) -> list[str]:
        if not self.backend.is_available(self.tweak):
            return []
        settings = self.backend._get_settings(self.tweak.schema)
        if settings is None:
            return []
        value = settings.get_value(self.tweak.key).unpack()
        if isinstance(value, (list, tuple)):
            return [str(v) if not isinstance(v, str) else v for v in value]
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return []

    def _write_items(self):
        if not self.backend.is_available(self.tweak):
            return
        settings = self.backend._get_settings(self.tweak.schema)
        if settings is None:
            return
        default = settings.get_default_value(self.tweak.key)
        if default is None:
            return
        type_string = default.get_type_string()
        try:
            self.backend.suppress(self.tweak.schema, self.tweak.key)
            if type_string == "s":
                settings.set_value(
                    self.tweak.key, GLib.Variant("s", ",".join(self._items))
                )
            else:
                settings.set_value(
                    self.tweak.key, GLib.Variant(type_string, self._items)
                )
        except Exception:
            pass

    def _rebuild_rows(self):
        for row in self._sub_rows:
            self.remove(row)
        self._sub_rows.clear()

        for i, item in enumerate(self._items):
            row = self._build_item_row(i, item)
            self.add_row(row)
            self._sub_rows.append(row)

        add_row = self._build_add_row()
        self.add_row(add_row)
        self._sub_rows.append(add_row)

    def _build_item_row(self, index: int, item: str) -> Adw.ActionRow:
        row = Adw.ActionRow()
        row.set_use_markup(False)
        row.set_title(item)

        remove_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        remove_btn.add_css_class("flat")
        remove_btn.set_valign(Gtk.Align.CENTER)
        remove_btn.connect("clicked", self._on_remove, index)
        row.add_suffix(remove_btn)

        handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle.add_css_class("dim-label")
        row.add_prefix(handle)

        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_drag_prepare, index)
        row.add_controller(source)

        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        target.connect("drop", self._on_drop, index)
        row.add_controller(target)

        return row

    def _build_add_row(self) -> Gtk.ListBoxRow:
        lbr = Gtk.ListBoxRow(activatable=False, selectable=False)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(16)
        box.set_margin_end(8)

        self._add_entry = Gtk.Entry()
        self._add_entry.set_placeholder_text("org.example.App.desktop")
        self._add_entry.set_hexpand(True)
        self._add_entry.connect("activate", self._on_add)
        box.append(self._add_entry)

        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.set_valign(Gtk.Align.CENTER)
        add_btn.connect("clicked", self._on_add)
        box.append(add_btn)

        lbr.set_child(box)
        return lbr

    def _on_remove(self, _button: Gtk.Button, index: int):
        if 0 <= index < len(self._items):
            self._items.pop(index)
            self._write_items()
            self.count_label.set_text(f"{len(self._items)} items")
            self._rebuild_rows()

    def _on_add(self, _widget: Gtk.Widget):
        text = self._add_entry.get_text().strip()
        if not text:
            return
        if text in self._items:
            self._add_entry.add_css_class("error")
            return
        self._add_entry.remove_css_class("error")
        self._items.append(text)
        self._write_items()
        self._add_entry.set_text("")
        self.count_label.set_text(f"{len(self._items)} items")
        self._rebuild_rows()

    def _on_drag_prepare(self, _source, _x, _y, index: int):
        return Gdk.ContentProvider.new_for_value(str(index))

    def _on_drop(self, _target, value, _x, _y, dest_index: int) -> bool:
        try:
            src_index = int(value)
        except (ValueError, TypeError):
            return False
        if src_index == dest_index or not (0 <= src_index < len(self._items)):
            return True
        item = self._items.pop(src_index)
        self._items.insert(dest_index, item)
        self._write_items()
        self.count_label.set_text(f"{len(self._items)} items")
        self._rebuild_rows()
        return True


class ExtensionListRow(Adw.ExpanderRow):
    """Extension manager with per-extension enable/disable toggles and uninstall."""

    _USER_EXT_DIR = Path.home() / ".local" / "share" / "gnome-shell" / "extensions"
    _SYSTEM_EXT_DIR = Path("/usr") / "share" / "gnome-shell" / "extensions"

    def __init__(self, tweak: Tweak, backend: SettingsBackend):
        super().__init__()
        self.tweak = tweak
        self.backend = backend
        self._sub_rows: list[Gtk.Widget] = []

        self.set_title(tweak.name)
        self.set_subtitle(tweak.summary)

        self._unavailable_badge = _make_unavailable_badge()
        self.add_suffix(self._unavailable_badge)

        self.count_label = Gtk.Label()
        self.count_label.add_css_class("dim-label")
        self.count_label.add_css_class("caption")
        self.add_suffix(self.count_label)

        self.refresh()

    def refresh(self):
        available = self.backend.is_available(self.tweak)
        self.set_sensitive(available)
        if not available:
            reason = self.backend.unavailable_reason(self.tweak) or "Not Available"
            self._unavailable_badge.set_label(reason)
            self._unavailable_badge.set_visible(True)
            self.count_label.set_visible(False)
            return
        self._unavailable_badge.set_visible(False)
        self.count_label.set_visible(True)

        self._extensions = self._discover_extensions()
        self._enabled = self._get_enabled()
        self.count_label.set_text(f"{len(self._extensions)} installed")
        self._rebuild_rows()

    def _discover_extensions(self) -> list[tuple[str, str, bool]]:
        """Return [(uuid, display_name, is_user), ...] for installed extensions."""
        import json as _json

        extensions: list[tuple[str, str, bool]] = []
        for ext_dir, is_user in [
            (self._USER_EXT_DIR, True),
            (self._SYSTEM_EXT_DIR, False),
        ]:
            if not ext_dir.is_dir():
                continue
            for entry in sorted(ext_dir.iterdir()):
                if not entry.is_dir():
                    continue
                metadata_file = entry / "metadata.json"
                if not metadata_file.exists():
                    continue
                try:
                    meta = _json.loads(metadata_file.read_text())
                    name = meta.get("name", entry.name)
                    uuid = meta.get("uuid", entry.name)
                except Exception:
                    name = entry.name
                    uuid = entry.name
                extensions.append((uuid, name, is_user))
        return extensions

    def _get_enabled(self) -> set[str]:
        settings = self.backend._get_settings(self.tweak.schema)
        if settings is None:
            return set()
        value = settings.get_value(self.tweak.key).unpack()
        if isinstance(value, (list, tuple)):
            return set(value)
        return set()

    def _set_enabled(self, enabled: set[str]):
        settings = self.backend._get_settings(self.tweak.schema)
        if settings is None:
            return
        self.backend.suppress(self.tweak.schema, self.tweak.key)
        settings.set_value(self.tweak.key, GLib.Variant("as", sorted(enabled)))

    def _rebuild_rows(self):
        for row in self._sub_rows:
            self.remove(row)
        self._sub_rows.clear()

        for uuid, name, is_user in self._extensions:
            row = self._build_ext_row(uuid, name, is_user)
            self.add_row(row)
            self._sub_rows.append(row)

    def _build_ext_row(self, uuid: str, name: str, is_user: bool) -> Adw.ActionRow:
        row = Adw.ActionRow()
        row.set_use_markup(False)
        row.set_title(name)
        row.set_subtitle(uuid)

        toggle = Gtk.Switch()
        toggle.set_valign(Gtk.Align.CENTER)
        toggle.set_active(uuid in self._enabled)
        toggle.connect("notify::active", self._on_toggle, uuid)
        row.add_suffix(toggle)
        row.set_activatable_widget(toggle)

        if is_user:
            uninstall_btn = Gtk.Button(icon_name="user-trash-symbolic")
            uninstall_btn.add_css_class("flat")
            uninstall_btn.set_valign(Gtk.Align.CENTER)
            uninstall_btn.connect(
                "clicked", self._on_uninstall_clicked, uuid, name
            )
            row.add_suffix(uninstall_btn)

        return row

    def _on_toggle(self, switch: Gtk.Switch, _pspec, uuid: str):
        if switch.get_active():
            self._enabled.add(uuid)
        else:
            self._enabled.discard(uuid)
        self._set_enabled(self._enabled)

    def _on_uninstall_clicked(self, _button: Gtk.Button, uuid: str, name: str):
        dialog = Adw.AlertDialog(
            heading="Uninstall Extension",
            body=f"Are you sure you want to delete the {name} extension?",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("uninstall", "Uninstall")
        dialog.set_response_appearance(
            "uninstall", Adw.ResponseAppearance.DESTRUCTIVE
        )
        dialog.connect("response", self._on_uninstall_response, uuid)
        dialog.present(self.get_root())

    def _on_uninstall_response(self, _dialog, response: str, uuid: str):
        if response != "uninstall":
            return
        import shutil

        ext_dir = self._USER_EXT_DIR / uuid
        if ext_dir.is_dir():
            shutil.rmtree(ext_dir)
        self._enabled.discard(uuid)
        self._set_enabled(self._enabled)
        self.refresh()


def _build_runtime_group(
    backend: AnimationBackend,
    on_install: Callable[[], None],
    on_enable_changed: Callable[[bool], None],
) -> Adw.PreferencesGroup:
    """Build the shared runtime install/enable/status group used by multiple sections."""
    group = Adw.PreferencesGroup(
        title="Runtime",
        description="First-party GNOME Shell runtime bundled with More Tweaks.",
    )

    # Status row
    status_row = Adw.ActionRow(title="Bundled shell runtime")
    status_row.set_subtitle(backend.status_text)
    status_label = Gtk.Label(label="Installed" if backend.available else "Not installed")
    status_label.add_css_class("dim-label")
    status_row.add_suffix(status_label)
    group.add(status_row)

    # Install/update button
    install_row = Adw.ActionRow(title="Install or update runtime")
    install_row.set_subtitle(
        "Copies the bundled More Tweaks shell runtime into your local GNOME Shell extensions folder."
    )
    install_button = Gtk.Button(label="Update" if backend.available else "Install")
    install_button.add_css_class("pill")
    install_button.set_valign(Gtk.Align.CENTER)
    install_button.connect("clicked", lambda _btn: on_install())
    install_row.add_suffix(install_button)
    group.add(install_row)

    # Enable switch
    switch_row = Adw.ActionRow(title="Enable bundled runtime")
    switch_row.set_subtitle(
        "Turn on the app-owned GNOME Shell runtime."
    )
    switch = Gtk.Switch(valign=Gtk.Align.CENTER)
    switch.set_active(backend.runtime_enabled)
    switch.connect("notify::active", lambda sw, _pspec: on_enable_changed(sw.get_active()))
    switch_row.add_suffix(switch)
    group.add(switch_row)

    # Runtime state row
    runtime_row = Adw.ActionRow(title="Bundled runtime state")
    if backend.runtime_error:
        runtime_row.set_subtitle(
            "GNOME Shell reported an error while loading the bundled More Tweaks runtime."
        )
        runtime_label = Gtk.Label(label="Runtime error")
    elif backend.needs_shell_restart:
        runtime_row.set_subtitle(
            "The runtime files are installed, but GNOME Shell has not detected them yet. "
            "Log out and log back in for the extension to be recognized."
        )
        runtime_label = Gtk.Label(label="Log out required")
    elif backend.available and backend.extension_state is None:
        runtime_row.set_subtitle(
            "The runtime files are installed, but GNOME Shell has not picked them up yet. "
            "A logout/login may be needed."
        )
        runtime_label = Gtk.Label(label="Restart shell")
    elif not backend.runtime_enabled:
        runtime_row.set_subtitle(
            "The bundled runtime is installed but disabled."
        )
        runtime_label = Gtk.Label(label="Disabled")
    else:
        runtime_row.set_subtitle(
            "The bundled More Tweaks runtime is active inside GNOME Shell."
        )
        runtime_label = Gtk.Label(label="Running")
    runtime_label.add_css_class("dim-label")
    runtime_row.add_suffix(runtime_label)
    group.add(runtime_row)

    # Error detail row
    if backend.runtime_error:
        error_row = Adw.ActionRow(title="Reported shell error")
        error_row.set_subtitle(backend.runtime_error)
        group.add(error_row)

    return group


def _pretty_panel_name(item_id: str) -> str:
    """Return a human-readable label for a panel statusArea id."""
    import re
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", item_id)
    spaced = spaced.replace("_", " ").replace("-", " ")
    return spaced.title()


class PanelZoneList(Gtk.ListBox):
    """A single top-bar zone (left/center/right) with drag-to-reorder items."""

    def __init__(self, zone_name: str, items: list[str],
                 on_change: Callable[[], None]):
        super().__init__(selection_mode=Gtk.SelectionMode.NONE)
        self.zone_name = zone_name
        self._items = items
        self._on_change = on_change
        self.add_css_class("boxed-list")
        self._rebuild_rows()

    @property
    def items(self) -> list[str]:
        return list(self._items)

    def _rebuild_rows(self):
        while True:
            row = self.get_row_at_index(0)
            if row is None:
                break
            self.remove(row)
        for index, item_id in enumerate(self._items):
            self.append(self._build_item_row(index, item_id))

    def _build_item_row(self, index: int, item_id: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(10)
        content.set_margin_end(10)

        handle = Gtk.Image.new_from_icon_name("list-drag-handle-symbolic")
        handle.add_css_class("dim-label")
        content.append(handle)

        label = Gtk.Label(label=_pretty_panel_name(item_id), xalign=0)
        label.set_hexpand(True)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        label.set_max_width_chars(20)
        content.append(label)

        row.set_child(content)

        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_drag_prepare, index)
        row.add_controller(source)

        target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        target.connect("drop", self._on_drop, index)
        row.add_controller(target)

        return row

    def _on_drag_prepare(self, _source, _x, _y, index: int):
        return Gdk.ContentProvider.new_for_value(f"{self.zone_name}:{index}")

    def _on_drop(self, _target, value, _x, _y, dest_index: int) -> bool:
        try:
            src_zone, src_idx_str = value.split(":", 1)
            src_index = int(src_idx_str)
        except (ValueError, TypeError):
            return False

        if src_zone == self.zone_name:
            # Intra-zone reorder
            if src_index == dest_index or not (0 <= src_index < len(self._items)):
                return True
            item = self._items.pop(src_index)
            self._items.insert(dest_index, item)
        else:
            # Cross-zone drop — find the source zone list via parent
            section = self.get_parent()
            while section is not None and not isinstance(section, PanelReorderSection):
                section = section.get_parent()
            if section is None:
                return False
            src_list = section.get_zone_list(src_zone)
            if src_list is None or not (0 <= src_index < len(src_list._items)):
                return False
            item = src_list._items.pop(src_index)
            self._items.insert(dest_index, item)
            src_list._rebuild_rows()

        self._rebuild_rows()
        self._on_change()
        return True


class PanelReorderSection(Gtk.Box):
    """Panel item reorder widget for the Top Bar category."""

    def __init__(self, backend: AnimationBackend):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._backend = backend
        self._zone_lists: dict[str, PanelZoneList] = {}

    def get_zone_list(self, zone_name: str) -> PanelZoneList | None:
        return self._zone_lists.get(zone_name)

    def refresh(self):
        _clear_box(self)
        self._zone_lists.clear()

        saved = self._backend.get_panel_layout()
        available = self._backend.get_panel_items_available()

        if not saved:
            # No custom layout saved — show what the extension actually sees.
            layout = {k: list(v) for k, v in available.items()}
        elif available:
            # Merge: keep saved ordering but reconcile with reality.
            # Drop saved items that no longer exist on the panel and
            # append newly-appeared items to their actual zone.
            all_avail = {item for items in available.values() for item in items}
            layout: dict[str, list[str]] = {}
            seen: set[str] = set()
            for zone in ("left", "center", "right"):
                kept = [i for i in saved.get(zone, []) if i in all_avail]
                seen.update(kept)
                layout[zone] = kept
            for zone in ("left", "center", "right"):
                for item in available.get(zone, []):
                    if item not in seen:
                        layout[zone].append(item)
                        seen.add(item)
        else:
            layout = {k: list(v) for k, v in saved.items()}

        title = Gtk.Label(label="Panel Layout", xalign=0)
        title.add_css_class("title-4")
        self.append(title)

        desc = Gtk.Label(
            label="Drag items to reorder within or between zones.",
            xalign=0, wrap=True,
        )
        desc.add_css_class("dim-label")
        self.append(desc)

        zones_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        zones_box.set_homogeneous(True)

        for zone_name, zone_title in [("left", "Left"), ("center", "Center"), ("right", "Right")]:
            zone_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            zone_label = Gtk.Label(label=zone_title, xalign=0)
            zone_label.add_css_class("heading")
            zone_box.append(zone_label)

            items = list(layout.get(zone_name, []))
            zone_list = PanelZoneList(zone_name, items, self._on_layout_changed)
            self._zone_lists[zone_name] = zone_list
            zone_box.append(zone_list)

            # Drop target on the zone box itself for drops into empty zones
            zone_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
            zone_target.connect("drop", self._on_zone_drop, zone_name)
            zone_box.add_controller(zone_target)

            zones_box.append(zone_box)

        self.append(zones_box)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_margin_top(8)

        reset_btn = Gtk.Button(label="Reset to Default")
        reset_btn.add_css_class("pill")
        reset_btn.connect("clicked", self._on_reset)
        button_box.append(reset_btn)

        self.append(button_box)

    def _on_zone_drop(self, _target, value, _x, _y, dest_zone: str) -> bool:
        try:
            src_zone, src_idx_str = value.split(":", 1)
            src_index = int(src_idx_str)
        except (ValueError, TypeError):
            return False

        src_list = self._zone_lists.get(src_zone)
        dest_list = self._zone_lists.get(dest_zone)
        if src_list is None or dest_list is None:
            return False
        if not (0 <= src_index < len(src_list._items)):
            return False

        item = src_list._items.pop(src_index)
        dest_list._items.append(item)
        src_list._rebuild_rows()
        dest_list._rebuild_rows()
        self._on_layout_changed()
        return True

    def _on_layout_changed(self):
        layout = {}
        for zone_name, zone_list in self._zone_lists.items():
            layout[zone_name] = zone_list.items
        self._backend.set_panel_layout(layout)

    def _on_reset(self, _button):
        self._backend.set_panel_layout({})
        self.refresh()


class _ScrollPreservingSection(Gtk.Box):
    """Base class for sections that rebuild their widget tree on refresh.

    Saves and restores the nearest ancestor ScrolledWindow's scroll
    position around each rebuild so the viewport doesn't jump to the top.
    """

    def _save_scroll(self) -> tuple[Gtk.ScrolledWindow | None, float]:
        sw = _find_ancestor_scrolled_window(self)
        return (sw, sw.get_vadjustment().get_value()) if sw else (None, 0.0)

    @staticmethod
    def _restore_scroll(sw: Gtk.ScrolledWindow | None, pos: float):
        if sw is None:
            return
        GLib.idle_add(lambda: (sw.get_vadjustment().set_value(pos), False)[-1])


class TopBarSection(_ScrollPreservingSection):
    """Hybrid section for the Top Bar category: standard tweaks + panel reorder."""

    def __init__(self, notify: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.set_margin_bottom(48)
        self._notify = notify
        self._backend = SettingsBackend()
        self._animation_backend = AnimationBackend()
        self._tweak_rows: list[TweakRow | TextListRow] = []
        self._panel_section = PanelReorderSection(self._animation_backend)
        self._topbar_widgets: dict[str, Gtk.Widget] = {}
        self._updating_topbar = False

    def _toast(self, message: str):
        if self._notify:
            self._notify(message)

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

        # Standard GSettings tweaks — always shown
        tweaks_group = Adw.PreferencesGroup(
            title="Top Bar Settings",
            description="Clock, battery, and hot corner tweaks.",
        )
        tweaks = filter_tweaks("", "topbar")
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

        # Runtime management — same controls as Animations
        runtime_group = _build_runtime_group(
            self._animation_backend,
            on_install=self._on_install_runtime,
            on_enable_changed=self._on_enable_runtime,
        )
        self.append(runtime_group)

        # Panel reorder — requires the bundled shell extension
        if self._animation_backend.needs_shell_restart:
            self.append(_build_status_page(
                icon_name="system-log-out-symbolic",
                title="Log Out Required",
                description=(
                    "The bundled shell runtime has been installed, but GNOME Shell "
                    "needs to restart to detect it.\n\n"
                    "On Wayland, log out and log back in. "
                    "Panel reordering will become available after that."
                ),
            ))
            return

        if not self._animation_backend.available:
            self.append(_build_status_page(
                icon_name="application-x-addon-symbolic",
                title="Shell Runtime Not Installed",
                description=(
                    "Panel reordering requires the bundled GNOME Shell extension.\n\n"
                    "Use the Install button above to set it up. "
                    "Panel reordering will become available once it's running."
                ),
            ))
            return

        # Capability checks for panel layout and top bar overrides
        panel_blocked = _check_capability(
            self._animation_backend, "panelLayout", "Panel Layout Customization")
        topbar_blocked = _check_capability(
            self._animation_backend, "topBar", "Top Bar Overrides")

        if panel_blocked is None:
            if not self._animation_backend.get_panel_items_available():
                self.append(_build_status_page(
                    icon_name="system-log-out-symbolic",
                    title="Log Out Required",
                    description=(
                        "The shell extension needs to be restarted to report "
                        "your current top bar items.\n\n"
                        "On Wayland, log out and log back in. "
                        "Panel reordering will become available after that."
                    ),
                ))
            else:
                self._panel_section.refresh()
                self.append(self._panel_section)
        else:
            self.append(panel_blocked)

        # Top bar overrides — extension-backed appearance tweaks
        if topbar_blocked is None:
            self._build_topbar_overrides()
        else:
            self.append(topbar_blocked)

    def _build_topbar_overrides(self):
        ab = self._animation_backend
        self._topbar_widgets.clear()
        self._updating_topbar = True

        enabled = ab._get_boolean("topbar-overrides-enabled", default=False)

        group = Adw.PreferencesGroup(
            title="Top Bar Overrides",
            description=(
                "Customise Activities button, clock format, and panel spacing. "
                "Requires the bundled shell extension."
            ),
        )

        # Master switch
        enable_row = Adw.ActionRow(
            title="Enable top bar overrides",
            subtitle="Apply custom appearance tweaks to the GNOME top bar.",
        )
        enable_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        enable_switch.set_active(enabled)
        enable_switch.connect("notify::active", self._on_topbar_master_switch)
        enable_row.add_suffix(enable_switch)
        group.add(enable_row)
        self._topbar_widgets["_master"] = enable_switch

        # Activities button visible
        act_vis_row = Adw.ActionRow(
            title="Show Activities button",
            subtitle="Hide or show the Activities button in the top-left corner.",
        )
        act_vis_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        act_vis_switch.set_active(ab._get_boolean("activities-button-visible", default=True))
        act_vis_switch.set_sensitive(enabled)
        act_vis_switch.connect("notify::active", self._on_topbar_bool_changed,
                               "activities-button-visible")
        act_vis_row.add_suffix(act_vis_switch)
        group.add(act_vis_row)
        self._topbar_widgets["activities-button-visible"] = act_vis_switch

        self.append(group)

        # Clock format group
        clock_group = Adw.PreferencesGroup(title="Custom Clock Format")

        clock_enable_row = Adw.ActionRow(
            title="Use custom clock format",
            subtitle="Override the built-in 12h/24h clock with a custom format string.",
        )
        clock_enable_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        clock_enable_switch.set_active(
            ab._get_boolean("clock-custom-format-enabled", default=False))
        clock_enable_switch.set_sensitive(enabled)
        clock_enable_switch.connect("notify::active", self._on_topbar_bool_changed,
                                    "clock-custom-format-enabled")
        clock_enable_row.add_suffix(clock_enable_switch)
        clock_group.add(clock_enable_row)
        self._topbar_widgets["clock-custom-format-enabled"] = clock_enable_switch

        clock_fmt_row = Adw.ActionRow(
            title="Format string",
            subtitle="%H:%M:%S = 24h with seconds, %I:%M %p = 12h AM/PM, %a = weekday",
        )
        clock_fmt_entry = Gtk.Entry(
            valign=Gtk.Align.CENTER,
            placeholder_text="%a %b %e  %H:%M:%S",
            width_chars=22,
        )
        clock_fmt_entry.set_text(
            ab._get_string("clock-custom-format", default="%a %b %e  %H:%M:%S"))
        clock_fmt_entry.set_sensitive(enabled)
        clock_fmt_entry.connect("changed", self._on_topbar_text_changed,
                                "clock-custom-format")
        clock_fmt_row.add_suffix(clock_fmt_entry)
        clock_group.add(clock_fmt_row)
        self._topbar_widgets["clock-custom-format"] = clock_fmt_entry

        self.append(clock_group)

        # Panel spacing group
        spacing_group = Adw.PreferencesGroup(title="Panel Spacing")

        spacing_row = Adw.ActionRow(
            title="Indicator spacing",
            subtitle="Horizontal padding between top bar items in pixels (−1 = default).",
        )
        spacing_spin = Gtk.SpinButton.new_with_range(-1, 24, 1)
        spacing_spin.set_valign(Gtk.Align.CENTER)
        spacing_spin.set_value(ab._get_int("panel-icon-spacing", default=-1))
        spacing_spin.set_sensitive(enabled)
        spacing_spin.connect("value-changed", self._on_topbar_int_changed,
                             "panel-icon-spacing")
        spacing_row.add_suffix(spacing_spin)
        spacing_group.add(spacing_row)
        self._topbar_widgets["panel-icon-spacing"] = spacing_spin

        self.append(spacing_group)

        # Panel icon color group
        color_group = Adw.PreferencesGroup(title="Panel Icon Color")

        color_row = Adw.ActionRow(
            title="Icon color",
            subtitle="Override the color of all top bar icons and text.",
        )
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        color_box.set_valign(Gtk.Align.CENTER)

        color_dialog = Gtk.ColorDialog()
        color_dialog.set_title("Panel Icon Color")
        color_dialog.set_with_alpha(False)
        self._topbar_color_button = Gtk.ColorDialogButton(dialog=color_dialog)
        current_color = ab._get_string("panel-icon-color", default="")
        if current_color:
            rgba = Gdk.RGBA()
            rgba.parse(current_color)
            self._topbar_color_button.set_rgba(rgba)
        self._topbar_color_button.set_sensitive(enabled)
        self._topbar_color_button.connect("notify::rgba",
                                          self._on_topbar_color_changed)
        color_box.append(self._topbar_color_button)

        reset_color_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        reset_color_btn.add_css_class("flat")
        reset_color_btn.set_tooltip_text("Reset to default theme color")
        reset_color_btn.set_sensitive(enabled)
        reset_color_btn.connect("clicked", self._on_topbar_color_reset)
        color_box.append(reset_color_btn)

        color_row.add_suffix(color_box)
        color_group.add(color_row)
        self._topbar_widgets["panel-icon-color"] = self._topbar_color_button
        self._topbar_widgets["panel-icon-color-reset"] = reset_color_btn

        self.append(color_group)
        self._updating_topbar = False

    def _on_topbar_master_switch(self, switch: Gtk.Switch, _pspec):
        active = switch.get_active()
        self._animation_backend._set_boolean("topbar-overrides-enabled", active)
        for key, widget in self._topbar_widgets.items():
            if key == "_master":
                continue
            widget.set_sensitive(active)

    def _on_topbar_bool_changed(self, switch: Gtk.Switch, _pspec, key: str):
        if self._updating_topbar:
            return
        self._animation_backend._set_boolean(key, switch.get_active())

    def _on_topbar_text_changed(self, entry: Gtk.Entry, key: str):
        if self._updating_topbar:
            return
        self._animation_backend._set_string(key, entry.get_text())

    def _on_topbar_int_changed(self, spin: Gtk.SpinButton, key: str):
        if self._updating_topbar:
            return
        self._animation_backend._set_int(key, int(spin.get_value()))

    def _on_topbar_color_changed(self, button: Gtk.ColorDialogButton, _pspec):
        if self._updating_topbar:
            return
        rgba = button.get_rgba()
        r = int(round(rgba.red * 255))
        g = int(round(rgba.green * 255))
        b = int(round(rgba.blue * 255))
        self._animation_backend._set_string("panel-icon-color", f"#{r:02x}{g:02x}{b:02x}")

    def _on_topbar_color_reset(self, _button: Gtk.Button):
        self._animation_backend._set_string("panel-icon-color", "")
        # Reset the color button to white as a visual indicator
        rgba = Gdk.RGBA()
        rgba.parse("#ffffff")
        self._topbar_color_button.set_rgba(rgba)

    def _on_install_runtime(self):
        if not self._animation_backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        self._toast("Bundled More Tweaks runtime installed")
        self.refresh()

    def _on_enable_runtime(self, enabled: bool):
        if enabled and not self._animation_backend.available and not self._animation_backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        success = self._animation_backend.enable_runtime() if enabled else self._animation_backend.disable_runtime()
        self._toast(
            "Bundled More Tweaks runtime enabled"
            if success and enabled
            else "Bundled More Tweaks runtime disabled"
        )
        self.refresh()



# ── Tiling & Snapping section ──────────────────────────────────────────


class TilingSection(_ScrollPreservingSection):
    """Hybrid section for the Tiling & Snapping category:
    standard GSettings tweaks + extension-backed tile gap controls."""

    def __init__(self, notify: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.set_margin_bottom(48)
        self._notify = notify
        self._backend = SettingsBackend()
        self._animation_backend = AnimationBackend()
        self._tweak_rows: list[TweakRow | TextListRow] = []
        self._grid_widgets: dict[str, Gtk.Widget] = {}
        self._preview_widgets: dict[str, Gtk.Widget] = {}
        self._gap_widgets: dict[str, Gtk.Widget] = {}
        self._updating_gaps = False

    def _toast(self, message: str):
        if self._notify:
            self._notify(message)

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
        self._grid_widgets.clear()
        self._preview_widgets.clear()
        self._gap_widgets.clear()
        self._updating_gaps = True

        # Standard GSettings tweaks — always shown
        tweaks_group = Adw.PreferencesGroup(
            title="Tiling &amp; Snapping Settings",
            description="Edge snapping behavior and keyboard tile shortcuts.",
        )
        tweaks = filter_tweaks("", "tiling")
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

        # Runtime management — install / enable the shell extension
        runtime_group = _build_runtime_group(
            self._animation_backend,
            on_install=self._on_install_runtime,
            on_enable_changed=self._on_enable_runtime,
        )
        self.append(runtime_group)

        if self._animation_backend.needs_shell_restart:
            self.append(_build_status_page(
                icon_name="system-log-out-symbolic",
                title="Log Out Required",
                description=(
                    "The bundled shell runtime has been installed, but GNOME Shell "
                    "needs to restart to detect it.\n\n"
                    "On Wayland, log out and log back in. "
                    "Tile grid and gap controls will become available after that."
                ),
            ))
            self._updating_gaps = False
            return

        if not self._animation_backend.available:
            self.append(_build_status_page(
                icon_name="application-x-addon-symbolic",
                title="Shell Runtime Not Installed",
                description=(
                    "Tile grid and gaps require the bundled GNOME Shell extension.\n\n"
                    "Use the Install button above to set it up."
                ),
            ))
            self._updating_gaps = False
            return

        # Capability checks for tiling features
        grid_blocked = _check_capability(
            self._animation_backend, "tileGrid", "Tile Grid & Snap Preview")
        gaps_blocked = _check_capability(
            self._animation_backend, "tileGaps", "Tile Gaps")

        # Extension-backed tiling controls
        if grid_blocked is None:
            self._build_tile_grid_group()
            self._build_tile_preview_group()
        else:
            self.append(grid_blocked)

        if gaps_blocked is None:
            self._build_tile_gap_group()
        else:
            self.append(gaps_blocked)

        self._updating_gaps = False

    def _build_tile_gap_group(self):
        ab = self._animation_backend
        enabled = ab._get_boolean("tile-gaps-enabled", default=False)

        group = Adw.PreferencesGroup(
            title="Tile Gaps",
            description=(
                "Add pixel spacing between tiled windows and screen edges. "
                "Requires the bundled shell extension."
            ),
        )

        # Master switch
        enable_row = Adw.ActionRow(
            title="Enable tile gaps",
            subtitle="Add gaps around half-tiled windows.",
        )
        enable_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        enable_switch.set_active(enabled)
        enable_switch.connect("notify::active", self._on_gap_master_switch)
        enable_row.add_suffix(enable_switch)
        group.add(enable_row)
        self._gap_widgets["_master"] = enable_switch

        # Inner gap
        inner_row = Adw.ActionRow(
            title="Inner gap",
            subtitle="Pixel spacing between adjacent tiled windows.",
        )
        inner_spin = Gtk.SpinButton.new_with_range(0, 64, 1)
        inner_spin.set_valign(Gtk.Align.CENTER)
        inner_spin.set_value(ab._get_int("tile-gap-inner", default=8))
        inner_spin.set_sensitive(enabled)
        inner_spin.connect("value-changed", self._on_gap_int_changed, "tile-gap-inner")
        inner_row.add_suffix(inner_spin)
        group.add(inner_row)
        self._gap_widgets["tile-gap-inner"] = inner_spin

        # Outer gap
        outer_row = Adw.ActionRow(
            title="Outer gap",
            subtitle="Pixel spacing between tiled windows and screen edges.",
        )
        outer_spin = Gtk.SpinButton.new_with_range(0, 64, 1)
        outer_spin.set_valign(Gtk.Align.CENTER)
        outer_spin.set_value(ab._get_int("tile-gap-outer", default=8))
        outer_spin.set_sensitive(enabled)
        outer_spin.connect("value-changed", self._on_gap_int_changed, "tile-gap-outer")
        outer_row.add_suffix(outer_spin)
        group.add(outer_row)
        self._gap_widgets["tile-gap-outer"] = outer_spin

        self.append(group)

    def _on_gap_master_switch(self, switch: Gtk.Switch, _pspec):
        active = switch.get_active()
        self._animation_backend._set_boolean("tile-gaps-enabled", active)
        for key, widget in self._gap_widgets.items():
            if key == "_master":
                continue
            widget.set_sensitive(active)

    def _on_gap_int_changed(self, spin: Gtk.SpinButton, key: str):
        if self._updating_gaps:
            return
        self._animation_backend._set_int(key, int(spin.get_value()))

    # ── Tile grid ─────────────────────────────────────────────────

    def _build_tile_grid_group(self):
        ab = self._animation_backend

        group = Adw.PreferencesGroup(
            title="Tile Grid",
            description="Screen grid dimensions for drag-to-tile placement.",
        )

        # Columns
        cols_row = Adw.ActionRow(
            title="Columns",
            subtitle="Number of columns in the tiling grid.",
        )
        cols_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        cols_spin.set_valign(Gtk.Align.CENTER)
        cols_spin.set_value(ab._get_int("tile-cols", default=2))
        cols_spin.connect("value-changed", self._on_grid_int_changed, "tile-cols")
        cols_row.add_suffix(cols_spin)
        group.add(cols_row)
        self._grid_widgets["tile-cols"] = cols_spin

        # Rows
        rows_row = Adw.ActionRow(
            title="Rows",
            subtitle="Number of rows in the tiling grid.",
        )
        rows_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        rows_spin.set_valign(Gtk.Align.CENTER)
        rows_spin.set_value(ab._get_int("tile-rows", default=2))
        rows_spin.connect("value-changed", self._on_grid_int_changed, "tile-rows")
        rows_row.add_suffix(rows_spin)
        group.add(rows_row)
        self._grid_widgets["tile-rows"] = rows_spin

        self.append(group)

    def _on_grid_int_changed(self, spin: Gtk.SpinButton, key: str):
        self._animation_backend._set_int(key, int(spin.get_value()))

    # ── Drag preview ──────────────────────────────────────────────

    def _build_tile_preview_group(self):
        ab = self._animation_backend
        enabled = ab._get_boolean("tile-preview-enabled", default=True)

        group = Adw.PreferencesGroup(
            title="Drag Preview &amp; Snapping",
            description=(
                "Show a tile preview overlay and snap windows to the grid "
                "when dragging near screen edges."
            ),
        )

        # Master switch
        enable_row = Adw.ActionRow(
            title="Enable drag preview",
            subtitle="Preview and snap windows when dragging near edges.",
        )
        enable_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        enable_switch.set_active(enabled)
        enable_switch.connect("notify::active", self._on_preview_master_switch)
        enable_row.add_suffix(enable_switch)
        group.add(enable_row)
        self._preview_widgets["_master"] = enable_switch

        # Edge distance
        dist_row = Adw.ActionRow(
            title="Edge distance",
            subtitle="Pixels from screen edge to trigger the preview.",
        )
        dist_spin = Gtk.SpinButton.new_with_range(0, 150, 5)
        dist_spin.set_valign(Gtk.Align.CENTER)
        dist_spin.set_value(ab._get_int("tile-preview-distance", default=25))
        dist_spin.set_sensitive(enabled)
        dist_spin.connect("value-changed", self._on_preview_int_changed,
                          "tile-preview-distance")
        dist_row.add_suffix(dist_spin)
        group.add(dist_row)
        self._preview_widgets["tile-preview-distance"] = dist_spin

        # Delay
        delay_row = Adw.ActionRow(
            title="Preview delay",
            subtitle="Milliseconds before the preview appears.",
        )
        delay_spin = Gtk.SpinButton.new_with_range(25, 1000, 25)
        delay_spin.set_valign(Gtk.Align.CENTER)
        delay_spin.set_value(ab._get_int("tile-preview-delay", default=500))
        delay_spin.set_sensitive(enabled)
        delay_spin.connect("value-changed", self._on_preview_int_changed,
                          "tile-preview-delay")
        delay_row.add_suffix(delay_spin)
        group.add(delay_row)
        self._preview_widgets["tile-preview-delay"] = delay_spin

        self.append(group)

    def _on_preview_master_switch(self, switch: Gtk.Switch, _pspec):
        active = switch.get_active()
        self._animation_backend._set_boolean("tile-preview-enabled", active)
        for key, widget in self._preview_widgets.items():
            if key == "_master":
                continue
            widget.set_sensitive(active)

    def _on_preview_int_changed(self, spin: Gtk.SpinButton, key: str):
        self._animation_backend._set_int(key, int(spin.get_value()))

    def _on_install_runtime(self):
        if not self._animation_backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        self._toast("Bundled More Tweaks runtime installed")
        self.refresh()

    def _on_enable_runtime(self, enabled: bool):
        if enabled and not self._animation_backend.available and not self._animation_backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        success = self._animation_backend.enable_runtime() if enabled else self._animation_backend.disable_runtime()
        self._toast(
            "Bundled More Tweaks runtime enabled"
            if success and enabled
            else "Bundled More Tweaks runtime disabled"
        )
        self.refresh()


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
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.set_margin_bottom(48)
        self._notify = notify
        self._backend = SettingsBackend()
        self._animation_backend = AnimationBackend()
        self._tweak_rows: list[TweakRow | TextListRow] = []
        self._gesture_widgets: dict[str, Gtk.DropDown] = {}
        self._updating_gestures = False

    def _toast(self, message: str):
        if self._notify:
            self._notify(message)

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

        # ── Runtime management (shared widget) ─────────────────────────
        runtime_group = _build_runtime_group(
            self._animation_backend,
            on_install=self._on_install_runtime,
            on_enable_changed=self._on_enable_runtime,
        )
        self.append(runtime_group)

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

    def _on_install_runtime(self):
        if not self._animation_backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        self._toast("Bundled More Tweaks runtime installed")
        self.refresh()

    def _on_enable_runtime(self, enabled: bool):
        if enabled and not self._animation_backend.available and not self._animation_backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        success = self._animation_backend.enable_runtime() if enabled else self._animation_backend.disable_runtime()
        self._toast(
            "Bundled More Tweaks runtime enabled"
            if success and enabled
            else "Bundled More Tweaks runtime disabled"
        )
        self.refresh()


class AnimationSection(_ScrollPreservingSection):
    def __init__(self, notify: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.set_margin_bottom(48)
        self.backend = AnimationBackend()
        self.custom_presets = CustomPresetStore()
        self.desktop_settings = Gio.Settings.new("org.gnome.desktop.interface")
        self._notify = notify

        self.refresh()

    def refresh(self):
        sw, pos = self._save_scroll()
        try:
            self._refresh_inner()
        finally:
            self._restore_scroll(sw, pos)

    def _refresh_inner(self):
        self.backend.refresh_runtime_state()

        # Save UI state before rebuild
        saved_tab = getattr(self, "_saved_notebook_tab", 0)
        if hasattr(self, "_notebook") and self._notebook is not None:
            saved_tab = self._notebook.get_current_page()

        _clear_box(self)
        banner = self._build_runtime_banner()
        if banner is not None:
            self.append(banner)

        for group in self._build_runtime_group():
            self.append(group)

        # If the extension isn't ready, show a prominent status page
        # instead of a wall of greyed-out controls.
        if self.backend.needs_shell_restart:
            self.append(_build_status_page(
                icon_name="system-log-out-symbolic",
                title="Log Out Required",
                description=(
                    "The bundled shell runtime has been installed, but GNOME Shell "
                    "needs to restart to detect it.\n\n"
                    "On Wayland, log out and log back in. "
                    "The animation controls will appear here after that."
                ),
            ))
            self._notebook = None
            self._saved_notebook_tab = saved_tab
            return

        if not self.backend.available:
            self.append(_build_status_page(
                icon_name="application-x-addon-symbolic",
                title="Shell Runtime Not Installed",
                description=(
                    "More Tweaks ships a bundled GNOME Shell extension that "
                    "controls window, dialog, and notification animations.\n\n"
                    "Use the Install button above to set it up. "
                    "The animation controls will appear here once it's running."
                ),
            ))
            self._notebook = None
            self._saved_notebook_tab = saved_tab
            return

        for group in self._build_controls_group():
            self.append(group)
        for group in self._build_diagnostics_group():
            self.append(group)

        group_states = self.backend.get_group_states()
        notebook = Gtk.Notebook()
        notebook.set_scrollable(True)
        notebook.set_size_request(-1, 500)

        # Map animation group IDs to the capability they require
        _group_capability = {
            "windows": "animations",
            "window_states": "animations",
            "interactive": "animations",
            "dialogs": "animations",
            "notifications": "notifications",
        }

        # System timing tab (first)
        system_page = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        system_page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sys_blocked = _check_capability(
            self.backend, "systemTimings", "System Animation Timings")
        system_page.set_child(
            sys_blocked if sys_blocked else self._build_system_timing_group())
        notebook.append_page(system_page, Gtk.Label(label="System"))

        for group_state in group_states:
            page = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
            page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            cap = _group_capability.get(group_state.spec.id, "animations")
            blocked = _check_capability(
                self.backend, cap, f"{group_state.spec.title} Animations")
            page.set_child(
                blocked if blocked else self._build_group(group_state))
            notebook.append_page(page, Gtk.Label(label=group_state.spec.title))

        # Per-App Rules tab
        per_app_page = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        per_app_page.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        per_app_page.set_child(self._build_per_app_rules())
        notebook.append_page(per_app_page, Gtk.Label(label="Per-App Rules"))

        self._notebook = notebook
        self.append(notebook)

        # Restore notebook tab
        n_pages = notebook.get_n_pages()
        if saved_tab >= 0 and saved_tab < n_pages:
            notebook.set_current_page(saved_tab)
        self._saved_notebook_tab = saved_tab

    def _build_runtime_banner(self) -> Adw.Banner | None:
        if not self.backend.runtime_error:
            return None

        banner = Adw.Banner(
            title="GNOME Shell reports an error in the bundled More Tweaks runtime. Retry the runtime after changing the shell hooks."
        )
        banner.set_button_label("Retry runtime")
        banner.set_revealed(True)
        banner.connect("button-clicked", self._on_retry_runtime_clicked)
        return banner

    def _build_runtime_group(self) -> list[Adw.PreferencesGroup]:
        """Group A: Runtime -- installation and enable state."""
        group = _build_runtime_group(
            self.backend,
            on_install=self._on_install_runtime_clicked_action,
            on_enable_changed=self._on_enable_runtime_action,
        )

        # Animation-specific: shell warning row
        if not self.desktop_settings.get_boolean("enable-animations"):
            shell_warning_row = Adw.ActionRow(title="GNOME animations are off")
            shell_warning_row.set_subtitle(
                "Turn that desktop-wide switch back on or GNOME Shell may suppress visible motion even when the bundled runtime is enabled."
            )
            warning_label = Gtk.Label(label="Blocking")
            warning_label.add_css_class("dim-label")
            shell_warning_row.add_suffix(warning_label)
            group.add(shell_warning_row)

        return [group]

    def _on_install_runtime_clicked_action(self):
        if not self.backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        self._toast("Bundled More Tweaks runtime installed")
        self.refresh()

    def _on_enable_runtime_action(self, enabled: bool):
        if enabled and not self.backend.available and not self.backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        success = self.backend.enable_runtime() if enabled else self.backend.disable_runtime()
        self._toast(
            "Bundled More Tweaks runtime enabled"
            if success and enabled
            else "Bundled More Tweaks runtime disabled"
        )
        self.refresh()

    def _build_controls_group(self) -> list[Adw.PreferencesGroup]:
        """Group B: Controls -- main animation controls."""
        group = Adw.PreferencesGroup(
            title="Controls",
            description="Main animation knobs for the bundled runtime.",
        )

        # GNOME interface animations toggle
        shell_row = Adw.ActionRow(title="GNOME interface animations")
        shell_row.set_subtitle("Core desktop motion toggle from org.gnome.desktop.interface")
        shell_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        shell_switch.set_active(self.desktop_settings.get_boolean("enable-animations"))
        shell_switch.connect("notify::active", self._on_shell_animations_changed)
        shell_row.add_suffix(shell_switch)
        group.add(shell_row)

        # Curated profile dropdown
        profile_row = Adw.ActionRow(title="Curated profile")
        profile_row.set_subtitle(
            "Quickly swap between tuned motion personalities before adjusting individual bindings."
        )
        profile_dropdown = Gtk.DropDown.new_from_strings(list(PROFILE_NAMES))
        profile_dropdown.set_valign(Gtk.Align.CENTER)
        active_profile = self.backend.get_active_profile()
        try:
            profile_dropdown.set_selected(PROFILE_NAMES.index(active_profile))
        except ValueError:
            profile_dropdown.set_selected(0)
        profile_dropdown.connect("notify::selected", self._on_profile_selected)
        profile_row.add_suffix(profile_dropdown)
        group.add(profile_row)

        # Reduced motion switch
        reduced_motion_row = Adw.ActionRow(title="Reduced motion mode")
        reduced_motion_row.set_subtitle(
            "Keep the bundled runtime active while toning down intensity for every curated preset."
        )
        reduced_motion_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        reduced_motion_switch.set_active(self.backend.get_runtime_flag("reduced-motion-mode"))
        reduced_motion_switch.connect(
            "notify::active",
            self._on_runtime_flag_changed,
            "reduced-motion-mode",
            "Reduced motion enabled",
            "Reduced motion disabled",
        )
        reduced_motion_row.add_suffix(reduced_motion_switch)
        group.add(reduced_motion_row)

        # Effect quality dropdown
        quality_row = Adw.ActionRow(title="Effect quality")
        quality_row.set_subtitle(
            "Pick how much headroom the runtime should spend on heavier effect families as they expand."
        )
        quality_dropdown = Gtk.DropDown.new_from_strings(["Performance", "Balanced", "Spectacle"])
        quality_dropdown.set_valign(Gtk.Align.CENTER)
        quality_names = ("performance", "balanced", "spectacle")
        current_quality = self.backend.get_runtime_string("effects-quality", "balanced")
        try:
            quality_dropdown.set_selected(quality_names.index(current_quality))
        except ValueError:
            quality_dropdown.set_selected(1)
        quality_dropdown.connect("notify::selected", self._on_effect_quality_selected, quality_names)
        quality_row.add_suffix(quality_dropdown)
        group.add(quality_row)

        # Experimental effects switch
        experimental_row = Adw.ActionRow(title="Experimental effect families")
        experimental_row.set_subtitle(
            "Allow compiz-inspired and shader-capable presets to appear in the bundled runtime as the catalog grows."
        )
        experimental_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        experimental_switch.set_active(self.backend.get_runtime_flag("experimental-effects"))
        experimental_switch.connect(
            "notify::active",
            self._on_runtime_flag_changed,
            "experimental-effects",
            "Experimental effects enabled",
            "Experimental effects disabled",
        )
        experimental_row.add_suffix(experimental_switch)
        group.add(experimental_row)

        return [group]

    def _build_diagnostics_group(self) -> list[Adw.PreferencesGroup]:
        """Group C: Diagnostics -- informational rows and maintenance actions."""
        group = Adw.PreferencesGroup(
            title="Diagnostics",
            description="Informational rows, debug controls, and maintenance actions.",
        )

        # Runtime source (informational)
        source_row = Adw.ActionRow(title="Runtime source")
        source_row.set_subtitle(
            "This animation runtime ships inside More Tweaks and is separate from third-party extensions like Burn My Windows or Animation Tweaks."
        )
        source_label = Gtk.Label(label="Bundled")
        source_label.add_css_class("dim-label")
        source_row.add_suffix(source_label)
        group.add(source_row)

        # Current scope (informational)
        scope_row = Adw.ActionRow(title="Current scope")
        scope_row.set_subtitle(
            "This bundled runtime now covers windows, focus and maximize state changes, interactive move or resize reactions, dialogs, modal dialogs, and notification banners."
        )
        scope_label = Gtk.Label(label="Broadening runtime")
        scope_label.add_css_class("dim-label")
        scope_row.add_suffix(scope_label)
        group.add(scope_row)

        # GNOME Shell version (informational)
        shell_ver = self.backend.get_detected_shell_version()
        if shell_ver > 0:
            ver_row = Adw.ActionRow(title="GNOME Shell version")
            ver_row.set_subtitle(
                "Major version detected by the extension at startup.")
            ver_label = Gtk.Label(label=f"GNOME {shell_ver}")
            ver_label.add_css_class("dim-label")
            ver_row.add_suffix(ver_label)
            group.add(ver_row)

        # Capabilities (show only if something failed)
        caps = self.backend.get_active_capabilities()
        failed = [k for k, v in caps.items() if not v]
        if failed:
            caps_row = Adw.ActionRow(title="Capability issues")
            active = [k for k, v in caps.items() if v]
            caps_row.set_subtitle(
                f"Some features could not load: {', '.join(failed)}")
            caps_label = Gtk.Label(label=f"{len(active)}/{len(caps)} active")
            caps_label.add_css_class("dim-label")
            caps_row.add_suffix(caps_label)
            group.add(caps_row)

        # Debug logging switch
        debug_row = Adw.ActionRow(title="Runtime debug logging")
        debug_row.set_subtitle("Write effect-selection and hook diagnostics into the GNOME Shell log.")
        debug_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        debug_switch.set_active(self.backend.get_runtime_flag("debug-logging"))
        debug_switch.connect(
            "notify::active",
            self._on_runtime_flag_changed,
            "debug-logging",
            "Runtime debug logging enabled",
            "Runtime debug logging disabled",
        )
        debug_row.add_suffix(debug_switch)
        group.add(debug_row)

        # Test animation button
        group.add(self._build_test_animation_row())

        # Restore defaults button
        defaults_row = Adw.ActionRow(title="Restore bundled defaults")
        defaults_row.set_subtitle(
            "Reset curated profile, timings, and hidden advanced controls back to their shipped values."
        )
        defaults_button = Gtk.Button(label="Restore")
        defaults_button.add_css_class("pill")
        defaults_button.set_valign(Gtk.Align.CENTER)
        defaults_button.connect("clicked", self._on_restore_defaults_clicked)
        defaults_row.add_suffix(defaults_button)
        group.add(defaults_row)

        # Open logs button
        logs_row = Adw.ActionRow(title="Diagnostics logs")
        logs_row.set_subtitle(
            "Open a filtered GNOME Shell log snapshot for the bundled More Tweaks runtime in your default text viewer."
        )
        logs_button = Gtk.Button(label="Open logs")
        logs_button.add_css_class("pill")
        logs_button.set_valign(Gtk.Align.CENTER)
        logs_button.connect("clicked", self._on_open_logs_clicked)
        logs_row.add_suffix(logs_button)
        group.add(logs_row)

        return [group]

    _SYSTEM_TIMINGS = (
        ("system-overview-duration-ms", "Overview", "Show and hide the Activities overview.", 250),
        ("system-show-apps-duration-ms", "Show Applications", "Transition between the overview and the application grid.", 250),
        ("system-app-grid-duration-ms", "App grid", "Switch to and from the full-screen application grid.", 400),
        ("system-workspace-switch-duration-ms", "Workspace switch", "Slide between workspaces.", 250),
        ("system-app-folder-duration-ms", "App folders", "Open and close app folders in the grid.", 200),
        ("system-osd-duration-ms", "OSD popups", "On-screen display popups for volume, brightness, etc.", 250),
    )

    def _build_system_timing_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            description="Duration overrides for built-in GNOME Shell transitions that are normally hardcoded.",
        )
        group.set_margin_top(12)
        group.set_margin_start(12)
        group.set_margin_end(12)

        for key, title, subtitle, default in self._SYSTEM_TIMINGS:
            row = Adw.ActionRow(title=title)
            row.set_subtitle(subtitle)

            spin = Gtk.SpinButton.new_with_range(50, 2000, 10)
            spin.set_valign(Gtk.Align.CENTER)
            spin.set_value(self.backend.get_system_timing(key, default))
            spin.connect("value-changed", self._on_system_timing_changed, key)
            row.add_suffix(spin)

            ms_label = Gtk.Label(label="ms")
            ms_label.add_css_class("dim-label")
            ms_label.add_css_class("caption")
            row.add_suffix(ms_label)

            group.add(row)

        return group

    def _on_system_timing_changed(self, spin: Gtk.SpinButton, key: str):
        self.backend.set_system_timing(key, int(round(spin.get_value())))

    def _build_per_app_rules(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Application Overrides",
            description="Override animation settings for specific applications matched by WM_CLASS.",
        )
        group.set_margin_top(12)
        group.set_margin_start(12)
        group.set_margin_end(12)

        overrides = self.backend.get_per_app_overrides()

        for entry in overrides:
            wm_class = entry.get("wm_class", "")
            match_mode = entry.get("match_mode", "exact")
            rules = entry.get("rules", {})

            app_row = Adw.ExpanderRow(title=wm_class)
            app_row.set_subtitle(f"Match: {match_mode} · {len(rules)} rule(s)")

            for action, rule in rules.items():
                rule_row = Adw.ActionRow(title=action.replace("-", " ").title())
                preset = rule.get("preset", "Glide In")
                duration = rule.get("duration_ms", 240)
                enabled = rule.get("enabled", True)

                rule_row.set_subtitle(f"{preset} · {duration}ms")

                enabled_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
                enabled_switch.set_active(enabled)
                enabled_switch.connect(
                    "notify::active",
                    self._on_per_app_rule_enabled_changed,
                    wm_class, action,
                )
                rule_row.add_suffix(enabled_switch)
                app_row.add_row(rule_row)

            # Remove app button
            remove_row = Adw.ActionRow(title="Remove this application")
            remove_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
            remove_btn.add_css_class("flat")
            remove_btn.set_valign(Gtk.Align.CENTER)
            remove_btn.connect("clicked", self._on_remove_per_app_override, wm_class)
            remove_row.add_suffix(remove_btn)
            app_row.add_row(remove_row)

            group.add(app_row)

        # Add new override row
        add_row = Adw.ActionRow(title="Add application override")
        add_row.set_subtitle("Enter the WM_CLASS of the application (use xprop WM_CLASS to find it)")

        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add_box.set_valign(Gtk.Align.CENTER)

        wm_entry = Gtk.Entry()
        wm_entry.set_placeholder_text("WM_CLASS")
        wm_entry.set_width_chars(14)
        add_box.append(wm_entry)

        match_dd = Gtk.DropDown.new_from_strings(["Exact", "Contains"])
        add_box.append(match_dd)

        action_dd = Gtk.DropDown.new_from_strings(list(PER_APP_ACTIONS))
        add_box.append(action_dd)

        add_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        add_btn.add_css_class("flat")
        add_btn.connect("clicked", self._on_add_per_app_override, wm_entry, match_dd, action_dd)
        add_box.append(add_btn)

        add_row.add_suffix(add_box)
        group.add(add_row)

        return group

    def _on_add_per_app_override(self, _btn, wm_entry, match_dd, action_dd):
        wm_class = wm_entry.get_text().strip()
        if not wm_class:
            wm_entry.add_css_class("error")
            return
        wm_entry.remove_css_class("error")
        match_modes = ("exact", "contains")
        match_mode = match_modes[match_dd.get_selected()]
        action = PER_APP_ACTIONS[action_dd.get_selected()]
        rule = {"preset": "Glide In", "duration_ms": 240, "enabled": True}
        if not self._prepare_runtime("add per-app animation override"):
            self.refresh()
            return
        self.backend.add_per_app_override(wm_class, match_mode, action, rule)
        self._toast(f"Added {action} override for {wm_class}")
        self.refresh()

    def _on_remove_per_app_override(self, _btn, wm_class):
        self.backend.remove_per_app_override(wm_class)
        self._toast(f"Removed overrides for {wm_class}")
        self.refresh()

    def _on_per_app_rule_enabled_changed(self, switch, _pspec, wm_class, action):
        overrides = self.backend.get_per_app_overrides()
        for entry in overrides:
            if entry.get("wm_class", "").lower() == wm_class.lower():
                if action in entry.get("rules", {}):
                    entry["rules"][action]["enabled"] = switch.get_active()
                break
        self.backend.set_per_app_overrides(overrides)

    def _build_group(self, group_state) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            description=group_state.spec.summary,
        )
        group.set_margin_top(12)
        group.set_margin_start(12)
        group.set_margin_end(12)

        for binding in group_state.bindings:
            group.add(self._build_binding_row(binding))

        return group

    def _build_binding_row(self, binding) -> Adw.ExpanderRow:
        row = Adw.ExpanderRow(title=binding.spec.title)
        tier_prefix = "Advanced. " if binding.spec.tier != "core" else ""
        subtitle = f"{tier_prefix}{binding.spec.summary}"
        if binding.preset_name:
            subtitle = (
                f"{subtitle} Current preset: {binding.preset_name} "
                f"({binding.duration_ms} ms, delay {binding.delay_ms} ms, intensity {binding.intensity:.2f})"
            )
        row.set_subtitle(subtitle)

        control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        custom_names = self.custom_presets.preset_names()
        all_preset_names = tuple(custom_names) + binding.preset_names
        dropdown = Gtk.DropDown.new_from_strings(list(all_preset_names))
        dropdown.set_valign(Gtk.Align.CENTER)
        dropdown.set_size_request(220, -1)
        try:
            dropdown.set_selected(all_preset_names.index(binding.preset_name))
        except ValueError:
            dropdown.set_selected(len(custom_names))
        dropdown.connect(
            "notify::selected",
            self._on_binding_preset_selected,
            binding.spec.preset_key,
            all_preset_names,
        )
        control_box.append(dropdown)

        preview_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        preview_btn.set_valign(Gtk.Align.CENTER)
        preview_btn.add_css_class("flat")
        preview_btn.set_tooltip_text("Preview this animation")
        preview_btn.connect("clicked", self._on_preview_clicked, binding)
        control_box.append(preview_btn)

        clone_btn = Gtk.Button.new_from_icon_name("edit-copy-symbolic")
        clone_btn.set_valign(Gtk.Align.CENTER)
        clone_btn.add_css_class("flat")
        clone_btn.set_tooltip_text("Clone as custom preset")
        clone_btn.connect("clicked", self._on_clone_preset_clicked, binding)
        control_box.append(clone_btn)

        switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        switch.set_active(binding.enabled)
        switch.connect("notify::active", self._on_binding_enabled_changed, binding.spec.enabled_key)
        control_box.append(switch)

        row.add_suffix(control_box)

        duration_row = Adw.ActionRow(title="Duration")
        duration_row.set_subtitle("Visible timing for this binding.")
        duration_spin = Gtk.SpinButton.new_with_range(80, 1200, 10)
        duration_spin.set_valign(Gtk.Align.CENTER)
        duration_spin.set_value(binding.duration_ms)
        duration_spin.connect("value-changed", self._on_binding_duration_changed, binding.spec.duration_key)
        duration_row.add_suffix(duration_spin)
        row.add_row(duration_row)

        delay_row = Adw.ActionRow(title="Delay")
        delay_row.set_subtitle("Hidden advanced control for staggering motion.")
        delay_spin = Gtk.SpinButton.new_with_range(0, 600, 10)
        delay_spin.set_valign(Gtk.Align.CENTER)
        delay_spin.set_value(binding.delay_ms)
        delay_spin.connect("value-changed", self._on_binding_delay_changed, binding.spec.delay_key)
        delay_row.add_suffix(delay_spin)
        row.add_row(delay_row)

        intensity_row = Adw.ActionRow(title="Intensity")
        intensity_row.set_subtitle("Hidden advanced control for exaggerating or softening the preset.")
        intensity_spin = Gtk.SpinButton.new_with_range(0.25, 2.0, 0.05)
        intensity_spin.set_digits(2)
        intensity_spin.set_valign(Gtk.Align.CENTER)
        intensity_spin.set_value(binding.intensity)
        intensity_spin.connect(
            "value-changed",
            self._on_binding_intensity_changed,
            binding.spec.intensity_key,
        )
        intensity_row.add_suffix(intensity_spin)
        row.add_row(intensity_row)

        timeline_row = Adw.ActionRow(title="Timeline")
        timeline_row.set_subtitle("Phase breakdown for this preset.")
        timeline = AnimationTimelineWidget()
        timeline.update(binding.preset_name, binding.duration_ms, binding.delay_ms, binding.intensity)
        timeline_row.add_suffix(timeline)
        row.add_row(timeline_row)

        return row

    def _build_test_animation_row(self) -> Adw.ActionRow:
        row = Adw.ActionRow(title="Test animation")
        row.set_subtitle(
            "Apply the Signature profile, then trigger window open, close, minimize, restore, focus, maximize, and a GNOME notification."
        )
        button = Gtk.Button(label="Apply signature test")
        button.add_css_class("pill")
        button.set_valign(Gtk.Align.CENTER)
        button.connect("clicked", self._on_apply_test_animation_clicked)
        row.add_suffix(button)
        return row

    def _on_shell_animations_changed(self, switch: Gtk.Switch, _pspec):
        self.desktop_settings.set_boolean("enable-animations", switch.get_active())
        self._toast(
            "GNOME interface animations enabled"
            if switch.get_active()
            else "GNOME interface animations disabled"
        )
        self.refresh()

    def _on_retry_runtime_clicked(self, _banner: Adw.Banner):
        if not self.backend.restart_runtime():
            self._toast("Could not restart the bundled More Tweaks runtime")
        else:
            self._toast("Bundled More Tweaks runtime restarted")
        self.refresh()

    def _on_profile_selected(self, dropdown: Gtk.DropDown, _pspec):
        selected = dropdown.get_selected()
        if selected >= len(PROFILE_NAMES):
            return
        profile_name = PROFILE_NAMES[selected]
        if not self._prepare_runtime("apply an animation profile"):
            self.refresh()
            return
        if not self.backend.apply_profile(profile_name):
            self._toast("Could not apply the selected curated profile")
        else:
            self._toast(f"Applied {profile_name} animation profile")
        self.refresh()

    def _on_apply_test_animation_clicked(self, _button: Gtk.Button):
        if not self._prepare_runtime("apply a test animation"):
            self.refresh()
            return

        if not self.desktop_settings.get_boolean("enable-animations"):
            self.desktop_settings.set_boolean("enable-animations", True)
            self._toast("GNOME interface animations enabled for testing")

        updates = (
            self.backend.apply_profile("Signature"),
            self.backend.set_binding_enabled("window-open-enabled", True),
            self.backend.set_binding_enabled("window-close-enabled", True),
            self.backend.set_binding_enabled("window-minimize-enabled", True),
            self.backend.set_binding_enabled("window-unminimize-enabled", True),
            self.backend.set_binding_enabled("window-focus-enabled", True),
            self.backend.set_binding_enabled("window-defocus-enabled", True),
            self.backend.set_binding_enabled("window-maximize-enabled", True),
            self.backend.set_binding_enabled("window-unmaximize-enabled", True),
            self.backend.set_binding_enabled("notification-open-enabled", True),
            self.backend.set_binding_enabled("notification-close-enabled", True),
        )
        if all(updates):
            self._toast(
                "Signature test applied. Trigger a notification or open, close, minimize, and restore a normal window."
            )
        else:
            self._toast("Could not apply the full test preset")
        self.refresh()

    def _on_open_logs_clicked(self, _button: Gtk.Button):
        try:
            result = subprocess.run(
                ["journalctl", "--user", "--since", "30 min ago", "--output=cat"],
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            self._toast("Could not collect GNOME Shell logs")
            return

        lines = [
            line
            for line in result.stdout.splitlines()
            if "More Tweaks Shell Runtime" in line
            or "more-tweaks-shell@n14395.github.com" in line
            or "gnome-shell" in line
        ]
        if not lines:
            lines = ["No matching More Tweaks runtime log lines found in the last 30 minutes."]

        try:
            temp_dir = Path(tempfile.gettempdir())
            log_path = temp_dir / "more-tweaks-shell-runtime-logs.txt"
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            uri = GLib.filename_to_uri(str(log_path), None)
            Gio.AppInfo.launch_default_for_uri(uri, None)
            self._toast(f"Opened log snapshot: {log_path}")
        except Exception:
            self._toast("Could not open the log snapshot")

    def _on_binding_enabled_changed(self, switch: Gtk.Switch, _pspec, key: str):
        if not self._prepare_runtime("apply animation changes"):
            self.refresh()
            return
        if not self.backend.set_binding_enabled(key, switch.get_active()):
            self._toast("Could not update animation target")
        self.refresh()

    def _on_preview_clicked(self, button, binding):
        preset_name = binding.preset_name
        preset = TRANSFORM_PRESETS.get(preset_name)
        if preset is None:
            self._toast(f"'{preset_name}' uses a runtime-only effect and cannot be previewed")
            return
        popover = Gtk.Popover()
        preview = AnimationPreviewWidget()
        if preset.setup.opacity < 128:
            preview.set_visible_during_wait(False)
        popover.set_child(preview)
        popover.set_parent(button)
        popover.popup()
        GLib.timeout_add(500, preview.play, preset, binding.duration_ms, binding.delay_ms, binding.intensity)

    def _on_clone_preset_clicked(self, _button, binding):
        preset_name = binding.preset_name
        preset = TRANSFORM_PRESETS.get(preset_name)
        if preset is None:
            self._toast(f"'{preset_name}' is a runtime-only effect and cannot be cloned")
            return
        preset_data = CustomPresetStore.transform_preset_to_dict(preset)
        new_name = f"Custom {preset_name}"
        suffix = 1
        while not self.custom_presets.clone_preset(preset_name, new_name, preset_data):
            suffix += 1
            new_name = f"Custom {preset_name} {suffix}"
        self.backend.bump_custom_presets_version()
        self._toast(f"Created custom preset '{new_name}'")
        self._show_preset_editor(new_name)

    def _show_preset_editor(self, preset_name: str):
        data = self.custom_presets.get_preset(preset_name)
        if data is None:
            return

        dialog = Adw.Dialog(title=f"Edit: {preset_name}")
        dialog.set_content_width(480)
        dialog.set_content_height(600)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Setup state group
        setup_group = Adw.PreferencesGroup(title="Setup State", description="Initial transform before animation begins.")
        setup = data.get("setup", {})

        setup_spins = {}
        setup_fields = [
            ("opacity", "Opacity", 0, 255, 1, setup.get("opacity", 255)),
            ("scaleX", "Scale X", 0.0, 2.0, 0.01, setup.get("scaleX", 1.0)),
            ("scaleY", "Scale Y", 0.0, 2.0, 0.01, setup.get("scaleY", 1.0)),
            ("translationX", "Translation X", -200.0, 200.0, 1.0, setup.get("translationX", 0.0)),
            ("translationY", "Translation Y", -200.0, 200.0, 1.0, setup.get("translationY", 0.0)),
            ("rotationZ", "Rotation Z", -180.0, 180.0, 0.5, setup.get("rotationZ", 0.0)),
            ("pivotX", "Pivot X", 0.0, 1.0, 0.1, setup.get("pivotX", 0.5)),
            ("pivotY", "Pivot Y", 0.0, 1.0, 0.1, setup.get("pivotY", 0.5)),
        ]
        for key, label, lo, hi, step, val in setup_fields:
            row = Adw.ActionRow(title=label)
            spin = Gtk.SpinButton.new_with_range(lo, hi, step)
            if isinstance(val, float) and step < 1:
                spin.set_digits(2)
            spin.set_value(val)
            spin.set_valign(Gtk.Align.CENTER)
            row.add_suffix(spin)
            setup_group.add(row)
            setup_spins[key] = spin

        box.append(setup_group)

        # Phase groups
        easing_options = ["EASE_OUT_CUBIC", "EASE_IN_CUBIC", "EASE_OUT_QUAD", "EASE_IN_QUAD", "EASE_OUT_BOUNCE", "LINEAR"]
        phase_widgets = []
        phases = data.get("phases", [])

        for i, phase in enumerate(phases):
            phase_group = Adw.PreferencesGroup(title=f"Phase {i + 1}")
            spins = {}

            phase_fields = [
                ("opacity", "Opacity", 0, 255, 1),
                ("scaleX", "Scale X", 0.0, 2.0, 0.01),
                ("scaleY", "Scale Y", 0.0, 2.0, 0.01),
                ("translationX", "Translation X", -200.0, 200.0, 1.0),
                ("translationY", "Translation Y", -200.0, 200.0, 1.0),
                ("rotationZ", "Rotation Z", -180.0, 180.0, 0.5),
            ]
            for key, label, lo, hi, step in phase_fields:
                val = phase.get(key)
                if val is None:
                    continue
                row = Adw.ActionRow(title=label)
                spin = Gtk.SpinButton.new_with_range(lo, hi, step)
                if isinstance(val, float) and step < 1:
                    spin.set_digits(2)
                spin.set_value(val)
                spin.set_valign(Gtk.Align.CENTER)
                row.add_suffix(spin)
                phase_group.add(row)
                spins[key] = spin

            # Duration scale
            ds_row = Adw.ActionRow(title="Duration Scale")
            ds_spin = Gtk.SpinButton.new_with_range(0.05, 1.0, 0.01)
            ds_spin.set_digits(2)
            ds_spin.set_value(phase.get("durationScale", 1.0))
            ds_spin.set_valign(Gtk.Align.CENTER)
            ds_row.add_suffix(ds_spin)
            phase_group.add(ds_row)
            spins["durationScale"] = ds_spin

            # Easing mode
            easing_row = Adw.ActionRow(title="Easing")
            easing_dd = Gtk.DropDown.new_from_strings(easing_options)
            easing_dd.set_valign(Gtk.Align.CENTER)
            current_mode = phase.get("mode", "EASE_OUT_CUBIC")
            try:
                easing_dd.set_selected(easing_options.index(current_mode))
            except ValueError:
                easing_dd.set_selected(0)
            easing_row.add_suffix(easing_dd)
            phase_group.add(easing_row)
            spins["_easing_dd"] = easing_dd

            box.append(phase_group)
            phase_widgets.append(spins)

        # Preview
        preview = AnimationPreviewWidget()
        box.append(preview)

        # Save / Delete buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.END)

        delete_btn = Gtk.Button(label="Delete Preset")
        delete_btn.add_css_class("destructive-action")
        btn_box.append(delete_btn)

        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        btn_box.append(save_btn)
        box.append(btn_box)

        def _on_save(_btn):
            new_setup = {}
            for key, spin in setup_spins.items():
                new_setup[key] = spin.get_value()
            new_setup["opacity"] = int(new_setup["opacity"])

            new_phases = []
            for pw in phase_widgets:
                p = {}
                for key, spin in pw.items():
                    if key == "_easing_dd":
                        sel = spin.get_selected()
                        p["mode"] = easing_options[sel] if sel < len(easing_options) else "EASE_OUT_CUBIC"
                    else:
                        p[key] = spin.get_value()
                if "opacity" in p:
                    p["opacity"] = int(p["opacity"])
                new_phases.append(p)

            new_data = {"family": data.get("family", "Custom"), "setup": new_setup, "phases": new_phases}
            if "based_on" in data:
                new_data["based_on"] = data["based_on"]
            self.custom_presets.update_preset(preset_name, new_data)
            self.backend.bump_custom_presets_version()
            self._toast(f"Saved custom preset '{preset_name}'")
            dialog.close()
            self.refresh()

        def _on_delete(_btn):
            self.custom_presets.delete_preset(preset_name)
            self.backend.bump_custom_presets_version()
            self._toast(f"Deleted custom preset '{preset_name}'")
            dialog.close()
            self.refresh()

        def _on_preview_update(*_args):
            new_setup = {}
            for key, spin in setup_spins.items():
                new_setup[key] = spin.get_value()
            new_setup["opacity"] = int(new_setup["opacity"])
            try:
                tp = self.custom_presets.to_transform_preset(preset_name)
                if tp:
                    preview.play(tp, 300, 0, 1.0)
            except Exception:
                pass

        save_btn.connect("clicked", _on_save)
        delete_btn.connect("clicked", _on_delete)

        scroller.set_child(box)
        toolbar.set_content(scroller)
        dialog.set_child(toolbar)
        dialog.present(self.get_root())

    def _on_binding_preset_selected(
        self,
        dropdown: Gtk.DropDown,
        _pspec,
        preset_key: str,
        preset_names: tuple[str, ...],
    ):
        selected = dropdown.get_selected()
        if selected >= len(preset_names):
            return
        if not self._prepare_runtime("apply animation changes"):
            self.refresh()
            return
        if not self.backend.set_binding_preset(preset_key, preset_names[selected]):
            self._toast("Could not update animation preset")
        self.refresh()

    def _on_binding_duration_changed(self, spin: Gtk.SpinButton, duration_key: str):
        if not self._prepare_runtime("update animation timing"):
            self.refresh()
            return
        if not self.backend.set_binding_duration(duration_key, int(round(spin.get_value()))):
            self._toast("Could not update animation duration")
        self.refresh()

    def _on_binding_delay_changed(self, spin: Gtk.SpinButton, delay_key: str):
        if not self._prepare_runtime("update animation timing"):
            self.refresh()
            return
        if not self.backend.set_binding_delay(delay_key, int(round(spin.get_value()))):
            self._toast("Could not update animation delay")
        self.refresh()

    def _on_binding_intensity_changed(self, spin: Gtk.SpinButton, intensity_key: str):
        if not self._prepare_runtime("update animation intensity"):
            self.refresh()
            return
        if not self.backend.set_binding_intensity(intensity_key, float(spin.get_value())):
            self._toast("Could not update animation intensity")
        self.refresh()

    def _on_runtime_flag_changed(
        self,
        switch: Gtk.Switch,
        _pspec,
        key: str,
        enabled_message: str,
        disabled_message: str,
    ):
        if not self._prepare_runtime("change runtime behavior"):
            self.refresh()
            return
        if not self.backend.set_runtime_flag(key, switch.get_active()):
            self._toast("Could not update runtime behavior")
        else:
            self._toast(enabled_message if switch.get_active() else disabled_message)
        self.refresh()

    def _on_effect_quality_selected(
        self,
        dropdown: Gtk.DropDown,
        _pspec,
        quality_names: tuple[str, ...],
    ):
        selected = dropdown.get_selected()
        if selected >= len(quality_names):
            return
        if not self._prepare_runtime("change runtime quality"):
            self.refresh()
            return
        if not self.backend.set_runtime_string("effects-quality", quality_names[selected]):
            self._toast("Could not update effect quality")
        else:
            self._toast(f"Effect quality set to {quality_names[selected]}")
        self.refresh()

    def _on_restore_defaults_clicked(self, _button: Gtk.Button):
        if not self._prepare_runtime("restore animation defaults"):
            self.refresh()
            return
        if not self.backend.restore_defaults():
            self._toast("Could not restore bundled animation defaults")
        else:
            self._toast("Bundled animation defaults restored")
        self.refresh()

    def _prepare_runtime(self, action: str) -> bool:
        if not self.backend.available and not self.backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            return False
        if self.backend.needs_shell_restart:
            self._toast("Log out and log back in for GNOME Shell to detect the runtime")
            return False
        if self.backend.runtime_enabled:
            return True
        if not self.backend.enable_runtime():
            self._toast(f"Could not enable the bundled runtime to {action}")
            return False
        self._toast("Bundled More Tweaks runtime enabled automatically")
        return True

    def _toast(self, message: str):
        if self._notify is not None:
            self._notify(message)



class MoreTweaksWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="More Tweaks")
        self.set_default_size(1120, 640)

        self.selected_category: str = CATEGORIES[0].id
        self.categories_by_id = {category.id: category for category in CATEGORIES}
        self.backend = SettingsBackend()
        self.backend.connect_change_callback(self._on_external_change)
        self.rendered_rows: list[TweakRow | TextListRow] = []

        self.toast_overlay = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        # Primary menu (hamburger menu)
        menu = Gio.Menu()
        menu.append("Reset All Settings", "app.reset-all")
        menu.append("Keyboard Shortcuts", "app.shortcuts")
        menu.append("About More Tweaks", "app.about")
        menu.append("Quit", "app.quit")

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        import_button = Gtk.Button(icon_name="document-open-symbolic")
        import_button.set_tooltip_text("Import settings")
        import_button.connect("clicked", self._on_import_clicked)
        header.pack_end(import_button)

        export_button = Gtk.Button(icon_name="document-save-symbolic")
        export_button.set_tooltip_text("Export settings")
        export_button.connect("clicked", self._on_export_clicked)
        header.pack_end(export_button)

        toolbar.add_top_bar(header)
        self.toast_overlay.set_child(toolbar)
        self.set_content(self.toast_overlay)

        # Build the NavigationSplitView
        self.split_view = Adw.NavigationSplitView()
        self.split_view.set_max_sidebar_width(260)
        self.split_view.set_min_sidebar_width(200)

        content_page = Adw.NavigationPage(title="Tweaks")
        content_page.set_child(self._build_main_panel())
        self.split_view.set_content(content_page)

        sidebar_page = Adw.NavigationPage(title="Categories")
        sidebar_page.set_child(self._build_sidebar())
        self.split_view.set_sidebar(sidebar_page)

        toolbar.set_content(self.split_view)

        self._update_category_header()
        self.refresh_rows()

    def _build_sidebar(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_vexpand(True)

        # Global search entry at the top of the sidebar
        self.search_entry = Gtk.SearchEntry(
            placeholder_text="Search tweaks..."
        )
        self.search_entry.set_margin_start(6)
        self.search_entry.set_margin_end(6)
        self.search_entry.set_margin_top(6)
        self.search_entry.connect("search-changed", self._on_filters_changed)
        self.search_entry.connect("stop-search", self._on_search_stopped)
        box.append(self.search_entry)

        self.category_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.category_list.add_css_class("navigation-sidebar")
        self.category_list.set_valign(Gtk.Align.FILL)
        self.category_list.connect("row-selected", self._on_category_selected)
        self.category_list.connect("row-activated", self._on_category_activated)

        self.category_rows: dict[Gtk.ListBoxRow, Category] = {}
        self._child_rows: dict[str, list[Gtk.ListBoxRow]] = {}
        self._expander_arrows: dict[str, Gtk.Image] = {}

        children_by_parent: dict[str, list[Category]] = {}
        for category in CATEGORIES:
            if category.parent is not None:
                children_by_parent.setdefault(category.parent, []).append(category)

        for category in CATEGORIES:
            # Skip child categories — they are added under their parent
            if category.parent is not None:
                continue

            row = self._build_sidebar_row(category)
            self.category_rows[row] = category
            self.category_list.append(row)

            # Add collapsible children
            if category.id in children_by_parent:
                arrow = Gtk.Image.new_from_icon_name("pan-end-symbolic")
                arrow.set_pixel_size(12)
                row.get_child().append(arrow)
                self._expander_arrows[category.id] = arrow

                child_rows: list[Gtk.ListBoxRow] = []
                for child in children_by_parent[category.id]:
                    child_row = self._build_sidebar_row(child, indent=True)
                    child_row.set_visible(False)
                    self.category_rows[child_row] = child
                    self.category_list.append(child_row)
                    child_rows.append(child_row)
                self._child_rows[category.id] = child_rows

        sidebar_scroll = Gtk.ScrolledWindow(vexpand=True)
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.set_child(self.category_list)
        box.append(sidebar_scroll)

        first_row = self.category_list.get_row_at_index(0)
        if first_row is not None:
            self.category_list.select_row(first_row)

        return box

    def _build_sidebar_row(self, category: Category, indent: bool = False) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(28 if indent else 10)
        content.set_margin_end(10)

        icon = Gtk.Image.new_from_icon_name(category.icon_name)
        name = Gtk.Label(label=category.name, xalign=0)
        name.set_hexpand(True)

        content.append(icon)
        content.append(name)
        row.set_child(content)
        return row

    def _build_main_panel(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)

        self.category_title_label = Gtk.Label(xalign=0)
        self.category_title_label.add_css_class("title-2")
        box.append(self.category_title_label)

        self.category_description_label = Gtk.Label(xalign=0, wrap=True)
        self.category_description_label.add_css_class("dim-label")
        box.append(self.category_description_label)

        self.group = Adw.PreferencesGroup()
        self.empty_status = Adw.StatusPage(
            title="No settings match the current filters",
            description="Try a broader search term.",
        )

        self.results_stack = Gtk.Stack(vhomogeneous=False)
        self.results_stack.add_named(self.group, "results")
        self.results_stack.add_named(self.empty_status, "empty")

        self.animation_section = AnimationSection(self._show_toast)
        self.topbar_section = TopBarSection(self._show_toast)
        self.tiling_section = TilingSection(self._show_toast)
        self.touchpad_section = TouchpadSection(self._show_toast)

        self.section_stack = Gtk.Stack(vhomogeneous=False)
        self.section_stack.add_named(self.results_stack, "generic")
        self.section_stack.add_named(self.animation_section, "animations")
        self.section_stack.add_named(self.topbar_section, "topbar")
        self.section_stack.add_named(self.tiling_section, "tiling")
        self.section_stack.add_named(self.touchpad_section, "touchpad")

        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.section_stack)
        box.append(scroller)
        return box

    def _show_toast(self, message: str):
        self.toast_overlay.add_toast(Adw.Toast.new(message))

    def _update_category_header(self):
        category = self.categories_by_id[self.selected_category]
        self.category_title_label.set_text(category.name)
        self.category_description_label.set_text(category.description)

    def _on_category_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None):
        if row is None:
            return
        category = self.category_rows[row]
        # Parent-only categories (e.g. "Apps") have no content of their own —
        # selection is handled by their children.
        if category.id in self._child_rows:
            return
        self.selected_category = category.id
        self._update_category_header()
        self.refresh_rows()

    def _on_category_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow):
        """Fired on every click, even if the row is already selected."""
        category = self.category_rows.get(row)
        if category is None:
            return
        # Toggle expand/collapse for parent categories with children
        if category.id in self._child_rows:
            child_rows = self._child_rows[category.id]
            expanding = not child_rows[0].get_visible()
            for child_row in child_rows:
                child_row.set_visible(expanding)
            arrow = self._expander_arrows.get(category.id)
            if arrow is not None:
                arrow.set_from_icon_name(
                    "pan-down-symbolic" if expanding else "pan-end-symbolic"
                )
            # Auto-select the first child when expanding
            if expanding:
                self.category_list.select_row(child_rows[0])

    def _on_external_change(self, schema: str, key: str):
        for row in self.rendered_rows:
            if row.tweak.schema == schema and row.tweak.key == key:
                row.refresh()
        for row in self.topbar_section._tweak_rows:
            if row.tweak.schema == schema and row.tweak.key == key:
                row.refresh()
        for row in self.touchpad_section._tweak_rows:
            if row.tweak.schema == schema and row.tweak.key == key:
                row.refresh()
        for row in self.tiling_section._tweak_rows:
            if row.tweak.schema == schema and row.tweak.key == key:
                row.refresh()

    def _on_search_stopped(self, _entry: Gtk.SearchEntry):
        self.search_entry.set_text("")
        self.category_list.grab_focus()

    def reset_focused_tweak(self):
        widget = self.get_focus()
        while widget is not None:
            if isinstance(widget, (TweakRow, TextListRow)):
                self.backend.reset(widget.tweak)
                widget.refresh()
                self._show_toast("Reset to default")
                return
            widget = widget.get_parent()

    def toggle_sidebar(self):
        if self.split_view.get_collapsed():
            self.split_view.set_show_content(
                not self.split_view.get_show_content()
            )

    def _on_filters_changed(self, _entry: Gtk.SearchEntry):
        self.refresh_rows()

    def refresh_rows(self):
        query = self.search_entry.get_text().strip()

        # When searching globally, ignore category scope
        if query:
            # Global search across all categories
            self.category_title_label.set_text("Search")
            self.category_description_label.set_text("Matching tweaks across all categories.")
            self.section_stack.set_visible_child_name("generic")
            for row in self.rendered_rows:
                self.group.remove(row)
            self.rendered_rows.clear()

            matches = filter_tweaks(query, None)

            if not matches:
                self.results_stack.set_visible_child_name("empty")
                return

            self.results_stack.set_visible_child_name("results")
            for tweak in matches:
                if tweak.control == "text-list":
                    row = TextListRow(tweak, self.backend)
                elif tweak.control == "extension-list":
                    row = ExtensionListRow(tweak, self.backend)
                else:
                    row = TweakRow(tweak, self.backend)
                self.rendered_rows.append(row)
                self.group.add(row)
            return

        # No search text -- category-scoped behavior
        self._update_category_header()
        if self.selected_category == "animations":
            self.section_stack.set_visible_child_name("animations")
            self.animation_section.refresh()
            return

        if self.selected_category == "topbar":
            self.section_stack.set_visible_child_name("topbar")
            self.topbar_section.refresh()
            return

        if self.selected_category == "tiling":
            self.section_stack.set_visible_child_name("tiling")
            self.tiling_section.refresh()
            return

        if self.selected_category == "touchpad":
            self.section_stack.set_visible_child_name("touchpad")
            self.touchpad_section.refresh()
            return

        self.section_stack.set_visible_child_name("generic")
        for row in self.rendered_rows:
            self.group.remove(row)
        self.rendered_rows.clear()

        matches = filter_tweaks("", self.selected_category)

        if not matches:
            self.results_stack.set_visible_child_name("empty")
            return

        self.results_stack.set_visible_child_name("results")
        for tweak in matches:
            if tweak.control == "text-list":
                row = TextListRow(tweak, self.backend)
            elif tweak.control == "extension-list":
                row = ExtensionListRow(tweak, self.backend)
            else:
                row = TweakRow(tweak, self.backend)
            self.rendered_rows.append(row)
            self.group.add(row)

    # ── Reset All ─────────────────────────────────────────────────────

    def reset_all_settings(self):
        """Show a confirmation dialog, then reset every non-default setting."""
        tweaks_changed, ext_changed = self._count_changed_settings()
        total = tweaks_changed + ext_changed
        if total == 0:
            self._show_toast("All settings are already at their defaults")
            return

        dialog = Adw.AlertDialog()
        dialog.set_heading("Reset All Settings?")
        parts = []
        if tweaks_changed:
            parts.append(f"{tweaks_changed} system tweak{'s' if tweaks_changed != 1 else ''}")
        if ext_changed:
            parts.append(f"{ext_changed} extension setting{'s' if ext_changed != 1 else ''}")
        dialog.set_body(
            f"This will reset {' and '.join(parts)} back to their GNOME defaults. "
            "This cannot be undone."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Reset All")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_reset_all_response)
        dialog.present(self)

    def _on_reset_all_response(self, _dialog, response: str):
        if response != "reset":
            return
        count = self._do_reset_all()
        self._refresh_all_sections()
        self._show_toast(f"{count} settings reset to defaults")

    def _count_changed_settings(self) -> tuple[int, int]:
        """Return (tweaks_changed, extension_changed) counts."""
        tweaks_changed = 0
        seen: set[tuple[str, str]] = set()
        for tweak in TWEAKS:
            pair = (tweak.schema, tweak.key)
            if pair in seen:
                continue
            seen.add(pair)
            if not self.backend.is_available(tweak):
                continue
            if not self.backend.is_default(tweak):
                tweaks_changed += 1

        ext_changed = 0
        ab = self.animation_section.backend
        if ab.available and ab._settings is not None and ab._schema is not None:
            for key in ab._schema.list_keys():
                if key in self._EPHEMERAL_EXTENSION_KEYS:
                    continue
                current = ab._settings.get_value(key)
                default = ab._settings.get_default_value(key)
                if default is not None and not current.equal(default):
                    ext_changed += 1
        return tweaks_changed, ext_changed

    def _do_reset_all(self) -> int:
        """Reset every non-default tweak and extension key.  Returns count."""
        count = 0

        # GSettings tweaks
        seen: set[tuple[str, str]] = set()
        for tweak in TWEAKS:
            pair = (tweak.schema, tweak.key)
            if pair in seen:
                continue
            seen.add(pair)
            if not self.backend.is_available(tweak):
                continue
            if self.backend.is_default(tweak):
                continue
            if self.backend.reset(tweak):
                count += 1

        # Extension settings
        ab = self.animation_section.backend
        if ab.available and ab._settings is not None and ab._schema is not None:
            for key in ab._schema.list_keys():
                if key in self._EPHEMERAL_EXTENSION_KEYS:
                    continue
                current = ab._settings.get_value(key)
                default = ab._settings.get_default_value(key)
                if default is not None and not current.equal(default):
                    try:
                        ab._settings.reset(key)
                        count += 1
                    except Exception:
                        continue
        return count

    # ── Export / Import ───────────────────────────────────────────────

    # Keys written by the extension at runtime — never export these.
    _EPHEMERAL_EXTENSION_KEYS = frozenset({
        "detected-shell-version",
        "active-capabilities",
        "panel-items-available",
    })

    def _on_export_clicked(self, _button: Gtk.Button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Export settings")
        dialog.set_initial_name("more-tweaks-backup.json")
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON files")
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        dialog.set_filters(filters)
        dialog.save(self, None, self._on_export_finish)

    def _on_export_finish(self, dialog: Gtk.FileDialog, result):
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # user cancelled
        path = gfile.get_path()
        if path is None:
            return
        try:
            data = self._collect_export_data()
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            self._show_toast("Settings exported")
        except Exception as exc:
            self._show_toast(f"Export failed: {exc}")

    def _collect_export_data(self) -> dict:
        data: dict = {
            "format_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "tweaks": {},
            "extension": {},
        }

        # GSettings tweaks — only non-default values
        seen: set[tuple[str, str]] = set()
        for tweak in TWEAKS:
            pair = (tweak.schema, tweak.key)
            if pair in seen:
                continue
            seen.add(pair)
            if not self.backend.is_available(tweak):
                continue
            if self.backend.is_default(tweak):
                continue
            settings = self.backend._get_settings(tweak.schema)
            if settings is None:
                continue
            value = settings.get_value(tweak.key).unpack()
            data["tweaks"][f"{tweak.schema}::{tweak.key}"] = value

        # Extension settings — only non-default values
        ab = self.animation_section.backend
        if ab.available and ab._settings is not None and ab._schema is not None:
            for key in ab._schema.list_keys():
                if key in self._EPHEMERAL_EXTENSION_KEYS:
                    continue
                current = ab._settings.get_value(key)
                default = ab._settings.get_default_value(key)
                if default is not None and current.equal(default):
                    continue
                data["extension"][key] = current.unpack()

        return data

    def _on_import_clicked(self, _button: Gtk.Button):
        dialog = Gtk.FileDialog()
        dialog.set_title("Import settings")
        json_filter = Gtk.FileFilter()
        json_filter.set_name("JSON files")
        json_filter.add_pattern("*.json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        dialog.set_filters(filters)
        dialog.open(self, None, self._on_import_finish)

    def _on_import_finish(self, dialog: Gtk.FileDialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return  # user cancelled
        path = gfile.get_path()
        if path is None:
            return
        try:
            raw = Path(path).read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            self._show_toast(f"Import failed: {exc}")
            return
        if not isinstance(data, dict) or data.get("format_version") != 1:
            self._show_toast("Unrecognised backup format")
            return
        try:
            count = self._apply_import_data(data)
            self._show_toast(f"{count} settings restored")
        except Exception as exc:
            self._show_toast(f"Import failed: {exc}")
        self._refresh_all_sections()

    def _apply_import_data(self, data: dict) -> int:
        count = 0

        # GSettings tweaks
        for composite_key, value in data.get("tweaks", {}).items():
            if "::" not in composite_key:
                continue
            schema_str, key = composite_key.split("::", 1)
            settings = self.backend._get_settings(schema_str)
            if settings is None:
                continue
            default = settings.get_default_value(key)
            if default is None:
                continue
            type_str = default.get_type_string()
            try:
                settings.set_value(key, GLib.Variant(type_str, value))
                count += 1
            except (TypeError, GLib.Error):
                continue

        # Extension settings
        ab = self.animation_section.backend
        if ab.available and ab._settings is not None:
            for key, value in data.get("extension", {}).items():
                if not ab._has_key(key):
                    continue
                if key in self._EPHEMERAL_EXTENSION_KEYS:
                    continue
                default = ab._settings.get_default_value(key)
                if default is None:
                    continue
                type_str = default.get_type_string()
                try:
                    ab._settings.set_value(key, GLib.Variant(type_str, value))
                    count += 1
                except (TypeError, GLib.Error):
                    continue

        return count

    def _refresh_all_sections(self):
        """Refresh every section so they reflect newly imported values."""
        self.refresh_rows()
        self.animation_section.refresh()
        self.topbar_section.refresh()
        self.tiling_section.refresh()
        self.touchpad_section.refresh()
