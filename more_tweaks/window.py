from __future__ import annotations

import json
import logging
import os
import pwd
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger("more_tweaks.window")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from .animation_section import AnimationSection
from .data import CATEGORIES, CHILD_CATEGORIES, TWEAKS, filter_tweaks
from .models import Category, Tweak
from .preferences import get_preferences
from .settings_backend import SettingsBackend
from .tiling_section import TilingSection
from .topbar_section import TopBarSection
from .touchpad_section import TouchpadSection
from .tweak_row import ExtensionListRow, TextListRow, TweakRow

_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
_CONFIG_DIR = _REAL_HOME / ".config" / "more-tweaks"
_WINDOW_STATE_FILE = _CONFIG_DIR / "window-state.json"


def _load_window_state() -> dict:
    try:
        return json.loads(_WINDOW_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_window_state(state: dict):
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _WINDOW_STATE_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except OSError:
        _log.debug("Could not save window state", exc_info=True)


class MoreTweaksWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="More Tweaks")

        state = _load_window_state()
        self.set_default_size(
            state.get("width", 1120),
            state.get("height", 640),
        )

        prefs = get_preferences()
        startup_pref = prefs.startup_category
        if startup_pref == "last":
            saved_category = state.get("category", CATEGORIES[0].id)
        else:
            saved_category = startup_pref
        self.selected_category: str = CATEGORIES[0].id
        self.categories_by_id = {category.id: category for category in CATEGORIES}
        self.backend = SettingsBackend()
        self.backend.connect_change_callback(self._on_external_change)
        prefs.connect_changed(self._on_preference_changed)
        self.rendered_rows: list[TweakRow | TextListRow] = []

        self.toast_overlay = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        # Primary menu (hamburger menu)
        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
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

        # Restore saved category selection
        if saved_category in self.categories_by_id:
            for row, cat in self.category_rows.items():
                if cat.id == saved_category:
                    # Expand parent if needed
                    if cat.parent and cat.parent in self._child_rows:
                        for child_row in self._child_rows[cat.parent]:
                            child_row.set_visible(True)
                        arrow = self._expander_arrows.get(cat.parent)
                        if arrow:
                            arrow.set_from_icon_name("pan-down-symbolic")
                    self.category_list.select_row(row)
                    break

        self._update_category_header()
        self.refresh_rows()
        self.connect("close-request", self._on_close_request)

    def _on_close_request(self, _window):
        width, height = self.get_default_size()
        # get_default_size returns the set default, not current — use get_size
        # which is only available in GTK4 via get_width/get_height
        _save_window_state({
            "width": self.get_width(),
            "height": self.get_height(),
            "category": self.selected_category,
        })
        return False  # allow the close to proceed

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

    def _on_preference_changed(self, key: str):
        if key in ("hide_unavailable", "show_command_hints"):
            self.refresh_rows()

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

    def _should_hide(self, tweak) -> bool:
        """Return True if this tweak should be skipped due to preferences."""
        if get_preferences().hide_unavailable and not self.backend.is_available(tweak):
            return True
        return False

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
                if self._should_hide(tweak):
                    continue
                if tweak.control == "text-list":
                    row = TextListRow(tweak, self.backend, highlight=query)
                elif tweak.control == "extension-list":
                    row = ExtensionListRow(tweak, self.backend, highlight=query)
                else:
                    row = TweakRow(tweak, self.backend, highlight=query)
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
            if self._should_hide(tweak):
                continue
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
                        _log.debug("Failed to reset extension key %s", key, exc_info=True)
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
        export_dir = get_preferences().default_export_dir
        if export_dir and Path(export_dir).is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(export_dir))
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
            _log.warning("Export failed", exc_info=True)
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
        diff = self._compute_import_diff(data)
        if not diff:
            self._show_toast("No changes to apply — all values already match")
            return
        self._show_import_preview(data, diff)

    def _compute_import_diff(self, data: dict) -> list[tuple[str, str, str]]:
        """Return a list of (label, current_display, new_display) for settings
        that would actually change if *data* were imported."""
        changes: list[tuple[str, str, str]] = []
        tweak_by_key: dict[str, Tweak] = {}
        for t in TWEAKS:
            tweak_by_key.setdefault(f"{t.schema}::{t.key}", t)

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
                new_variant = GLib.Variant(type_str, value)
            except (TypeError, GLib.Error):
                continue
            current = settings.get_value(key)
            if current.equal(new_variant):
                continue
            tweak = tweak_by_key.get(composite_key)
            label = tweak.name if tweak else f"{schema_str} → {key}"
            changes.append((label, str(current.unpack()), str(value)))

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
                    new_variant = GLib.Variant(type_str, value)
                except (TypeError, GLib.Error):
                    continue
                current = ab._settings.get_value(key)
                if current.equal(new_variant):
                    continue
                label = key.replace("-", " ").title()
                changes.append((label, str(current.unpack()), str(value)))
        return changes

    def _show_import_preview(self, data: dict, diff: list[tuple[str, str, str]]):
        """Show a dialog listing what will change, with Cancel/Apply buttons."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(f"Import {len(diff)} Settings?")
        dialog.set_body("The following settings will be changed:")

        # Build a scrollable list of changes
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        group = Adw.PreferencesGroup()
        for label, current, new in diff:
            row = Adw.ActionRow(title=GLib.markup_escape_text(label))
            row.set_subtitle(
                f"<span alpha='60%'>{GLib.markup_escape_text(current)}</span>"
                f"  →  {GLib.markup_escape_text(new)}"
            )
            row.set_subtitle_lines(3)
            group.add(row)

        scroller = Gtk.ScrolledWindow()
        scroller.set_min_content_height(min(len(diff) * 56, 320))
        scroller.set_max_content_height(320)
        scroller.set_propagate_natural_height(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(group)
        extra.append(scroller)
        dialog.set_extra_child(extra)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("apply", f"Apply {len(diff)} Changes")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_import_preview_response, data)
        dialog.present(self)

    def _on_import_preview_response(self, _dialog, response: str, data: dict):
        if response != "apply":
            return
        try:
            count = self._apply_import_data(data)
            self._show_toast(f"{count} settings restored")
        except Exception as exc:
            _log.warning("Import failed", exc_info=True)
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
                _log.debug("Import: skipped %s::%s", schema_str, key, exc_info=True)
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
                    _log.debug("Import: skipped extension key %s", key, exc_info=True)
                    continue

        return count

    def _refresh_all_sections(self):
        """Refresh every section so they reflect newly imported values."""
        self.refresh_rows()
        self.animation_section.refresh()
        self.topbar_section.refresh()
        self.tiling_section.refresh()
        self.touchpad_section.refresh()
