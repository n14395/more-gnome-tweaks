<p align="center">
  <img src="data/icons/hicolor/scalable/apps/com.n14395.MoreTweaks.svg" width="128" alt="More Tweaks icon"/>
</p>

<h1 align="center">More Tweaks</h1>

<p align="center">
A GTK4 + libadwaita app that surfaces hidden GNOME settings through a single searchable interface.<br>
328 tweaks, 26 categories, and a bundled GNOME Shell extension for animations, tiling, and more.
</p>

## Highlights

- **Full-text search** across names, descriptions, schemas, keys, and tags
- **Settings export/import** with diff preview before applying
- **Bundled GNOME Shell extension** (GNOME 45-49) providing:
  - 65 animation presets across 5 curated profiles with per-binding tuning
  - Physics-based interactive effects (wobbly move, spring snap, rubber stretch)
  - Custom preset authoring with live preview, phase editing, and looping playback
  - Per-app animation overrides
  - System animation timing control (overview, workspace switch, OSD, app grid)
  - Top bar zone reordering, tiling grid, and touchpad gesture mapping
- **Preferences dialog** for controlling tweak visibility, reset confirmation, export defaults, and startup behavior
- **Rich controls** including font picker, color picker, theme selector, keybinding recorder, and extension manager

## Install

### Flatpak

```bash
flatpak install --user MoreTweaks-0.2-x86_64.flatpak
flatpak run com.n14395.MoreTweaks
```

Download from [Releases](https://github.com/n14395/more-gnome-tweaks/releases).

### From source

Requires Python 3.12+, PyGObject, GTK 4, libadwaita 1.

```bash
# Arch
sudo pacman -S python-gobject gtk4 libadwaita

# Fedora
sudo dnf install python3-gobject gtk4 libadwaita

# Debian/Ubuntu
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

```bash
python3 -m more_tweaks
```

## Build Flatpak

```bash
flatpak install --user flathub org.gnome.Sdk//50
flatpak-builder --user --force-clean --repo=flatpak-repo flatpak-build com.n14395.MoreTweaks.yml
flatpak build-bundle flatpak-repo MoreTweaks-0.2-x86_64.flatpak com.n14395.MoreTweaks \
  --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo
```

## Test

```bash
cd src && python3 -m pytest tests/ -v
```

## License

[GPL-3.0-or-later](LICENSE)
