from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .settings_backend import SettingsBackend
from .tweak_row import TweakRow, TextListRow, ExtensionListRow
from ._shared import _ScrollPreservingSection, _clear_box, _build_runtime_status, _check_capability, _build_status_page
from .data import filter_tweaks


# ── Tiling & Snapping section ──────────────────────────────────────────


class TilingSection(_ScrollPreservingSection):
    """Hybrid section for the Tiling & Snapping category:
    standard GSettings tweaks + extension-backed tile gap controls."""

    def __init__(self, notify: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, notify=notify)
        self.set_margin_bottom(48)
        self._backend = SettingsBackend()
        self._tweak_rows: list[TweakRow | TextListRow] = []
        self._grid_widgets: dict[str, Gtk.Widget] = {}
        self._preview_widgets: dict[str, Gtk.Widget] = {}
        self._gap_widgets: dict[str, Gtk.Widget] = {}
        self._updating_gaps = False

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

        # Runtime status — compact single-row display when action needed
        for w in _build_runtime_status(
            self._animation_backend,
            on_install=self._on_install_runtime,
            on_enable_changed=self._on_enable_runtime,
            feature_label="Tile gap controls",
        ):
            self.append(w)

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
