from __future__ import annotations

import importlib.metadata
import logging
import os

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gio, Gtk

from .window import MoreTweaksWindow


APP_ID = "com.n14395.MoreTweaks"


class MoreTweaksApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Adw.Application.do_startup(self)

        # Configure logging — DEBUG when MORE_TWEAKS_DEBUG=1, WARNING otherwise
        level = logging.DEBUG if os.environ.get("MORE_TWEAKS_DEBUG") == "1" else logging.WARNING
        logging.basicConfig(
            format="%(name)s: %(levelname)s: %(message)s",
            level=level,
        )
        logging.getLogger("more_tweaks").setLevel(level)

        # Register bundled icon so it resolves when running from source
        from pathlib import Path
        icons_dir = Path(__file__).resolve().parent.parent / "data" / "icons"
        if icons_dir.is_dir():
            Gtk.IconTheme.get_for_display(
                __import__("gi").repository.Gdk.Display.get_default()
            ).add_search_path(str(icons_dir))

        # Ctrl+Q → quit
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

        # About dialog
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        # Keyboard shortcuts dialog
        shortcuts_action = Gio.SimpleAction.new("shortcuts", None)
        shortcuts_action.connect("activate", self._on_shortcuts)
        self.add_action(shortcuts_action)
        self.set_accels_for_action("app.shortcuts", ["<Control>question"])

        # Ctrl+F → focus search
        search_action = Gio.SimpleAction.new("search", None)
        search_action.connect("activate", self._on_search)
        self.add_action(search_action)
        self.set_accels_for_action("app.search", ["<Control>f"])

        # Ctrl+R → reset focused tweak to default
        reset_action = Gio.SimpleAction.new("reset-focused", None)
        reset_action.connect("activate", self._on_reset_focused)
        self.add_action(reset_action)
        self.set_accels_for_action("app.reset-focused", ["<Control>r"])

        # Reset all settings
        reset_all_action = Gio.SimpleAction.new("reset-all", None)
        reset_all_action.connect("activate", self._on_reset_all)
        self.add_action(reset_all_action)

        # Ctrl+Shift+F → toggle sidebar
        sidebar_action = Gio.SimpleAction.new("toggle-sidebar", None)
        sidebar_action.connect("activate", self._on_toggle_sidebar)
        self.add_action(sidebar_action)
        self.set_accels_for_action("app.toggle-sidebar", ["<Control><Shift>f"])

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            window = MoreTweaksWindow(self)
        window.present()

    def _on_about(self, _action, _param):
        about = Adw.AboutWindow(
            application_name="More Tweaks",
            application_icon=APP_ID,
            version=importlib.metadata.version("more-tweaks"),
            developer_name="n14395",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/n14395/more-gnome-tweaks",
            issue_url="https://github.com/n14395/more-gnome-tweaks/issues",
            developers=["n14395"],
            copyright="2026 n14395",
            comments="A GTK4 + libadwaita app that surfaces hidden GNOME settings through a single searchable interface.",
            transient_for=self.props.active_window,
        )
        about.present()

    def _on_shortcuts(self, _action, _param):
        builder = Gtk.Builder()
        builder.add_from_string(_SHORTCUTS_UI)
        window = builder.get_object("shortcuts")
        window.set_transient_for(self.props.active_window)
        window.present()

    def _on_search(self, _action, _param):
        window = self.props.active_window
        if window is not None and hasattr(window, "search_entry"):
            window.search_entry.grab_focus()

    def _on_reset_focused(self, _action, _param):
        window = self.props.active_window
        if window is not None and hasattr(window, "reset_focused_tweak"):
            window.reset_focused_tweak()

    def _on_reset_all(self, _action, _param):
        window = self.props.active_window
        if window is not None and hasattr(window, "reset_all_settings"):
            window.reset_all_settings()

    def _on_toggle_sidebar(self, _action, _param):
        window = self.props.active_window
        if window is not None and hasattr(window, "toggle_sidebar"):
            window.toggle_sidebar()


_SHORTCUTS_UI = """<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <object class="GtkShortcutsWindow" id="shortcuts">
    <property name="modal">true</property>
    <child>
      <object class="GtkShortcutsSection">
        <property name="section-name">shortcuts</property>
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">General</property>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">Search tweaks</property>
                <property name="accelerator">&lt;Control&gt;f</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">Keyboard shortcuts</property>
                <property name="accelerator">&lt;Control&gt;question</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">Reset focused tweak</property>
                <property name="accelerator">&lt;Control&gt;r</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">Toggle sidebar</property>
                <property name="accelerator">&lt;Control&gt;&lt;Shift&gt;f</property>
              </object>
            </child>
            <child>
              <object class="GtkShortcutsShortcut">
                <property name="title">Quit</property>
                <property name="accelerator">&lt;Control&gt;q</property>
              </object>
            </child>
          </object>
        </child>
      </object>
    </child>
  </object>
</interface>
"""


def main() -> int:
    app = MoreTweaksApplication()
    return app.run(None)
