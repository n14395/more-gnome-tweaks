<p align="center">
  <img src="data/icons/hicolor/scalable/apps/com.n14395.MoreTweaks.svg" width="192" alt="More Tweaks icon"/>
</p>

# More Tweaks

A GTK4 + libadwaita app that surfaces hidden GNOME settings through a single searchable interface — no `dconf-editor` or terminal needed.

300+ tweaks across 18 categories (plus 6 app sub-categories), with a bundled GNOME Shell extension for window animations, top bar customization, and touchpad gestures.

## Features

- **Global search** across all tweak names, descriptions, schemas, keys, and tags — tags are search-only and never shown in the UI
- **18 categories** — Desktop, Top Bar, Animations, Windows, Input, Themes, Privacy, Power, Apps, and more
- **Collapsible Apps category** with per-app sub-categories (Console, Terminal, Web, Screenshot, Clocks, Text Editor)
- **Extension manager** — toggle installed GNOME Shell extensions on/off and uninstall user extensions with a confirmation dialog
- **Top bar panel reordering** — drag-and-drop items between the left, center, and right zones of the GNOME top bar
- **Touchpad gesture mapping** — assign custom actions to three- and four-finger swipe gestures
- **Bundled GNOME Shell extension** — a self-managed runtime that powers:
  - 58 animation presets, 5 curated profiles, per-animation tuning, and per-app overrides
  - System animation timing overrides (overview, Show Applications transition, app grid, workspace switch, app folders, OSD popups)
  - Top bar zone reordering
  - Custom touchpad gesture bindings
- **In-app animation preview** and timeline visualization for each binding
- **Live external change detection** — UI auto-refreshes when settings change outside the app
- **Reset to default** and **copy gsettings command** for every tweak

## Installation

### Flatpak (recommended)

Download the `.flatpak` bundle from the [Releases](https://github.com/n14395/more-gnome-tweaks/releases) page:

```bash
flatpak install --user flathub org.gnome.Platform//50
flatpak install --user MoreTweaks-1.1.0-x86_64.flatpak
flatpak run com.n14395.MoreTweaks
```

### From source

Requires Python 3.12+, PyGObject, GTK 4, and libadwaita 1.

```bash
# Debian/Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita

# Arch
sudo pacman -S python-gobject gtk4 libadwaita
```

```bash
pip install .
more-tweaks

# Or run directly without installing:
python3 -m more_tweaks
```

## Building

### Flatpak

```bash
flatpak install --user flathub org.gnome.Sdk//50
flatpak-builder --user --force-clean --repo=flatpak-repo flatpak-build com.n14395.MoreTweaks.yml
flatpak build-bundle flatpak-repo MoreTweaks-1.1.0-x86_64.flatpak com.n14395.MoreTweaks \
  --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo
```

## Testing

```bash
cd src
python3 -m pytest tests/ -v
```

## License

[GNU General Public License v3.0 or later](LICENSE) (GPL-3.0-or-later)
