from __future__ import annotations

from more_tweaks.animation_catalog import (
    BINDING_DEFINITIONS,
    BINDINGS_BY_ID,
    GROUP_DEFINITIONS,
    GROUPS_BY_ID,
    MAXIMIZE_PRESETS,
    MOVE_START_PRESETS,
    MOVE_STOP_PRESETS,
    PER_APP_ACTIONS,
    PROFILE_DEFAULTS,
    PROFILE_NAMES,
    RESIZE_START_PRESETS,
    RESIZE_STOP_PRESETS,
    UNMAXIMIZE_PRESETS,
)
from more_tweaks.preset_data import TRANSFORM_PRESETS


class TestPresetCrossValidation:
    def test_all_preset_names_in_transform_presets(self):
        known = set(TRANSFORM_PRESETS.keys())
        for binding in BINDING_DEFINITIONS:
            for name in binding.preset_names:
                assert name in known, (
                    f"Binding {binding.id!r} references preset {name!r} "
                    f"not in TRANSFORM_PRESETS"
                )

    def test_all_transform_presets_referenced(self):
        referenced: set[str] = set()
        for binding in BINDING_DEFINITIONS:
            referenced.update(binding.preset_names)
        # Some presets exist only as preview approximations for runtime-only effects
        preview_only = {"Glass Ripple In", "Glass Ripple Out"}
        for name in TRANSFORM_PRESETS:
            if name in preview_only:
                continue
            assert name in referenced, (
                f"TRANSFORM_PRESETS contains {name!r} not referenced by any binding"
            )

    def test_default_preset_in_preset_names(self):
        for binding in BINDING_DEFINITIONS:
            assert binding.default_preset in binding.preset_names, (
                f"Binding {binding.id!r}: default_preset {binding.default_preset!r} "
                f"not in preset_names"
            )


class TestProfileCompleteness:
    def test_all_profiles_have_entries(self):
        for name in PROFILE_NAMES:
            assert name in PROFILE_DEFAULTS, f"Profile {name!r} missing from PROFILE_DEFAULTS"

    def test_profile_preset_values_valid(self):
        known = set(TRANSFORM_PRESETS.keys())
        for profile_name, settings in PROFILE_DEFAULTS.items():
            for key, value in settings.items():
                if key.endswith("-preset") and isinstance(value, str):
                    assert value in known, (
                        f"Profile {profile_name!r} key {key!r} references "
                        f"unknown preset {value!r}"
                    )

    def test_profile_keys_reference_valid_bindings(self):
        valid_keys: set[str] = set()
        for binding in BINDING_DEFINITIONS:
            valid_keys.add(binding.enabled_key)
            valid_keys.add(binding.preset_key)
            valid_keys.add(binding.duration_key)
            valid_keys.add(binding.delay_key)
            valid_keys.add(binding.intensity_key)
        for profile_name, settings in PROFILE_DEFAULTS.items():
            for key in settings:
                assert key in valid_keys, (
                    f"Profile {profile_name!r} contains key {key!r} "
                    f"not matching any binding"
                )


class TestBindingConstraints:
    def test_binding_key_formats(self):
        for binding in BINDING_DEFINITIONS:
            assert binding.enabled_key == f"{binding.id}-enabled"
            assert binding.preset_key == f"{binding.id}-preset"
            assert binding.duration_key == f"{binding.id}-duration-ms"
            assert binding.delay_key == f"{binding.id}-delay-ms"
            assert binding.intensity_key == f"{binding.id}-intensity"

    def test_default_durations_reasonable(self):
        for binding in BINDING_DEFINITIONS:
            assert 50 <= binding.default_duration_ms <= 2000, (
                f"Binding {binding.id!r}: duration {binding.default_duration_ms}ms "
                f"outside 50-2000 range"
            )

    def test_default_intensities_reasonable(self):
        for binding in BINDING_DEFINITIONS:
            assert 0.1 <= binding.default_intensity <= 2.0, (
                f"Binding {binding.id!r}: intensity {binding.default_intensity} "
                f"outside 0.1-2.0 range"
            )

    def test_default_delays_non_negative(self):
        for binding in BINDING_DEFINITIONS:
            assert binding.default_delay_ms >= 0, (
                f"Binding {binding.id!r}: delay {binding.default_delay_ms}ms is negative"
            )

    def test_valid_group_references(self):
        for binding in BINDING_DEFINITIONS:
            assert binding.group_id in GROUPS_BY_ID, (
                f"Binding {binding.id!r} references unknown group {binding.group_id!r}"
            )

    def test_valid_tiers(self):
        for binding in BINDING_DEFINITIONS:
            assert binding.tier in ("core", "advanced"), (
                f"Binding {binding.id!r} has invalid tier {binding.tier!r}"
            )


class TestPerAppActions:
    def test_actions_subset_of_binding_actions(self):
        binding_actions = {b.action for b in BINDING_DEFINITIONS}
        for action in PER_APP_ACTIONS:
            assert action in binding_actions, (
                f"PER_APP_ACTIONS contains {action!r} not found in any binding"
            )


class TestPhysicsPresetsInLists:
    def test_jelly_grab_in_move_start(self):
        assert "Jelly Grab" in MOVE_START_PRESETS

    def test_wobbly_drop_in_move_stop(self):
        assert "Wobbly Drop" in MOVE_STOP_PRESETS

    def test_rubber_stretch_in_resize_start(self):
        assert "Rubber Stretch" in RESIZE_START_PRESETS

    def test_spring_snap_in_resize_stop(self):
        assert "Spring Snap" in RESIZE_STOP_PRESETS

    def test_snap_wobble_in_maximize(self):
        assert "Snap Wobble" in MAXIMIZE_PRESETS

    def test_release_wobble_in_unmaximize(self):
        assert "Release Wobble" in UNMAXIMIZE_PRESETS
