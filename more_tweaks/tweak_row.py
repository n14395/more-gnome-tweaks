from __future__ import annotations

import logging
import shutil
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from .settings_backend import SettingsBackend, _unit_for_key, _list_installed_themes
from .models import Tweak

_log = logging.getLogger("more_tweaks.tweak_row")


def _highlight_match(text: str, query: str) -> str:
    """Return *text* with the first case-insensitive occurrence of *query*
    wrapped in Pango ``<b>`` tags.  Special XML chars are escaped first."""
    if not query:
        return GLib.markup_escape_text(text)
    escaped = GLib.markup_escape_text(text)
    lower = escaped.lower()
    q_lower = query.lower()
    # Also escape the query for safe comparison against the escaped text
    q_escaped = GLib.markup_escape_text(q_lower)
    idx = lower.find(q_escaped)
    if idx == -1:
        return escaped
    end = idx + len(q_escaped)
    return f"{escaped[:idx]}<b>{escaped[idx:end]}</b>{escaped[end:]}"


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
    def __init__(self, tweak: Tweak, backend: SettingsBackend, highlight: str = ""):
        super().__init__()
        self.tweak = tweak
        self.backend = backend
        self._updating = False

        if highlight:
            self.set_use_markup(True)
            self.set_title(_highlight_match(tweak.name, highlight))
            self.set_subtitle(_highlight_match(tweak.summary, highlight))
        else:
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

    def __init__(self, tweak: Tweak, backend: SettingsBackend, highlight: str = ""):
        super().__init__()
        self.tweak = tweak
        self.backend = backend
        self._items: list[str] = []
        self._sub_rows: list[Gtk.Widget] = []

        if highlight:
            self.set_use_markup(True)
            self.set_title(_highlight_match(tweak.name, highlight))
            self.set_subtitle(_highlight_match(tweak.summary, highlight))
        else:
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
            _log.warning("Failed to write text-list %s::%s", self.tweak.schema, self.tweak.key, exc_info=True)

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

    def __init__(self, tweak: Tweak, backend: SettingsBackend, highlight: str = ""):
        super().__init__()
        self.tweak = tweak
        self.backend = backend
        self._sub_rows: list[Gtk.Widget] = []
        self._toggling = False

        if highlight:
            self.set_use_markup(True)
            self.set_title(_highlight_match(tweak.name, highlight))
            self.set_subtitle(_highlight_match(tweak.summary, highlight))
        else:
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
        if self._toggling:
            return
        enable = switch.get_active()
        method = "EnableExtension" if enable else "DisableExtension"
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Shell.Extensions",
                "/org/gnome/Shell/Extensions",
                "org.gnome.Shell.Extensions",
                None,
            )
            self.backend.suppress(self.tweak.schema, self.tweak.key)
            result = proxy.call_sync(
                method,
                GLib.Variant("(s)", (uuid,)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            success = result is not None and bool(result.unpack()[0])
        except Exception:
            _log.warning("Failed to toggle extension %s", uuid, exc_info=True)
            success = False
        if success:
            if enable:
                self._enabled.add(uuid)
            else:
                self._enabled.discard(uuid)
        else:
            self._toggling = True
            switch.set_active(not enable)
            self._toggling = False

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
        ext_dir = self._USER_EXT_DIR / uuid
        if ext_dir.is_dir():
            shutil.rmtree(ext_dir)
        self._enabled.discard(uuid)
        self._set_enabled(self._enabled)
        self.refresh()
