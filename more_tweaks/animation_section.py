from __future__ import annotations

import copy
import logging
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .animation_preview import AnimationPreviewWidget  # noqa: E402
from .animations import AnimationBackend  # noqa: E402
from .animation_catalog import BINDING_DEFINITIONS, PER_APP_ACTIONS  # noqa: E402
from .custom_presets import CustomPresetStore, DEFAULT_BLANK_PRESET  # noqa: E402
from .preset_data import TRANSFORM_PRESETS  # noqa: E402
from .timeline_widget import AnimationTimelineWidget  # noqa: E402
from ._shared import (  # noqa: E402
    _ScrollPreservingSection,
    _build_runtime_status,
    _build_status_page,
    _check_capability,
    _clear_box,
)

_log = logging.getLogger("more_tweaks.animation_section")


class AnimationSection(_ScrollPreservingSection):
    @property
    def backend(self):
        return self._animation_backend

    def __init__(self, notify: Callable[[str], None] | None = None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, notify=notify)
        self.set_margin_bottom(48)
        self.custom_presets = CustomPresetStore()
        self.desktop_settings = Gio.Settings.new("org.gnome.desktop.interface")
        self._expanded_bindings: set[str] = set()

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

        # Runtime status — compact display (banner/row only when action needed)
        for w in _build_runtime_status(
            self.backend,
            on_install=self._on_install_runtime,
            on_enable_changed=self._on_enable_runtime,
            feature_label="Animation controls",
        ):
            self.append(w)

        # GNOME animations-off warning (separate from runtime status)
        if not self.desktop_settings.get_boolean("enable-animations"):
            warn_group = Adw.PreferencesGroup()
            warn_row = Adw.ActionRow(
                title="GNOME animations are off",
                subtitle="The desktop-wide animation switch is disabled. "
                         "GNOME Shell may suppress visible motion.",
            )
            warn_label = Gtk.Label(label="Blocking")
            warn_label.add_css_class("dim-label")
            warn_row.add_suffix(warn_label)
            warn_group.add(warn_row)
            self.append(warn_group)

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
        for group in self._build_custom_presets_group():
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

    def _build_custom_presets_group(self) -> list[Adw.PreferencesGroup]:
        """Group B2: Custom Presets -- create and manage custom animation presets."""
        custom_names = self.custom_presets.preset_names()
        if not custom_names:
            group = Adw.PreferencesGroup(
                title="Custom Presets",
                description="Create your own animation presets from scratch or by cloning existing ones.",
            )
            group.set_margin_top(12)
            group.set_margin_start(12)
            group.set_margin_end(12)
        else:
            group = Adw.PreferencesGroup(
                title="Custom Presets",
                description=f"{len(custom_names)} custom preset{'s' if len(custom_names) != 1 else ''}.",
            )
            group.set_margin_top(12)
            group.set_margin_start(12)
            group.set_margin_end(12)

            for name in custom_names:
                data = self.custom_presets.get_preset(name) or {}
                family = data.get("family", "Custom")
                n_phases = len(data.get("phases", []))
                row = Adw.ActionRow(title=name)
                row.set_subtitle(f"{family} family, {n_phases} phase{'s' if n_phases != 1 else ''}")

                btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

                edit_btn = Gtk.Button.new_from_icon_name("document-edit-symbolic")
                edit_btn.set_valign(Gtk.Align.CENTER)
                edit_btn.add_css_class("flat")
                edit_btn.set_tooltip_text("Edit preset")
                edit_btn.connect("clicked", lambda _b, n=name: self._show_preset_editor(n))
                btn_box.append(edit_btn)

                delete_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
                delete_btn.set_valign(Gtk.Align.CENTER)
                delete_btn.add_css_class("flat")
                delete_btn.set_tooltip_text("Delete preset")
                delete_btn.connect("clicked", lambda _b, n=name: self._on_delete_custom_preset(n))
                btn_box.append(delete_btn)

                row.add_suffix(btn_box)
                group.add(row)

        create_row = Adw.ActionRow(title="Create new preset")
        create_row.set_subtitle("Start with a blank fade-in animation")
        create_btn = Gtk.Button.new_from_icon_name("list-add-symbolic")
        create_btn.set_valign(Gtk.Align.CENTER)
        create_btn.add_css_class("flat")
        create_btn.set_tooltip_text("Create a new custom preset")
        create_btn.connect("clicked", self._on_create_preset_clicked)
        create_row.add_suffix(create_btn)
        group.add(create_row)

        return [group]

    def _on_create_preset_clicked(self, _button):
        name = "New Preset"
        suffix = 1
        while not self.custom_presets.name_is_available(name):
            suffix += 1
            name = f"New Preset {suffix}"
        self.custom_presets.create_preset(name, copy.deepcopy(DEFAULT_BLANK_PRESET))
        self.backend.bump_custom_presets_version()
        self._toast(f"Created custom preset '{name}'")
        self._show_preset_editor(name)

    def _on_delete_custom_preset(self, preset_name: str):
        self._update_bindings_after_delete(preset_name)
        self.custom_presets.delete_preset(preset_name)
        self.backend.bump_custom_presets_version()
        self._toast(f"Deleted custom preset '{preset_name}'")
        self.refresh()

    def _update_bindings_after_rename(self, old_name: str, new_name: str):
        for binding_def in BINDING_DEFINITIONS:
            current = self.backend.get_binding_preset(
                binding_def.preset_key, binding_def.default_preset)
            if current == old_name:
                self.backend.set_binding_preset(binding_def.preset_key, new_name)
        overrides = self.backend.get_per_app_overrides()
        changed = False
        for entry in overrides:
            for _action, rule in entry.get("rules", {}).items():
                if rule.get("preset") == old_name:
                    rule["preset"] = new_name
                    changed = True
        if changed:
            self.backend.set_per_app_overrides(overrides)

    def _update_bindings_after_delete(self, deleted_name: str):
        for binding_def in BINDING_DEFINITIONS:
            current = self.backend.get_binding_preset(
                binding_def.preset_key, binding_def.default_preset)
            if current == deleted_name:
                self.backend.set_binding_preset(
                    binding_def.preset_key, binding_def.default_preset)
        overrides = self.backend.get_per_app_overrides()
        changed = False
        for entry in overrides:
            for _action, rule in entry.get("rules", {}).items():
                if rule.get("preset") == deleted_name:
                    rule["preset"] = "Glide In"
                    changed = True
        if changed:
            self.backend.set_per_app_overrides(overrides)

    def _build_diagnostics_group(self) -> list[Adw.PreferencesGroup]:
        """Group C: Diagnostics -- informational rows and maintenance actions."""
        group = Adw.PreferencesGroup(
            title="Diagnostics",
            description="Informational rows, debug controls, and maintenance actions.",
        )

        # Runtime source (informational)
        source_row = Adw.ActionRow(title="Runtime source")
        source_row.set_subtitle(
            "This animation runtime ships inside More Tweaks as a bundled GNOME Shell extension."
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

        # Runtime enable/disable switch (power-user toggle)
        enable_row = Adw.ActionRow(title="Bundled runtime enabled")
        enable_row.set_subtitle("Manually enable or disable the GNOME Shell extension.")
        enable_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        enable_switch.set_active(self.backend.runtime_enabled)
        enable_switch.connect(
            "notify::active",
            lambda sw, _pspec: self._on_enable_runtime(sw.get_active()),
        )
        enable_row.add_suffix(enable_switch)
        group.add(enable_row)

        # Restore defaults button
        defaults_row = Adw.ActionRow(title="Restore system defaults")
        defaults_row.set_subtitle(
            "Reset animation overrides back to GNOME's stock behavior."
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
        if binding.spec.id in self._expanded_bindings:
            row.set_expanded(True)
        row.connect("notify::expanded", self._on_binding_row_expanded, binding.spec.id)
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
        duration_row.set_activatable(False)
        duration_row.set_subtitle("Visible timing for this binding.")
        duration_spin = Gtk.SpinButton.new_with_range(80, 1200, 10)
        duration_spin.set_valign(Gtk.Align.CENTER)
        duration_spin.set_value(binding.duration_ms)
        duration_spin.connect("value-changed", self._on_binding_duration_changed, binding.spec.duration_key)
        duration_row.add_suffix(duration_spin)
        row.add_row(duration_row)

        delay_row = Adw.ActionRow(title="Delay")
        delay_row.set_activatable(False)
        delay_row.set_subtitle("Hidden advanced control for staggering motion.")
        delay_spin = Gtk.SpinButton.new_with_range(0, 600, 10)
        delay_spin.set_valign(Gtk.Align.CENTER)
        delay_spin.set_value(binding.delay_ms)
        delay_spin.connect("value-changed", self._on_binding_delay_changed, binding.spec.delay_key)
        delay_row.add_suffix(delay_spin)
        row.add_row(delay_row)

        intensity_row = Adw.ActionRow(title="Intensity")
        intensity_row.set_activatable(False)
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
        timeline_row.set_activatable(False)
        timeline_row.set_subtitle("Phase breakdown for this preset.")
        timeline = AnimationTimelineWidget()
        timeline.update(binding.preset_name, binding.duration_ms, binding.delay_ms, binding.intensity)
        timeline_row.add_suffix(timeline)
        row.add_row(timeline_row)

        return row

    def _on_shell_animations_changed(self, switch: Gtk.Switch, _pspec):
        self.desktop_settings.set_boolean("enable-animations", switch.get_active())
        self._toast(
            "GNOME interface animations enabled"
            if switch.get_active()
            else "GNOME interface animations disabled"
        )
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
            _log.warning("Could not open log snapshot", exc_info=True)
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
            preset = self.custom_presets.to_transform_preset(preset_name)
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
            preset = self.custom_presets.to_transform_preset(preset_name)
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

        dialog = Adw.Dialog(title="Edit Preset")
        dialog.set_content_width(480)
        dialog.set_content_height(640)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Name entry
        name_group = Adw.PreferencesGroup()
        name_entry = Adw.EntryRow(title="Preset Name")
        name_entry.set_text(preset_name)
        name_group.add(name_entry)
        box.append(name_group)

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
            ("rotationY", "Rotation Y", -180.0, 180.0, 0.5, setup.get("rotationY", 0.0)),
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

        # Phase data and widgets (mutable lists for dynamic add/remove)
        easing_options = ["EASE_OUT_CUBIC", "EASE_IN_CUBIC", "EASE_OUT_QUAD", "EASE_IN_QUAD", "EASE_OUT_BOUNCE", "LINEAR"]
        phase_data_list = [dict(p) for p in data.get("phases", [])]
        phase_widgets: list[dict] = []

        phase_defaults = {
            "opacity": 255, "scaleX": 1.0, "scaleY": 1.0,
            "translationX": 0.0, "translationY": 0.0, "rotationZ": 0.0,
        }

        phases_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(phases_container)

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

        # --- Name validation ---
        def _on_name_changed(_entry):
            text = name_entry.get_text().strip()
            valid = self.custom_presets.name_is_available(text, exclude=preset_name)
            if valid:
                name_entry.remove_css_class("error")
                save_btn.set_sensitive(True)
            else:
                name_entry.add_css_class("error")
                save_btn.set_sensitive(False)

        name_entry.connect("changed", _on_name_changed)

        # --- Phase rebuild ---
        def _snapshot_phases():
            """Capture current widget values back into phase_data_list before rebuild."""
            for i, pw in enumerate(phase_widgets):
                if i >= len(phase_data_list):
                    break
                for key, widget in pw.items():
                    if key == "_easing_dd":
                        sel = widget.get_selected()
                        phase_data_list[i]["mode"] = easing_options[sel] if sel < len(easing_options) else "EASE_OUT_CUBIC"
                    elif key == "opacity":
                        phase_data_list[i][key] = int(widget.get_value())
                    else:
                        phase_data_list[i][key] = widget.get_value()

        def _rebuild_phases():
            phase_widgets.clear()
            child = phases_container.get_first_child()
            while child is not None:
                next_child = child.get_next_sibling()
                phases_container.remove(child)
                child = next_child

            phase_fields = [
                ("opacity", "Opacity", 0, 255, 1),
                ("scaleX", "Scale X", 0.0, 2.0, 0.01),
                ("scaleY", "Scale Y", 0.0, 2.0, 0.01),
                ("translationX", "Translation X", -200.0, 200.0, 1.0),
                ("translationY", "Translation Y", -200.0, 200.0, 1.0),
                ("rotationZ", "Rotation Z", -180.0, 180.0, 0.5),
            ]

            for i, phase in enumerate(phase_data_list):
                phase_group = Adw.PreferencesGroup(title=f"Phase {i + 1}")
                spins = {}

                # Fill defaults for missing properties
                for key, default_val in phase_defaults.items():
                    if key not in phase:
                        phase[key] = default_val

                for key, label, lo, hi, step in phase_fields:
                    val = phase.get(key, phase_defaults.get(key, 0))
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
                ds_spin = Gtk.SpinButton.new_with_range(0.05, 2.0, 0.01)
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

                # Remove phase button
                remove_row = Adw.ActionRow(title="Remove this phase")
                remove_btn = Gtk.Button.new_from_icon_name("user-trash-symbolic")
                remove_btn.set_valign(Gtk.Align.CENTER)
                remove_btn.add_css_class("flat")
                remove_btn.add_css_class("destructive-action")
                remove_btn.set_sensitive(len(phase_data_list) > 1)
                remove_btn.connect("clicked", lambda _b, idx=i: _remove_phase(idx))
                remove_row.add_suffix(remove_btn)
                phase_group.add(remove_row)

                phases_container.append(phase_group)
                phase_widgets.append(spins)

            # Add Phase button
            add_btn = Gtk.Button(label="Add Phase")
            add_btn.set_halign(Gtk.Align.START)
            add_btn.add_css_class("pill")
            add_btn.connect("clicked", lambda _b: _add_phase())
            phases_container.append(add_btn)

            # Reconnect preview signals
            for pw in phase_widgets:
                for key, widget in pw.items():
                    if key == "_easing_dd":
                        widget.connect("notify::selected", _on_preview_update)
                    else:
                        widget.connect("value-changed", _on_preview_update)

        def _add_phase():
            _snapshot_phases()
            phase_data_list.append({
                "opacity": 255, "scaleX": 1.0, "scaleY": 1.0,
                "translationX": 0.0, "translationY": 0.0, "rotationZ": 0.0,
                "mode": "EASE_OUT_CUBIC", "durationScale": 0.5,
            })
            _rebuild_phases()
            _on_preview_update()

        def _remove_phase(index):
            _snapshot_phases()
            if len(phase_data_list) > 1:
                phase_data_list.pop(index)
            _rebuild_phases()
            _on_preview_update()

        # --- Handlers ---
        def _on_save(_btn):
            new_name = name_entry.get_text().strip()
            if not self.custom_presets.name_is_available(new_name, exclude=preset_name):
                self._toast("Invalid or conflicting preset name")
                return

            _snapshot_phases()

            new_setup = {}
            for key, spin in setup_spins.items():
                new_setup[key] = spin.get_value()
            new_setup["opacity"] = int(new_setup["opacity"])

            new_phases = []
            for pd in phase_data_list:
                p = dict(pd)
                if "opacity" in p:
                    p["opacity"] = int(p["opacity"])
                new_phases.append(p)

            new_data = {"family": data.get("family", "Custom"), "setup": new_setup, "phases": new_phases}
            if "based_on" in data:
                new_data["based_on"] = data["based_on"]

            # Handle rename
            final_name = preset_name
            if new_name != preset_name:
                if not self.custom_presets.rename_preset(preset_name, new_name):
                    self._toast(f"Could not rename to '{new_name}'")
                    return
                self._update_bindings_after_rename(preset_name, new_name)
                final_name = new_name

            self.custom_presets.update_preset(final_name, new_data)
            self.backend.bump_custom_presets_version()
            self._toast(f"Saved custom preset '{final_name}'")
            dialog.close()
            self.refresh()

        def _on_delete(_btn):
            self._update_bindings_after_delete(preset_name)
            self.custom_presets.delete_preset(preset_name)
            self.backend.bump_custom_presets_version()
            self._toast(f"Deleted custom preset '{preset_name}'")
            dialog.close()
            self.refresh()

        _CAMEL_TO_SNAKE = {
            "scaleX": "scale_x", "scaleY": "scale_y",
            "translationX": "translation_x", "translationY": "translation_y",
            "rotationZ": "rotation_z",
        }

        def _on_preview_update(*_args):
            from .preset_data import PresetPhase, PresetSetup, TransformPreset
            try:
                cur_setup = PresetSetup(
                    opacity=int(setup_spins["opacity"].get_value()),
                    scale_x=setup_spins["scaleX"].get_value(),
                    scale_y=setup_spins["scaleY"].get_value(),
                    translation_x=setup_spins["translationX"].get_value(),
                    translation_y=setup_spins["translationY"].get_value(),
                    rotation_z=setup_spins["rotationZ"].get_value(),
                    rotation_y=setup_spins["rotationY"].get_value(),
                    pivot_x=setup_spins["pivotX"].get_value(),
                    pivot_y=setup_spins["pivotY"].get_value(),
                )
                cur_phases = []
                for pw in phase_widgets:
                    p_kwargs = {}
                    for key, spin in pw.items():
                        if key == "_easing_dd":
                            sel = spin.get_selected()
                            p_kwargs["mode"] = easing_options[sel] if sel < len(easing_options) else "EASE_OUT_CUBIC"
                        elif key == "opacity":
                            p_kwargs["opacity"] = int(spin.get_value())
                        elif key == "durationScale":
                            p_kwargs["duration_scale"] = spin.get_value()
                        else:
                            p_kwargs[_CAMEL_TO_SNAKE.get(key, key)] = spin.get_value()
                    cur_phases.append(PresetPhase(**p_kwargs))
                tp = TransformPreset(
                    family=data.get("family", "Custom"),
                    setup=cur_setup,
                    phases=tuple(cur_phases),
                )
                preview.play(tp, 300, 0, 1.0)
            except Exception:
                _log.debug("Preview update failed for preset %r", preset_name, exc_info=True)

        # Connect setup spins to live preview
        for spin in setup_spins.values():
            spin.connect("value-changed", _on_preview_update)

        # Build initial phases
        _rebuild_phases()

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

    def _on_binding_row_expanded(self, row: Adw.ExpanderRow, _pspec, binding_id: str):
        if row.get_expanded():
            self._expanded_bindings.add(binding_id)
        else:
            self._expanded_bindings.discard(binding_id)

    def _on_binding_duration_changed(self, spin: Gtk.SpinButton, duration_key: str):
        if not self._prepare_runtime("update animation timing"):
            GLib.idle_add(self.refresh)
            return
        if not self.backend.set_binding_duration(duration_key, int(round(spin.get_value()))):
            self._toast("Could not update animation duration")
        GLib.idle_add(self.refresh)

    def _on_binding_delay_changed(self, spin: Gtk.SpinButton, delay_key: str):
        if not self._prepare_runtime("update animation timing"):
            GLib.idle_add(self.refresh)
            return
        if not self.backend.set_binding_delay(delay_key, int(round(spin.get_value()))):
            self._toast("Could not update animation delay")
        GLib.idle_add(self.refresh)

    def _on_binding_intensity_changed(self, spin: Gtk.SpinButton, intensity_key: str):
        if not self._prepare_runtime("update animation intensity"):
            GLib.idle_add(self.refresh)
            return
        if not self.backend.set_binding_intensity(intensity_key, float(spin.get_value())):
            self._toast("Could not update animation intensity")
        GLib.idle_add(self.refresh)

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
            self._toast("Could not restore system animation defaults")
        else:
            self._toast("System animation defaults restored")
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
