from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")

from gi.repository import Gio, GLib

from .animation_catalog import (
    BINDING_DEFINITIONS,
    BINDINGS_BY_ID,
    GROUP_DEFINITIONS,
    GROUPS_BY_ID,
    PROFILE_DEFAULTS,
    PROFILE_NAMES,
    BindingDefinition,
)


SCHEMA_ID = "com.n14395.more-tweaks.shell"
EXTENSION_UUID = "more-tweaks-shell@n14395.github.com"
EXTENSION_NAME = "More Tweaks Shell Runtime"

PACKAGE_ROOT = Path(__file__).resolve().parent
BUNDLED_EXTENSION_PATH = PACKAGE_ROOT / "bundled_extension"

# Use pwd to get the real home directory — Path.home() returns the sandboxed
# home inside Flatpak, but the extension must be installed to the host.
_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
INSTALLED_EXTENSION_PATH = _REAL_HOME / ".local/share/gnome-shell/extensions" / EXTENSION_UUID


@dataclass(frozen=True, slots=True)
class AnimationBindingSpec:
    id: str
    title: str
    summary: str
    target: str
    action: str
    tier: str
    enabled_key: str
    preset_key: str
    duration_key: str
    delay_key: str
    intensity_key: str
    preset_names: tuple[str, ...]
    default_preset: str
    default_duration_ms: int
    default_delay_ms: int
    default_intensity: float


@dataclass(frozen=True, slots=True)
class AnimationGroupSpec:
    id: str
    title: str
    summary: str
    bindings: tuple[AnimationBindingSpec, ...]


@dataclass(frozen=True, slots=True)
class AnimationBindingState:
    spec: AnimationBindingSpec
    enabled: bool
    preset_name: str
    duration_ms: int
    delay_ms: int
    intensity: float
    preset_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnimationGroupState:
    spec: AnimationGroupSpec
    bindings: tuple[AnimationBindingState, ...]


def _binding_spec(definition: BindingDefinition) -> AnimationBindingSpec:
    return AnimationBindingSpec(
        id=definition.id,
        title=definition.title,
        summary=definition.summary,
        target=definition.target,
        action=definition.action,
        tier=definition.tier,
        enabled_key=definition.enabled_key,
        preset_key=definition.preset_key,
        duration_key=definition.duration_key,
        delay_key=definition.delay_key,
        intensity_key=definition.intensity_key,
        preset_names=definition.preset_names,
        default_preset=definition.default_preset,
        default_duration_ms=definition.default_duration_ms,
        default_delay_ms=definition.default_delay_ms,
        default_intensity=definition.default_intensity,
    )


GROUP_SPECS: tuple[AnimationGroupSpec, ...] = tuple(
    AnimationGroupSpec(
        id=group.id,
        title=group.title,
        summary=group.summary,
        bindings=tuple(
            _binding_spec(binding)
            for binding in BINDING_DEFINITIONS
            if binding.group_id == group.id
        ),
    )
    for group in GROUP_DEFINITIONS
)


class AnimationBackend:
    def __init__(self):
        self.extension_path = INSTALLED_EXTENSION_PATH if INSTALLED_EXTENSION_PATH.is_dir() else None
        self._schema = self._load_schema()
        self._settings = (
            Gio.Settings.new_full(self._schema, None, None) if self._schema is not None else None
        )
        self._extension_info_cache: dict[str, object] | None = None

    def _reload_schema(self):
        self.extension_path = INSTALLED_EXTENSION_PATH if INSTALLED_EXTENSION_PATH.is_dir() else None
        self._schema = self._load_schema()
        self._settings = (
            Gio.Settings.new_full(self._schema, None, None) if self._schema is not None else None
        )

    def _load_schema(self) -> Gio.SettingsSchema | None:
        if self.extension_path is None:
            return None

        schema_dir = self.extension_path / "schemas"
        if not schema_dir.is_dir():
            return None

        source = Gio.SettingsSchemaSource.new_from_directory(
            str(schema_dir),
            Gio.SettingsSchemaSource.get_default(),
            False,
        )
        return source.lookup(SCHEMA_ID, False)

    @property
    def available(self) -> bool:
        return self._settings is not None

    @property
    def runtime_available(self) -> bool:
        return self.runtime_enabled and self.extension_state == 1

    @property
    def extension_state(self) -> int | None:
        value = self.extension_info.get("state")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def runtime_enabled(self) -> bool:
        value = self.extension_info.get("enabled")
        return bool(value) if isinstance(value, bool) else False

    @property
    def runtime_error(self) -> str:
        value = self.extension_info.get("error")
        return value if isinstance(value, str) else ""

    @property
    def extension_info(self) -> dict[str, object]:
        if self._extension_info_cache is None:
            self._extension_info_cache = self._load_extension_info()
        return self._extension_info_cache

    @property
    def status_text(self) -> str:
        if self.extension_path is None:
            return "Bundled More Tweaks shell runtime is not installed yet"
        if self._settings is None:
            return "Bundled runtime is installed, but its schema failed to load"
        if not self.extension_info:
            return "Bundled runtime files are installed locally, but GNOME Shell has not detected them yet"
        if self.runtime_error:
            return f"Bundled runtime error: {self.runtime_error}"
        return "Bundled More Tweaks shell runtime is installed"

    def refresh_runtime_state(self):
        self._extension_info_cache = self._load_extension_info()
        self._reload_schema()

    def _get_extensions_proxy(self) -> Gio.DBusProxy | None:
        try:
            return Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.gnome.Shell.Extensions",
                "/org/gnome/Shell/Extensions",
                "org.gnome.Shell.Extensions",
                None,
            )
        except Exception:
            return None

    def _load_extension_info(self) -> dict[str, object]:
        proxy = self._get_extensions_proxy()
        if proxy is None:
            return {}
        try:
            result = proxy.call_sync(
                "GetExtensionInfo",
                GLib.Variant("(s)", (EXTENSION_UUID,)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception:
            return {}
        if result is None:
            return {}
        return dict(result.unpack()[0])

    def _call_extension_method(self, method: str) -> bool:
        proxy = self._get_extensions_proxy()
        if proxy is None:
            return False
        try:
            result = proxy.call_sync(
                method,
                GLib.Variant("(s)", (EXTENSION_UUID,)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
        except Exception:
            return False
        self.refresh_runtime_state()
        if result is None:
            return False
        unpacked = result.unpack()
        return bool(unpacked[0]) if unpacked else False

    @property
    def installed_on_disk(self) -> bool:
        return (INSTALLED_EXTENSION_PATH / "metadata.json").is_file()

    @staticmethod
    def _read_metadata_version(path: Path) -> int:
        """Read the integer 'version' field from a metadata.json, or 0."""
        try:
            return int(json.loads((path / "metadata.json").read_text()).get("version", 0))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return 0

    @property
    def bundled_version(self) -> int:
        return self._read_metadata_version(BUNDLED_EXTENSION_PATH)

    @property
    def installed_version(self) -> int:
        return self._read_metadata_version(INSTALLED_EXTENSION_PATH)

    @property
    def update_available(self) -> bool:
        """True when the installed version is older than the bundled one."""
        return self.installed_on_disk and self.installed_version < self.bundled_version

    @property
    def needs_shell_restart(self) -> bool:
        if getattr(self, "_force_restart", False):
            return True
        return self.installed_on_disk and not self.extension_info

    def install_runtime(self) -> bool:
        if not BUNDLED_EXTENSION_PATH.is_dir():
            return False
        try:
            # Build a zip bundle and use gnome-extensions install --force
            # so GNOME Shell discovers the extension without a full restart.
            import tempfile
            import zipfile
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                zip_path = tmp.name
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in BUNDLED_EXTENSION_PATH.rglob("*"):
                    if file.is_file() and "__pycache__" not in file.parts:
                        zf.write(file, file.relative_to(BUNDLED_EXTENSION_PATH))
            subprocess.run(
                ["gnome-extensions", "install", "--force", zip_path],
                check=True,
                capture_output=True,
                text=True,
            )
            Path(zip_path).unlink(missing_ok=True)

            # Compile schemas at the installed location
            if INSTALLED_EXTENSION_PATH.is_dir():
                subprocess.run(
                    ["glib-compile-schemas", str(INSTALLED_EXTENSION_PATH / "schemas")],
                    check=True,
                    capture_output=True,
                    text=True,
                )

            # Enable the extension via gnome-extensions CLI
            subprocess.run(
                ["gnome-extensions", "enable", EXTENSION_UUID],
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            # Fallback: direct file copy (e.g. gnome-extensions CLI missing)
            try:
                INSTALLED_EXTENSION_PATH.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(BUNDLED_EXTENSION_PATH, INSTALLED_EXTENSION_PATH, dirs_exist_ok=True)
                subprocess.run(
                    ["glib-compile-schemas", str(INSTALLED_EXTENSION_PATH / "schemas")],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                shell_settings = Gio.Settings.new("org.gnome.shell")
                enabled_extensions = list(shell_settings.get_strv("enabled-extensions"))
                if EXTENSION_UUID not in enabled_extensions:
                    enabled_extensions.append(EXTENSION_UUID)
                    shell_settings.set_strv("enabled-extensions", enabled_extensions)
            except (OSError, shutil.Error, subprocess.CalledProcessError):
                return False
        self.refresh_runtime_state()
        # GNOME Shell must restart to pick up the updated extension code,
        # even when the extension was already known to the shell.  Clear any
        # stale panel-items-available data so the UI shows "restart required"
        # instead of items from the old extension version.
        self._force_restart = True
        self._set_string("panel-items-available", "")
        return self.available

    def enable_runtime(self) -> bool:
        return self._call_extension_method("EnableExtension")

    def disable_runtime(self) -> bool:
        return self._call_extension_method("DisableExtension")

    def restart_runtime(self) -> bool:
        if not self.available and not self.install_runtime():
            return False
        if not self.runtime_enabled:
            return self.enable_runtime()
        disabled = self.disable_runtime()
        enabled = self.enable_runtime()
        return disabled and enabled

    def _has_key(self, key: str) -> bool:
        return self._schema is not None and self._schema.has_key(key)

    def _get_boolean(self, key: str, default: bool = False) -> bool:
        if self._settings is None or not self._has_key(key):
            return default
        return self._settings.get_boolean(key)

    def _set_boolean(self, key: str, value: bool) -> bool:
        if self._settings is None or not self._has_key(key):
            return False
        return self._settings.set_boolean(key, value)

    def _get_string(self, key: str, default: str = "") -> str:
        if self._settings is None or not self._has_key(key):
            return default
        return self._settings.get_string(key)

    def _set_string(self, key: str, value: str) -> bool:
        if self._settings is None or not self._has_key(key):
            return False
        return self._settings.set_string(key, value)

    def _get_int(self, key: str, default: int = 0) -> int:
        if self._settings is None or not self._has_key(key):
            return default
        return self._settings.get_int(key)

    def _set_int(self, key: str, value: int) -> bool:
        if self._settings is None or not self._has_key(key):
            return False
        return self._settings.set_int(key, value)

    def _get_double(self, key: str, default: float = 1.0) -> float:
        if self._settings is None or not self._has_key(key):
            return default
        return self._settings.get_double(key)

    def _set_double(self, key: str, value: float) -> bool:
        if self._settings is None or not self._has_key(key):
            return False
        return self._settings.set_double(key, value)

    # ── Version detection & capability reporting ─────────────────────

    def get_detected_shell_version(self) -> int:
        """Return the GNOME Shell major version, or 0 if unknown.

        Prefers the value reported by the extension via GSettings.
        Falls back to parsing ``gnome-shell --version``.
        """
        ver_str = self._get_string("detected-shell-version", "")
        if ver_str:
            try:
                return int(ver_str)
            except ValueError:
                pass
        return self._detect_shell_version_from_cli()

    @staticmethod
    def _detect_shell_version_from_cli() -> int:
        """Parse GNOME Shell version from CLI.  Returns major version or 0."""
        try:
            result = subprocess.run(
                ["gnome-shell", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            for word in result.stdout.split():
                if word and word[0].isdigit():
                    return int(word.split(".")[0])
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            pass
        return 0

    def get_active_capabilities(self) -> dict[str, bool]:
        """Return the capabilities reported by the running extension."""
        import json
        raw = self._get_string("active-capabilities", "")
        if not raw:
            return {}
        try:
            caps = json.loads(raw)
            return {k: bool(v) for k, v in caps.items()}
        except (json.JSONDecodeError, TypeError):
            return {}

    def is_capability_available(self, capability: str) -> bool:
        """Check if a specific extension capability is active."""
        caps = self.get_active_capabilities()
        return caps.get(capability, False)

    def _binding_state(self, spec: AnimationBindingSpec) -> AnimationBindingState:
        return AnimationBindingState(
            spec=spec,
            enabled=self._get_boolean(spec.enabled_key, True),
            preset_name=self._get_string(spec.preset_key, spec.default_preset),
            duration_ms=self._get_int(spec.duration_key, spec.default_duration_ms),
            delay_ms=self._get_int(spec.delay_key, spec.default_delay_ms),
            intensity=self._get_double(spec.intensity_key, spec.default_intensity),
            preset_names=spec.preset_names,
        )

    def get_group_states(self) -> tuple[AnimationGroupState, ...]:
        return tuple(
            AnimationGroupState(
                spec=spec,
                bindings=tuple(self._binding_state(binding) for binding in spec.bindings),
            )
            for spec in GROUP_SPECS
        )

    def get_active_profile(self) -> str:
        return self._get_string("active-profile", PROFILE_NAMES[0])

    def set_active_profile(self, profile_name: str) -> bool:
        if profile_name not in PROFILE_NAMES:
            return False
        success = self._set_string("active-profile", profile_name)
        if success:
            self.restart_runtime()
        return success

    def apply_profile(self, profile_name: str) -> bool:
        if self._settings is None or profile_name not in PROFILE_DEFAULTS:
            return False
        try:
            self._settings.delay()
            self._settings.set_string("active-profile", profile_name)
            for key, value in PROFILE_DEFAULTS[profile_name].items():
                if isinstance(value, bool):
                    self._settings.set_boolean(key, value)
                elif isinstance(value, int):
                    self._settings.set_int(key, value)
                elif isinstance(value, float):
                    self._settings.set_double(key, value)
                else:
                    self._settings.set_string(key, str(value))
            self._settings.apply()
        except Exception:
            return False
        self.restart_runtime()
        return True

    def set_binding_enabled(self, key: str, value: bool) -> bool:
        success = self._set_boolean(key, value)
        if success:
            self.restart_runtime()
        return success

    def set_binding_preset(self, preset_key: str, preset_name: str) -> bool:
        success = self._set_string(preset_key, preset_name)
        if success:
            self.restart_runtime()
        return success

    def set_binding_duration(self, duration_key: str, value: int) -> bool:
        success = self._set_int(duration_key, value)
        if success:
            self.restart_runtime()
        return success

    def set_binding_delay(self, delay_key: str, value: int) -> bool:
        success = self._set_int(delay_key, value)
        if success:
            self.restart_runtime()
        return success

    def set_binding_intensity(self, intensity_key: str, value: float) -> bool:
        success = self._set_double(intensity_key, value)
        if success:
            self.restart_runtime()
        return success

    def set_runtime_flag(self, key: str, value: bool) -> bool:
        success = self._set_boolean(key, value)
        if success:
            self.restart_runtime()
        return success

    def get_runtime_flag(self, key: str, default: bool = False) -> bool:
        return self._get_boolean(key, default)

    def get_runtime_string(self, key: str, default: str = "") -> str:
        return self._get_string(key, default)

    def set_runtime_string(self, key: str, value: str) -> bool:
        success = self._set_string(key, value)
        if success:
            self.restart_runtime()
        return success

    def get_system_timing(self, key: str, default: int = 250) -> int:
        return self._get_int(key, default)

    def set_system_timing(self, key: str, value: int) -> bool:
        return self._set_int(key, value)

    def bump_custom_presets_version(self):
        current = self._get_int("custom-presets-version", 0)
        self._set_int("custom-presets-version", current + 1)
        self.restart_runtime()

    def get_per_app_overrides(self) -> list[dict]:
        import json
        raw = self._get_string("per-app-overrides", "")
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def set_per_app_overrides(self, overrides: list[dict]) -> bool:
        import json
        success = self._set_string("per-app-overrides", json.dumps(overrides))
        if success:
            self.restart_runtime()
        return success

    def add_per_app_override(self, wm_class: str, match_mode: str, action: str, rule: dict) -> bool:
        overrides = self.get_per_app_overrides()
        entry = next((e for e in overrides if e.get("wm_class", "").lower() == wm_class.lower()), None)
        if entry is None:
            entry = {"wm_class": wm_class, "match_mode": match_mode, "rules": {}}
            overrides.append(entry)
        entry["rules"][action] = rule
        return self.set_per_app_overrides(overrides)

    def remove_per_app_override(self, wm_class: str, action: str | None = None) -> bool:
        overrides = self.get_per_app_overrides()
        if action:
            for entry in overrides:
                if entry.get("wm_class", "").lower() == wm_class.lower():
                    entry["rules"].pop(action, None)
                    if not entry["rules"]:
                        overrides.remove(entry)
                    break
        else:
            overrides = [e for e in overrides if e.get("wm_class", "").lower() != wm_class.lower()]
        return self.set_per_app_overrides(overrides)

    def get_panel_items_available(self) -> dict[str, list[str]]:
        import json
        raw = self._get_string("panel-items-available", "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_panel_layout(self) -> dict[str, list[str]]:
        import json
        raw = self._get_string("panel-layout", "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}

    def set_panel_layout(self, layout: dict[str, list[str]]) -> bool:
        import json
        return self._set_string("panel-layout", json.dumps(layout) if layout else "")

    def restore_defaults(self) -> bool:
        if self._settings is None or self._schema is None:
            return False
        try:
            for key in self._schema.list_keys():
                self._settings.reset(key)
        except Exception:
            return False
        self.restart_runtime()
        return True
