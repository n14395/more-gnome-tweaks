"""Shared helpers extracted from window.py."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .animations import AnimationBackend  # noqa: E402


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
    # Don't show capability failures when a restart is pending — the
    # reported capabilities are stale from before the update.
    if ab.needs_shell_restart:
        return None
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


def _build_runtime_status(
    backend: AnimationBackend,
    on_install: Callable[[], None],
    on_enable_changed: Callable[[bool], None],
    feature_label: str = "Extension features",
) -> list[Gtk.Widget]:
    """Build a compact runtime status display.

    Returns 0-1 widgets depending on state:
    - Running & healthy: empty list
    - Error: Adw.Banner with retry
    - Needs logout / not installed / disabled: single ActionRow with button
    """
    # Error — prominent banner
    if backend.runtime_error:
        banner = Adw.Banner(title=f"Shell runtime error: {backend.runtime_error}")
        banner.set_button_label("Retry")
        banner.set_revealed(True)
        banner.connect("button-clicked", lambda _b: on_install())
        return [banner]

    # Needs restart after install
    if backend.needs_shell_restart:
        group = Adw.PreferencesGroup()
        row = Adw.ActionRow(
            title="Log out required",
            subtitle="The runtime is installed but GNOME Shell hasn't detected it yet. "
                     "Log out and log back in.",
        )
        icon = Gtk.Image.new_from_icon_name("system-log-out-symbolic")
        icon.add_css_class("dim-label")
        row.add_prefix(icon)
        group.add(row)
        return [group]

    # Not installed
    if not backend.available:
        group = Adw.PreferencesGroup()
        row = Adw.ActionRow(
            title="Shell runtime not installed",
            subtitle=f"{feature_label} require the bundled GNOME Shell extension.",
        )
        btn = Gtk.Button(label="Install")
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda _b: on_install())
        row.add_suffix(btn)
        icon = Gtk.Image.new_from_icon_name("application-x-addon-symbolic")
        icon.add_css_class("dim-label")
        row.add_prefix(icon)
        group.add(row)
        return [group]

    # Installed but disabled
    if not backend.runtime_enabled:
        group = Adw.PreferencesGroup()
        row = Adw.ActionRow(
            title="Shell runtime disabled",
            subtitle="The extension is installed but not enabled.",
        )
        btn = Gtk.Button(label="Enable")
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda _b: on_enable_changed(True))
        row.add_suffix(btn)
        group.add(row)
        return [group]

    # Running but update available
    if backend.update_available:
        group = Adw.PreferencesGroup()
        row = Adw.ActionRow(
            title="Runtime update available",
            subtitle=f"Installed version {backend.installed_version} → "
                     f"bundled version {backend.bundled_version}. "
                     "Update and log out to apply.",
        )
        btn = Gtk.Button(label="Update")
        btn.add_css_class("suggested-action")
        btn.add_css_class("pill")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", lambda _b: on_install())
        row.add_suffix(btn)
        icon = Gtk.Image.new_from_icon_name("software-update-available-symbolic")
        icon.add_css_class("dim-label")
        row.add_prefix(icon)
        group.add(row)
        return [group]

    # Running and up to date — nothing to show
    return []


class _ScrollPreservingSection(Gtk.Box):
    """Base class for sections that rebuild their widget tree on refresh.

    Saves and restores the nearest ancestor ScrolledWindow's scroll
    position around each rebuild so the viewport doesn't jump to the top.
    Provides shared runtime management (install/enable/toast) so subclasses
    don't duplicate it.
    """

    def __init__(self, *args, notify: Callable[[str], None] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._notify = notify
        self._animation_backend = AnimationBackend()

    def _toast(self, message: str):
        if self._notify:
            self._notify(message)

    def _save_scroll(self) -> tuple[Gtk.ScrolledWindow | None, float]:
        sw = _find_ancestor_scrolled_window(self)
        return (sw, sw.get_vadjustment().get_value()) if sw else (None, 0.0)

    @staticmethod
    def _restore_scroll(sw: Gtk.ScrolledWindow | None, pos: float):
        if sw is None:
            return
        GLib.idle_add(lambda: (sw.get_vadjustment().set_value(pos), False)[-1])

    def _on_install_runtime(self):
        if not self._animation_backend.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        self._toast("Bundled More Tweaks runtime installed")
        self.refresh()

    def _on_enable_runtime(self, enabled: bool):
        ab = self._animation_backend
        if enabled and not ab.available and not ab.install_runtime():
            self._toast("Could not install the bundled More Tweaks runtime")
            self.refresh()
            return
        success = ab.enable_runtime() if enabled else ab.disable_runtime()
        self._toast(
            "Bundled More Tweaks runtime enabled"
            if success and enabled
            else "Bundled More Tweaks runtime disabled"
        )
        self.refresh()
