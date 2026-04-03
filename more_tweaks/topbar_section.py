from __future__ import annotations

import re
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango  # noqa: E402

from .animations import AnimationBackend  # noqa: E402
from .settings_backend import SettingsBackend  # noqa: E402
from .tweak_row import TweakRow, TextListRow, ExtensionListRow  # noqa: E402
from ._shared import (  # noqa: E402
    _ScrollPreservingSection,
    _clear_box,
    _build_runtime_status,
    _build_status_page,
    _check_capability,
)
from .data import TWEAKS, filter_tweaks  # noqa: E402
from .models import Tweak  # noqa: E402


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


class TopBarSection(_ScrollPreservingSection):
    """Hybrid section for the Top Bar category: standard tweaks + panel reorder."""

    def __init__(self, notify: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, notify=notify)
        self.set_margin_bottom(48)
        self._backend = SettingsBackend()
        self._tweak_rows: list[TweakRow | TextListRow] = []
        self._panel_section = PanelReorderSection(self._animation_backend)
        self._topbar_widgets: dict[str, Gtk.Widget] = {}
        self._updating_topbar = False

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

        # Runtime status — compact single-row display when action needed
        for w in _build_runtime_status(
            self._animation_backend,
            on_install=self._on_install_runtime,
            on_enable_changed=self._on_enable_runtime,
            feature_label="Panel layout controls",
        ):
            self.append(w)

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

        # Panel layout capability check
        panel_blocked = _check_capability(
            self._animation_backend, "panelLayout", "Panel Layout Customization")

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

        # Top bar overrides — always show controls; they write to GSettings
        # and take effect once the extension processes them.
        self._build_topbar_overrides()

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

        color_sym_row = Adw.ActionRow(
            title="Colour symbolic icons",
            subtitle="Apply the chosen colour to theme icons and text labels.",
        )
        color_sym_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        color_sym_switch.set_active(
            ab._get_boolean("panel-color-symbolic", default=True))
        color_sym_switch.set_sensitive(enabled)
        color_sym_switch.connect("notify::active", self._on_topbar_bool_changed,
                                 "panel-color-symbolic")
        color_sym_row.add_suffix(color_sym_switch)
        color_group.add(color_sym_row)
        self._topbar_widgets["panel-color-symbolic"] = color_sym_switch

        color_other_row = Adw.ActionRow(
            title="Colour non-symbolic icons",
            subtitle="Tint third-party indicator icons (e.g. Nextcloud, Solaar).",
        )
        color_other_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        color_other_switch.set_active(
            ab._get_boolean("panel-color-other", default=True))
        color_other_switch.set_sensitive(enabled)
        color_other_switch.connect("notify::active", self._on_topbar_bool_changed,
                                   "panel-color-other")
        color_other_row.add_suffix(color_other_switch)
        color_group.add(color_other_row)
        self._topbar_widgets["panel-color-other"] = color_other_switch

        color_act_row = Adw.ActionRow(
            title="Colour Activities indicator",
            subtitle="Tint the workspace overview button in the top-left corner.",
        )
        color_act_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        color_act_switch.set_active(
            ab._get_boolean("panel-color-activities", default=True))
        color_act_switch.set_sensitive(enabled)
        color_act_switch.connect("notify::active", self._on_topbar_bool_changed,
                                 "panel-color-activities")
        color_act_row.add_suffix(color_act_switch)
        color_group.add(color_act_row)
        self._topbar_widgets["panel-color-activities"] = color_act_switch

        color_row = Adw.ActionRow(
            title="Icon color",
            subtitle="Choose the colour to apply to the enabled icon types above.",
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
