from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from more_tweaks.preset_data import PresetPhase, PresetSetup, TransformPreset


@pytest.fixture
def tmp_presets_dir(tmp_path):
    presets_dir = tmp_path / "more-tweaks"
    presets_file = presets_dir / "custom-presets.json"
    with (
        patch("more_tweaks.custom_presets.CUSTOM_PRESETS_DIR", presets_dir),
        patch("more_tweaks.custom_presets.CUSTOM_PRESETS_FILE", presets_file),
    ):
        from more_tweaks.custom_presets import CustomPresetStore
        store = CustomPresetStore()
        yield store, presets_file


class TestCustomPresetStore:
    def test_empty_on_fresh_start(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        assert store.list_presets() == {}
        assert store.preset_names() == []

    def test_clone_and_list(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {
            "family": "Custom",
            "setup": {"opacity": 0, "scaleX": 0.9},
            "phases": [{"opacity": 255, "scaleX": 1.0, "mode": "EASE_OUT_CUBIC", "durationScale": 1.0}],
        }
        assert store.clone_preset("Glide In", "My Custom", data) is True
        assert "My Custom" in store.list_presets()

    def test_clone_rejects_duplicate(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        store.clone_preset("Glide In", "My Custom", data)
        assert store.clone_preset("Glide In", "My Custom", data) is False

    def test_clone_rejects_builtin_name(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        assert store.clone_preset("Glide In", "Glide In", data) is False

    def test_save_and_load(self, tmp_presets_dir):
        store, presets_file = tmp_presets_dir
        data = {"family": "Custom", "setup": {"opacity": 128}, "phases": []}
        store.clone_preset("Fade In", "Test Preset", data)

        # Verify file was written
        assert presets_file.exists()
        saved = json.loads(presets_file.read_text())
        assert "Test Preset" in saved["presets"]

        # Create new store and verify it loads
        with (
            patch("more_tweaks.custom_presets.CUSTOM_PRESETS_DIR", presets_file.parent),
            patch("more_tweaks.custom_presets.CUSTOM_PRESETS_FILE", presets_file),
        ):
            from more_tweaks.custom_presets import CustomPresetStore
            store2 = CustomPresetStore()
            assert "Test Preset" in store2.list_presets()

    def test_update_preset(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        store.clone_preset("Fade In", "My Preset", data)
        store.update_preset("My Preset", {"family": "Updated", "setup": {"opacity": 100}, "phases": []})
        assert store.get_preset("My Preset")["family"] == "Updated"

    def test_delete_preset(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        store.clone_preset("Fade In", "To Delete", data)
        store.delete_preset("To Delete")
        assert store.get_preset("To Delete") is None
        assert "To Delete" not in store.preset_names()

    def test_to_transform_preset(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {
            "family": "Custom",
            "setup": {"opacity": 0, "scaleX": 0.9, "scaleY": 0.9},
            "phases": [
                {"opacity": 255, "scaleX": 1.0, "scaleY": 1.0, "mode": "EASE_OUT_CUBIC", "durationScale": 1.0}
            ],
        }
        store.clone_preset("Bloom In", "My Bloom", data)
        tp = store.to_transform_preset("My Bloom")
        assert tp is not None
        assert tp.family == "Custom"
        assert tp.setup.opacity == 0
        assert tp.setup.scale_x == 0.9
        assert len(tp.phases) == 1
        assert tp.phases[0].opacity == 255
        assert tp.phases[0].mode == "EASE_OUT_CUBIC"

    def test_to_transform_preset_missing(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        assert store.to_transform_preset("nonexistent") is None


    def test_create_preset(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {"opacity": 0}, "phases": [{"opacity": 255}]}
        assert store.create_preset("My New Preset", data) is True
        assert "My New Preset" in store.list_presets()
        assert store.get_preset("My New Preset")["family"] == "Custom"

    def test_create_preset_rejects_empty_name(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        assert store.create_preset("", data) is False
        assert store.create_preset("   ", data) is False

    def test_create_preset_rejects_builtin_name(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        assert store.create_preset("Glide In", data) is False

    def test_create_preset_rejects_duplicate(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        store.create_preset("My Preset", data)
        assert store.create_preset("My Preset", data) is False

    def test_rename_preset(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {"opacity": 42}, "phases": []}
        store.create_preset("Old Name", data)
        assert store.rename_preset("Old Name", "New Name") is True
        assert store.get_preset("Old Name") is None
        assert store.get_preset("New Name") is not None
        assert store.get_preset("New Name")["setup"]["opacity"] == 42

    def test_rename_preset_noop(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        store.create_preset("Same Name", data)
        assert store.rename_preset("Same Name", "Same Name") is True
        assert "Same Name" in store.preset_names()

    def test_rename_preset_rejects_nonexistent(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        assert store.rename_preset("Does Not Exist", "New") is False

    def test_rename_preset_rejects_conflict(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        store.create_preset("Preset A", data)
        store.create_preset("Preset B", data)
        assert store.rename_preset("Preset A", "Preset B") is False
        assert store.rename_preset("Preset A", "Glide In") is False

    def test_name_is_available(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {}, "phases": []}
        store.create_preset("Taken", data)
        assert store.name_is_available("Free Name") is True
        assert store.name_is_available("Taken") is False
        assert store.name_is_available("Taken", exclude="Taken") is True
        assert store.name_is_available("Glide In") is False
        assert store.name_is_available("") is False
        assert store.name_is_available("   ") is False


    def test_create_rename_edit_delete_lifecycle(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        data = {"family": "Custom", "setup": {"opacity": 0}, "phases": [{"opacity": 255}]}
        assert store.create_preset("Lifecycle Test", data) is True
        assert "Lifecycle Test" in store.preset_names()

        assert store.rename_preset("Lifecycle Test", "Renamed Test") is True
        assert "Lifecycle Test" not in store.preset_names()
        assert "Renamed Test" in store.preset_names()

        store.update_preset("Renamed Test", {"family": "Updated", "setup": {"opacity": 128}, "phases": []})
        assert store.get_preset("Renamed Test")["family"] == "Updated"

        store.delete_preset("Renamed Test")
        assert store.get_preset("Renamed Test") is None

    def test_clone_custom_preset(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        original = {"family": "Custom", "setup": {"opacity": 42}, "phases": [{"opacity": 255}]}
        store.create_preset("Original", original)
        # Clone the custom preset by getting its data and cloning
        preset_data = store.get_preset("Original")
        assert store.clone_preset("Original", "Cloned", preset_data) is True
        cloned = store.get_preset("Cloned")
        assert cloned is not None
        assert cloned["based_on"] == "Original"
        assert cloned["setup"]["opacity"] == 42


class TestDefaultBlankPreset:
    def test_structure(self):
        from more_tweaks.custom_presets import DEFAULT_BLANK_PRESET
        assert "family" in DEFAULT_BLANK_PRESET
        assert "setup" in DEFAULT_BLANK_PRESET
        assert "phases" in DEFAULT_BLANK_PRESET
        setup = DEFAULT_BLANK_PRESET["setup"]
        for key in ("opacity", "scaleX", "scaleY", "translationX", "translationY",
                     "rotationZ", "rotationY", "pivotX", "pivotY"):
            assert key in setup, f"DEFAULT_BLANK_PRESET setup missing {key!r}"
        assert len(DEFAULT_BLANK_PRESET["phases"]) >= 1

    def test_valid_values(self):
        from more_tweaks.custom_presets import DEFAULT_BLANK_PRESET
        setup = DEFAULT_BLANK_PRESET["setup"]
        assert 0 <= setup["opacity"] <= 255
        assert setup["scaleX"] > 0
        assert setup["scaleY"] > 0
        phase = DEFAULT_BLANK_PRESET["phases"][0]
        assert phase["mode"] in ("EASE_OUT_CUBIC", "EASE_IN_CUBIC", "EASE_OUT_QUAD",
                                  "EASE_IN_QUAD", "EASE_OUT_BOUNCE", "LINEAR")
        assert phase.get("durationScale", 1.0) > 0


class TestTransformPresetToDict:
    def test_round_trip(self, tmp_presets_dir):
        store, _ = tmp_presets_dir
        from more_tweaks.custom_presets import CustomPresetStore

        preset = TransformPreset(
            family="Test",
            setup=PresetSetup(opacity=0, scale_x=0.88, scale_y=0.88, translation_y=18.0),
            phases=(
                PresetPhase(opacity=255, scale_x=1.03, scale_y=1.03, translation_y=0.0, mode="EASE_OUT_CUBIC", duration_scale=0.82),
                PresetPhase(scale_x=1.0, scale_y=1.0, mode="EASE_OUT_QUAD", duration_scale=0.18),
            ),
        )

        data = CustomPresetStore.transform_preset_to_dict(preset)
        assert data["family"] == "Test"
        assert data["setup"]["opacity"] == 0
        assert data["setup"]["scaleX"] == 0.88
        assert len(data["phases"]) == 2
        assert data["phases"][0]["opacity"] == 255
        assert data["phases"][1].get("opacity") is None
