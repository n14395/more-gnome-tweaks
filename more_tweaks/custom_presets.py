"""Manages custom animation presets stored in a JSON file."""
from __future__ import annotations

import json
import os
import pwd
from pathlib import Path

from .preset_data import PresetPhase, PresetSetup, TransformPreset

_REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
CUSTOM_PRESETS_DIR = _REAL_HOME / ".config" / "more-tweaks"
CUSTOM_PRESETS_FILE = CUSTOM_PRESETS_DIR / "custom-presets.json"


class CustomPresetStore:
    """Read/write custom presets to ~/.config/more-tweaks/custom-presets.json."""

    def __init__(self):
        self._presets: dict[str, dict] = {}
        self.load()

    def load(self):
        if CUSTOM_PRESETS_FILE.exists():
            try:
                data = json.loads(CUSTOM_PRESETS_FILE.read_text())
                self._presets = data.get("presets", {})
            except (json.JSONDecodeError, OSError):
                self._presets = {}
        else:
            self._presets = {}

    def save(self):
        CUSTOM_PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "presets": self._presets}
        CUSTOM_PRESETS_FILE.write_text(json.dumps(data, indent=2))

    def clone_preset(self, source_name: str, new_name: str, preset_data: dict) -> bool:
        from .preset_data import TRANSFORM_PRESETS
        if new_name in TRANSFORM_PRESETS or new_name in self._presets:
            return False
        self._presets[new_name] = {**preset_data, "based_on": source_name}
        self.save()
        return True

    def update_preset(self, name: str, preset_data: dict):
        self._presets[name] = preset_data
        self.save()

    def delete_preset(self, name: str):
        self._presets.pop(name, None)
        self.save()

    def get_preset(self, name: str) -> dict | None:
        return self._presets.get(name)

    def list_presets(self) -> dict[str, dict]:
        return dict(self._presets)

    def preset_names(self) -> list[str]:
        return list(self._presets.keys())

    def to_transform_preset(self, name: str) -> TransformPreset | None:
        data = self._presets.get(name)
        if data is None:
            return None
        try:
            setup_data = data.get("setup", {})
            setup = PresetSetup(
                opacity=setup_data.get("opacity", 255),
                scale_x=setup_data.get("scaleX", 1.0),
                scale_y=setup_data.get("scaleY", 1.0),
                translation_x=setup_data.get("translationX", 0.0),
                translation_y=setup_data.get("translationY", 0.0),
                rotation_z=setup_data.get("rotationZ", 0.0),
                rotation_y=setup_data.get("rotationY", 0.0),
                pivot_x=setup_data.get("pivotX", 0.5),
                pivot_y=setup_data.get("pivotY", 0.5),
            )
            phases = []
            for phase_data in data.get("phases", []):
                phases.append(PresetPhase(
                    opacity=phase_data.get("opacity"),
                    scale_x=phase_data.get("scaleX"),
                    scale_y=phase_data.get("scaleY"),
                    translation_x=phase_data.get("translationX"),
                    translation_y=phase_data.get("translationY"),
                    rotation_z=phase_data.get("rotationZ"),
                    rotation_y=phase_data.get("rotationY"),
                    duration_scale=phase_data.get("durationScale", 1.0),
                    mode=phase_data.get("mode", "EASE_OUT_CUBIC"),
                ))
            return TransformPreset(
                family=data.get("family", "Custom"),
                setup=setup,
                phases=tuple(phases),
            )
        except (TypeError, KeyError):
            return None

    @staticmethod
    def transform_preset_to_dict(preset: TransformPreset) -> dict:
        """Convert a TransformPreset to the JSON-compatible dict format."""
        setup = {
            "opacity": preset.setup.opacity,
            "scaleX": preset.setup.scale_x,
            "scaleY": preset.setup.scale_y,
            "translationX": preset.setup.translation_x,
            "translationY": preset.setup.translation_y,
            "rotationZ": preset.setup.rotation_z,
            "rotationY": preset.setup.rotation_y,
            "pivotX": preset.setup.pivot_x,
            "pivotY": preset.setup.pivot_y,
        }
        phases = []
        for phase in preset.phases:
            p: dict = {"mode": phase.mode, "durationScale": phase.duration_scale}
            if phase.opacity is not None:
                p["opacity"] = phase.opacity
            if phase.scale_x is not None:
                p["scaleX"] = phase.scale_x
            if phase.scale_y is not None:
                p["scaleY"] = phase.scale_y
            if phase.translation_x is not None:
                p["translationX"] = phase.translation_x
            if phase.translation_y is not None:
                p["translationY"] = phase.translation_y
            if phase.rotation_z is not None:
                p["rotationZ"] = phase.rotation_z
            if phase.rotation_y is not None:
                p["rotationY"] = phase.rotation_y
            phases.append(p)
        return {"family": preset.family, "setup": setup, "phases": phases}
